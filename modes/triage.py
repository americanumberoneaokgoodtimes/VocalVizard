"""TRIAGE mode — cheap VAD scout pass + on-demand Dive with cache."""
from __future__ import annotations

import asyncio
import logging
from typing import Callable, Optional

from modes.base import BaseMode
from vv_io.reader import ChunkedAudioReader
from vv_io.cache import ChunkCache
from dsp.pipeline import AnalysisParams
from dsp.recovery import RecoveryParams
from dsp.synthesis import SynthesisParams

logger = logging.getLogger(__name__)


class TriageMode(BaseMode):
    def __init__(
        self,
        reader: ChunkedAudioReader,
        cache: ChunkCache,
        params: AnalysisParams,
        recovery_params: RecoveryParams,
        synthesis_params: SynthesisParams,
    ) -> None:
        self._reader = reader
        self._cache = cache
        self._params = params
        self._recovery_params = recovery_params
        self._synthesis_params = synthesis_params
        self._cancelled = False
        self._scout_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # BaseMode interface
    # ------------------------------------------------------------------

    async def on_file_opened(self, reader: ChunkedAudioReader, ws_send: Callable) -> None:
        """Start the Scout pass in a background asyncio task."""
        self._reader = reader
        self._cancelled = False
        self._scout_task = asyncio.create_task(self._scout_pass(ws_send))

    async def on_chunk_requested(
        self, chunk_idx: int, priority: str, ws_send: Callable
    ) -> None:
        """Run full pipeline (Dive) for the requested chunk."""
        cache_key = self._cache.make_key(
            self._reader._info.file_id if self._reader._info else "unknown",
            chunk_idx,
            {"task": "dive"},
        )
        cached = self._cache.get(cache_key)
        if cached is not None:
            await ws_send({"type": "chunk_ready", "chunk_idx": chunk_idx, "cached": True})
            return

        # Run Dive in a thread pool to avoid blocking the event loop
        loop = asyncio.get_running_loop()
        await ws_send({"type": "chunk_progress", "chunk_idx": chunk_idx, "pct": 0})

        result = await loop.run_in_executor(None, self._dive, chunk_idx)
        self._cache.put(cache_key, result)
        await ws_send({"type": "chunk_ready", "chunk_idx": chunk_idx, "cached": False})

    def cancel_all(self) -> None:
        self._cancelled = True
        if self._scout_task and not self._scout_task.done():
            self._scout_task.cancel()

    # ------------------------------------------------------------------
    # Scout pass
    # ------------------------------------------------------------------

    async def _scout_pass(self, ws_send: Callable) -> None:
        """Iterate all chunks, compute VAD scores, stream progress messages."""
        from dsp.vad import compute_vad_chunk

        loop = asyncio.get_running_loop()
        num_chunks = self._reader.num_chunks
        vad_timeline = []

        for chunk_idx in range(num_chunks):
            if self._cancelled:
                return

            try:
                samples = await loop.run_in_executor(
                    None, self._reader.read_chunk, chunk_idx
                )
                sr = self._reader.target_sr
                scores = await loop.run_in_executor(
                    None, compute_vad_chunk, samples, sr
                )
                chunk_scores = scores.tolist()
                vad_timeline.extend(chunk_scores)

                await ws_send({
                    "type": "vad_progress",
                    "chunk_idx": chunk_idx,
                    "scores": chunk_scores,
                    "progress": (chunk_idx + 1) / num_chunks,
                })
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.warning("Scout error on chunk %d: %s", chunk_idx, exc)

        if not self._cancelled:
            await ws_send({
                "type": "vad_complete",
                "timeline": vad_timeline,
                "num_chunks": num_chunks,
            })

    # ------------------------------------------------------------------
    # Dive (synchronous — called in thread pool)
    # ------------------------------------------------------------------

    def _dive(self, chunk_idx: int) -> dict:
        """Run full pipeline on a single chunk. Returns a summary dict."""
        from dsp.pipeline import STFTPipeline
        from dsp.lpc import analyze_chunk
        from dsp.recovery import build_path_a, build_path_b

        sr = self._reader.target_sr
        samples = self._reader.read_chunk_overlap(chunk_idx, overlap_s=5.0)

        # STFT + LPC
        pipe = STFTPipeline(self._params, sr)
        stft = pipe.compute(samples)
        lpc_list, pitch_list = analyze_chunk(stft, sr, self._params.lpc_order)

        # Path A
        path_a = build_path_a(samples, sr, self._recovery_params)

        # Path B
        path_b = build_path_b(lpc_list, pitch_list, path_a, sr, self._synthesis_params)

        return {
            "chunk_idx": chunk_idx,
            "num_frames": len(lpc_list),
            "has_path_a": True,
            "has_path_b": True,
        }
