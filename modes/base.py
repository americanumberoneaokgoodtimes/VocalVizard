"""BaseMode ABC — interface all processing modes must implement."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable


class BaseMode(ABC):
    @abstractmethod
    async def on_file_opened(self, reader, ws_send: Callable) -> None:
        """Called when a new file is opened. Start background work (e.g. VAD scout)."""

    @abstractmethod
    async def on_chunk_requested(
        self, chunk_idx: int, priority: str, ws_send: Callable
    ) -> None:
        """Called when the UI requests a specific chunk (e.g. user clicked)."""

    @abstractmethod
    def cancel_all(self) -> None:
        """Cancel all in-flight async tasks and workers."""
