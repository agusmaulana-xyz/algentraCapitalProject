from collections import defaultdict, deque
import hmac
import json
import secrets
import time

from fastapi import HTTPException, Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send


SESSION_COOKIE_NAME = "copytrade_admin_session"
SESSION_DEFAULT_MAX_AGE = 12 * 60 * 60
REMEMBER_CLIENT_MAX_AGE = 30 * 24 * 60 * 60
SESSION_SIGNER_MAX_AGE = REMEMBER_CLIENT_MAX_AGE
AUTH_EXPIRES_SESSION_KEY = "auth_expires_at"
REMEMBER_SESSION_KEY = "remember_client"


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


class SessionExpiryMiddleware:
    """Enforce the authenticated session expiry stored in the signed session."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        session = scope.get("session")
        if session is not None:
            is_authenticated = "admin_username" in session or "client_user_id" in session
            expires_at = session.get(AUTH_EXPIRES_SESSION_KEY)
            if is_authenticated and (
                not isinstance(expires_at, (int, float)) or time.time() >= expires_at
            ):
                session.clear()
        await self.app(scope, receive, send)


class SessionCookiePolicyMiddleware:
    """Set a persistent cookie only when a client selected remember-me."""

    def __init__(self, app: ASGIApp, session_cookie: str = SESSION_COOKIE_NAME) -> None:
        self.app = app
        self.session_cookie = session_cookie

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                session = scope.get("session")
            else:
                session = None
            if message["type"] == "http.response.start" and session is not None:
                max_age = REMEMBER_CLIENT_MAX_AGE if session.get(REMEMBER_SESSION_KEY) is True else SESSION_DEFAULT_MAX_AGE
                rewritten_headers = []
                for name, value in message.get("headers", []):
                    if name.lower() == b"set-cookie":
                        cookie = value.decode("latin-1")
                        cookie_pair = cookie.split(";", 1)[0]
                        is_session_cookie = cookie_pair.startswith(f"{self.session_cookie}=")
                        is_deletion = cookie_pair == f"{self.session_cookie}=null" or "expires=thu, 01 jan 1970" in cookie.casefold()
                        if is_session_cookie and not is_deletion:
                            parts = [part.strip() for part in cookie.split(";")]
                            attributes = [part for part in parts[1:] if not part.casefold().startswith("max-age=")]
                            cookie = "; ".join([parts[0], f"Max-Age={max_age}", *attributes])
                            value = cookie.encode("latin-1")
                    rewritten_headers.append((name, value))
                message["headers"] = rewritten_headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


class RateLimitMiddleware:
    """Small in-process request limiter for the single-instance local backend."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.requests: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self.last_cleanup = time.monotonic()

    @staticmethod
    def _limit(path: str) -> tuple[int, int]:
        if path in {"/api/auth/login", "/api/auth/client-login"}:
            return 8, 60
        if path in {"/api/auth/register", "/api/auth/resend-code"}:
            return 4, 60
        if path == "/api/auth/verify-email":
            return 10, 60
        if path in {"/api/ea/master/snapshot", "/api/mt5/follower/positions"}:
            return 720, 60
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
