"""WebSocket connection manager and message dispatcher."""
from __future__ import annotations

import logging
from typing import Callable, Optional

from fastapi import WebSocket

logger = logging.getLogger(__name__)

# Current active mode instance (set by set_mode handler)
_current_mode = None


class WebSocketManager:
    def __init__(self) -> None:
        self._connections: list[WebSocket] = []
        self._handlers: dict[str, Callable] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        self._handlers["ping"] = self._handle_ping
        self._handlers["open_file"] = self._handle_open_file
        self._handlers["set_recovery"] = self._handle_set_recovery
        self._handlers["set_mode"] = self._handle_set_mode
        self._handlers["request_chunk"] = self._handle_request_chunk
        self._handlers["cancel_chunk"] = self._handle_cancel_chunk

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
        import os
        from vv_io.reader import ChunkedAudioReader
        from api.routes import set_reader

        raw_path = msg.get("path", "")
        if not raw_path:
            await ws.send_json({"type": "error", "message": "path is required"})
            return
        path = os.path.realpath(os.path.expanduser(raw_path))
        allowed_root = os.path.realpath(os.path.expanduser("~"))
        if not path.startswith(allowed_root + os.sep) and path != allowed_root:
            await ws.send_json({"type": "error", "message": "Path not permitted"})
            return
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

    async def _handle_set_mode(self, ws: WebSocket, msg: dict) -> None:
        global _current_mode
        from api.routes import (
            _current_reader, _current_cache, _synthesis_params, set_mode
        )
        from dsp.pipeline import AnalysisParams
        from dsp.recovery import RecoveryParams

        mode_name = msg.get("mode", "triage")

        # Cancel previous mode
        if _current_mode is not None:
            try:
                _current_mode.cancel_all()
            except Exception:
                pass

        set_mode(mode_name)

        if _current_reader is None:
            await ws.send_json({"type": "error", "message": "No file open — open a file first"})
            return

        try:
            if mode_name == "triage":
                from modes.triage import TriageMode
                _current_mode = TriageMode(
                    _current_reader, _current_cache or _no_cache(),
                    AnalysisParams(), RecoveryParams(), _synthesis_params,
                )
            elif mode_name == "atlas":
                from modes.atlas import AtlasMode
                _current_mode = AtlasMode(
                    _current_reader, _current_cache or _no_cache(),
                    AnalysisParams(), RecoveryParams(), _synthesis_params,
                )
            elif mode_name == "sweep":
                from modes.sweep import SweepMode
                _current_mode = SweepMode(
                    _current_reader, _current_cache or _no_cache(),
                    AnalysisParams(), RecoveryParams(), _synthesis_params,
                )
            else:
                await ws.send_json({"type": "error", "message": f"Unknown mode: {mode_name}"})
                return

            send = _make_sender(ws)
            await _current_mode.on_file_opened(_current_reader, send)
            await ws.send_json({"type": "mode_set", "mode": mode_name})
        except Exception as exc:
            await ws.send_json({"type": "error", "message": str(exc)})

    async def _handle_request_chunk(self, ws: WebSocket, msg: dict) -> None:
        global _current_mode
        if _current_mode is None:
            await ws.send_json({"type": "error", "message": "No active mode"})
            return
        chunk_idx = int(msg.get("chunk_idx", 0))
        from api.routes import _current_reader
        if _current_reader is not None and not (0 <= chunk_idx < _current_reader.num_chunks):
            await ws.send_json({"type": "error", "message": f"chunk_idx {chunk_idx} out of range"})
            return
        priority = msg.get("priority", "normal")
        send = _make_sender(ws)
        await _current_mode.on_chunk_requested(chunk_idx, priority, send)

    async def _handle_cancel_chunk(self, ws: WebSocket, msg: dict) -> None:
        logger.warning("cancel_chunk not yet implemented")

    def register(self, msg_type: str, handler: Callable) -> None:
        self._handlers[msg_type] = handler


def _make_sender(ws: WebSocket) -> Callable:
    async def send(msg: dict) -> None:
        try:
            await ws.send_json(msg)
        except Exception:
            pass
    return send


def _no_cache():
    from vv_io.cache import ChunkCache
    return ChunkCache(".vocvizard_cache")


manager = WebSocketManager()
