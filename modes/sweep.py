"""SWEEP mode — full-file parallel recovery using asyncio priority queue + thread pool."""
from __future__ import annotations

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

from modes.base import BaseMode
from vv_io.reader import ChunkedAudioReader
from vv_io.cache import ChunkCache
from dsp.pipeline import AnalysisParams
from dsp.recovery import RecoveryParams
from dsp.synthesis import SynthesisParams

logger = logging.getLogger(__name__)

_PRIORITY_HIGH = 0
_PRIORITY_NORMAL = 1


class SweepMode(BaseMode):
    def __init__(
        self,
        reader: ChunkedAudioReader,
        cache: ChunkCache,
        params: AnalysisParams,
        recovery_params: RecoveryParams,
        synthesis_params: SynthesisParams,
        num_workers: int = None,
    ) -> None:
        self._reader = reader
        self._cache = cache
        self._params = params
        self._recovery_params = recovery_params
        self._synthesis_params = synthesis_params
        self._num_workers = num_workers or max(1, min(4, (os.cpu_count() or 2) // 2))
        self._cancelled = False
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._executor: Optional[ThreadPoolExecutor] = None
        self._sweep_task: Optional[asyncio.Task] = None
        self._queued: set = set()

    # ------------------------------------------------------------------
    # BaseMode interface
    # ------------------------------------------------------------------

    async def on_file_opened(self, reader: ChunkedAudioReader, ws_send: Callable) -> None:
        self._reader = reader
        self._cancelled = False
        self._queue = asyncio.PriorityQueue()
        self._queued = set()
        self._executor = ThreadPoolExecutor(max_workers=self._num_workers)

        for chunk_idx in range(reader.num_chunks):
            await self._queue.put((_PRIORITY_NORMAL, chunk_idx))
            self._queued.add(chunk_idx)

        self._sweep_task = asyncio.create_task(self._sweep_loop(ws_send))

    async def on_chunk_requested(
        self, chunk_idx: int, priority: str, ws_send: Callable
    ) -> None:
        """Boost chunk to front of queue."""
        await self._queue.put((_PRIORITY_HIGH, chunk_idx))
        # Don't add to _queued so duplicates are handled (worker skips cached)

    def cancel_all(self) -> None:
        self._cancelled = True
        if self._sweep_task and not self._sweep_task.done():
            self._sweep_task.cancel()
        if self._executor:
            self._executor.shutdown(wait=False, cancel_futures=True)

    # ------------------------------------------------------------------
    # Sweep loop
    # ------------------------------------------------------------------

    async def _sweep_loop(self, ws_send: Callable) -> None:
        loop = asyncio.get_event_loop()
        num_chunks = self._reader.num_chunks
        completed = 0

        while completed < num_chunks and not self._cancelled:
            try:
                try:
                    _, chunk_idx = await asyncio.wait_for(self._queue.get(), timeout=2.0)
                except asyncio.TimeoutError:
                    continue

                if self._cancelled:
                    break

                file_id = self._reader._info.file_id if self._reader._info else "unknown"
                cache_key = self._cache.make_key(file_id, chunk_idx, {"task": "sweep"})

                if self._cache.get(cache_key) is not None:
                    # Already processed (e.g., duplicate priority insertion)
                    await ws_send({"type": "chunk_ready", "chunk_idx": chunk_idx, "cached": True})
                    if chunk_idx in self._queued:
                        self._queued.discard(chunk_idx)
                        completed += 1
                        await ws_send({
                            "type": "sweep_progress",
                            "completed": completed,
                            "total": num_chunks,
                        })
                    continue

                try:
                    result = await loop.run_in_executor(
                        self._executor, self._process_chunk, chunk_idx
                    )
                except asyncio.CancelledError:
                    return
                except Exception as exc:
                    logger.warning("Sweep error on chunk %d: %s", chunk_idx, exc)
                    self._queued.discard(chunk_idx)
                    continue

                if self._cancelled:
                    return

                self._cache.put(cache_key, result)
                self._queued.discard(chunk_idx)
                completed += 1

                await ws_send({"type": "chunk_ready", "chunk_idx": chunk_idx, "cached": False})
                await ws_send({
                    "type": "sweep_progress",
                    "completed": completed,
                    "total": num_chunks,
                })
            except asyncio.CancelledError:
                return

        if not self._cancelled:
            await ws_send({"type": "sweep_complete", "total": num_chunks})

    # ------------------------------------------------------------------
    # Chunk processing (synchronous — called in thread pool)
    # ------------------------------------------------------------------

    def _process_chunk(self, chunk_idx: int) -> dict:
        from dsp.pipeline import STFTPipeline
        from dsp.lpc import analyze_chunk
        from dsp.recovery import build_path_a, build_path_b

        sr = self._reader.target_sr
        samples = self._reader.read_chunk_overlap(chunk_idx, overlap_s=5.0)

        pipe = STFTPipeline(self._params, sr)
        stft = pipe.compute(samples)
        lpc_list, pitch_list = analyze_chunk(stft, sr, self._params.lpc_order)
        path_a = build_path_a(samples, sr, self._recovery_params)
        path_b = build_path_b(lpc_list, pitch_list, path_a, sr, self._synthesis_params)

        return {
            "chunk_idx": chunk_idx,
            "num_frames": len(lpc_list),
            "has_path_a": True,
            "has_path_b": True,
        }
