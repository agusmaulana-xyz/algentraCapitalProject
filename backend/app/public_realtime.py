import asyncio
from concurrent.futures import Future
import threading
import time
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect


class PublicPerformanceHub:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._history_lock = threading.Lock()
        self._last_history_publish = 0.0

    async def connect(self, websocket: WebSocket) -> None:
        self._loop = asyncio.get_running_loop()
        await websocket.accept()
        self._clients.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self._clients.discard(websocket)

    def history_refresh_due(self) -> bool:
        with self._history_lock:
            return time.monotonic() - self._last_history_publish >= 60

    def mark_history_published(self) -> None:
        with self._history_lock:
            self._last_history_publish = time.monotonic()

    @property
    def connected(self) -> bool:
        return bool(self._clients)

    def publish(self, payload: dict[str, Any]) -> Future[Any] | None:
        loop = self._loop
        if loop is None or loop.is_closed() or not self._clients:
            return None
        return asyncio.run_coroutine_threadsafe(self._broadcast(payload), loop)

    async def _broadcast(self, payload: dict[str, Any]) -> None:
        for websocket in tuple(self._clients):
            try:
                await websocket.send_json(payload)
            except (OSError, RuntimeError, WebSocketDisconnect):
                self.disconnect(websocket)


public_performance_hub = PublicPerformanceHub()
