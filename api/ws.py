"""WebSocket connection manager and message dispatcher."""
from __future__ import annotations

import logging
from typing import Any, Callable

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WebSocketManager:
    def __init__(self) -> None:
        self._connections: list[WebSocket] = []
        # Handlers registered by message type
        self._handlers: dict[str, Callable] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        self._handlers["ping"] = self._handle_ping

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        if ws in self._connections:
            self._connections.remove(ws)

    async def broadcast(self, msg: dict) -> None:
        for ws in list(self._connections):
            try:
                await ws.send_json(msg)
            except Exception:
                await self.disconnect(ws)

    async def handle_message(self, ws: WebSocket, msg: dict) -> None:
        msg_type = msg.get("type", "")
        handler = self._handlers.get(msg_type)
        if handler:
            await handler(ws, msg)
        else:
            logger.warning("Unhandled WebSocket message type: %s", msg_type)

    # --- default handlers ---

    async def _handle_ping(self, ws: WebSocket, msg: dict) -> None:
        await ws.send_json({"type": "pong"})

    # --- handler registration ---

    def register(self, msg_type: str, handler: Callable) -> None:
        self._handlers[msg_type] = handler


# Module-level singleton used by server.py
manager = WebSocketManager()
