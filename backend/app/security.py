from collections import defaultdict, deque
import hmac
import json
import secrets
import time

from fastapi import HTTPException, Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send


def csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not isinstance(token, str) or len(token) < 32:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


def require_csrf(request: Request) -> None:
    expected = request.session.get("csrf_token")
    supplied = request.headers.get("x-csrf-token", "")
    if not isinstance(expected, str) or not supplied or not hmac.compare_digest(expected, supplied):
        raise HTTPException(status_code=403, detail="Token CSRF tidak valid atau kedaluwarsa")


class RateLimitMiddleware:
    """Small in-process request limiter for the single-instance local backend."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.requests: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self.last_cleanup = time.monotonic()

    @staticmethod
    def _limit(path: str) -> tuple[int, int]:
        if path == "/api/auth/login":
            return 8, 60
        if path.startswith("/api/tg/"):
            return 12, 60
        if path == "/api/parser/test":
            return 20, 60
        return 120, 60

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if path in {"/health", "/favicon.ico"}:
            await self.app(scope, receive, send)
            return

        client = scope.get("client")
        identity = str(client[0]) if client else "unknown"
        key = (identity, path)
        limit, window = self._limit(path)
        now = time.monotonic()
        hits = self.requests[key]
        while hits and hits[0] <= now - window:
            hits.popleft()
        if len(hits) >= limit:
            body = json.dumps({"detail": "Terlalu banyak permintaan; coba lagi sebentar."}).encode()
            await send({
                "type": "http.response.start",
                "status": 429,
                "headers": [(b"content-type", b"application/json"), (b"retry-after", str(window).encode())],
            })
            await send({"type": "http.response.body", "body": body})
            return
        hits.append(now)

        if now - self.last_cleanup > 300 or len(self.requests) > 4096:
            cutoff = now - 60
            for old_key in list(self.requests):
                queue = self.requests[old_key]
                while queue and queue[0] <= cutoff:
                    queue.popleft()
                if not queue:
                    self.requests.pop(old_key, None)
            self.last_cleanup = now

        await self.app(scope, receive, send)
