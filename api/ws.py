"""WebSocket connection manager and message dispatcher."""
from __future__ import annotations

import logging
from typing import Callable

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WebSocketManager:
    def __init__(self) -> None:
        self._connections: list[WebSocket] = []
        self._handlers: dict[str, Callable] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        self._handlers["ping"] = self._handle_ping
        self._handlers["open_file"] = self._handle_open_file
        self._handlers["set_recovery"] = self._handle_set_recovery

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

    # --- handlers ---

    async def _handle_ping(self, ws: WebSocket, msg: dict) -> None:
        await ws.send_json({"type": "pong"})

    async def _handle_open_file(self, ws: WebSocket, msg: dict) -> None:
        from vv_io.reader import ChunkedAudioReader
        from api.routes import set_reader

        path = msg.get("path", "")
        try:
            reader = ChunkedAudioReader(path)
            info = reader.open()
            set_reader(reader)
            await ws.send_json({
                "type": "file_opened",
                "duration_s": info.duration_s,
                "sample_rate": info.sample_rate,
                "channels": info.channels,
                "format": info.format,
                "file_id": info.file_id,
                "num_chunks": reader.num_chunks,
            })
        except Exception as exc:
            await ws.send_json({"type": "error", "message": str(exc)})

    async def _handle_set_recovery(self, ws: WebSocket, msg: dict) -> None:
        from dsp.synthesis import SynthesisParams
        from api.routes import set_synthesis_params

        params = SynthesisParams(
            mode=msg.get("synthesis", "generic"),
            gaps=msg.get("gaps", "strict"),
            path_b_threshold=float(msg.get("path_b_threshold", 0.28)),
            blend_ratio=float(msg.get("blend_ratio", 0.5)),
        )
        set_synthesis_params(params)
        await ws.send_json({"type": "recovery_updated", "params": {
            "mode": params.mode,
            "gaps": params.gaps,
            "path_b_threshold": params.path_b_threshold,
            "blend_ratio": params.blend_ratio,
        }})

    def register(self, msg_type: str, handler: Callable) -> None:
        self._handlers[msg_type] = handler


manager = WebSocketManager()
