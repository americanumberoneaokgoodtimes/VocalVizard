"""ATLAS mode — three zoom levels, progressive tile delivery, cache-aware."""
from __future__ import annotations

import asyncio
import logging
from typing import Callable, Optional

import numpy as np

from modes.base import BaseMode
from vv_io.reader import ChunkedAudioReader
from vv_io.cache import ChunkCache
from dsp.pipeline import AnalysisParams
from dsp.recovery import RecoveryParams
from dsp.synthesis import SynthesisParams

logger = logging.getLogger(__name__)


class AtlasMode(BaseMode):
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
        self._reader = reader
        self._cancelled = False
        self._scout_task = asyncio.create_task(self._scout_pass(ws_send))

    async def on_chunk_requested(
        self, chunk_idx: int, priority: str, ws_send: Callable
    ) -> None:
        """Deliver tiles progressively: zoom 1 → 2 → 3."""
        loop = asyncio.get_running_loop()
        file_id = self._reader._info.file_id if self._reader._info else "unknown"

        for zoom in (1, 2, 3):
            if self._cancelled:
                return
            cache_key = self._cache.make_key(
                file_id, chunk_idx, {"task": f"atlas_z{zoom}"}
            )
            cached = self._cache.get(cache_key)
            if cached is not None:
                await ws_send({"type": "tile_ready", "chunk_idx": chunk_idx, "zoom": zoom, "cached": True})
                continue

            await ws_send({"type": "tile_computing", "chunk_idx": chunk_idx, "zoom": zoom})
            result = await loop.run_in_executor(None, self._compute_tile, chunk_idx, zoom)
            self._cache.put(cache_key, result)
            await ws_send({"type": "tile_ready", "chunk_idx": chunk_idx, "zoom": zoom, "cached": False})

    def cancel_all(self) -> None:
        self._cancelled = True
        if self._scout_task and not self._scout_task.done():
            self._scout_task.cancel()

    # ------------------------------------------------------------------
    # Scout pass — fills zoom-1 tiles for all chunks
    # ------------------------------------------------------------------

    async def _scout_pass(self, ws_send: Callable) -> None:
        from dsp.vad import compute_vad_chunk

        loop = asyncio.get_running_loop()
        num_chunks = self._reader.num_chunks
        file_id = self._reader._info.file_id if self._reader._info else "unknown"

        for chunk_idx in range(num_chunks):
            if self._cancelled:
                return
            try:
                cache_key = self._cache.make_key(file_id, chunk_idx, {"task": "atlas_z1"})
                if self._cache.get(cache_key) is not None:
                    continue

                samples = await loop.run_in_executor(
                    None, self._reader.read_chunk, chunk_idx
                )
                sr = self._reader.target_sr
                scores = await loop.run_in_executor(
                    None, compute_vad_chunk, samples, sr
                )
                envelope = float(np.abs(samples).mean())
                tile = {"vad": scores.tolist(), "envelope": envelope}
                self._cache.put(cache_key, tile)

                await ws_send({
                    "type": "tile_ready",
                    "chunk_idx": chunk_idx,
                    "zoom": 1,
                    "cached": False,
                })
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.warning("Atlas scout error on chunk %d: %s", chunk_idx, exc)

    # ------------------------------------------------------------------
    # Tile computation (synchronous — called in thread pool)
    # ------------------------------------------------------------------

    def _compute_tile(self, chunk_idx: int, zoom: int) -> dict:
        if zoom == 1:
            return self._tile_z1(chunk_idx)
        elif zoom == 2:
            return self._tile_z2(chunk_idx)
        else:
            return self._tile_z3(chunk_idx)

    def _tile_z1(self, chunk_idx: int) -> dict:
        """VAD + amplitude envelope only."""
        from dsp.vad import compute_vad_chunk

        samples = self._reader.read_chunk(chunk_idx)
        sr = self._reader.target_sr
        scores = compute_vad_chunk(samples, sr)
        envelope = float(np.abs(samples).mean())
        return {"vad": scores.tolist(), "envelope": envelope}

    def _tile_z2(self, chunk_idx: int) -> dict:
        """Reduced-resolution STFT, no LPC."""
        import scipy.signal

        samples = self._reader.read_chunk(chunk_idx)
        sr = self._reader.target_sr
        _, _, Zxx = scipy.signal.stft(
            samples, fs=sr, nperseg=1024, noverlap=512,
            window="blackmanharris",
        )
        power = np.abs(Zxx) ** 2
        return {"shape": list(power.shape), "mean_power": float(power.mean())}

    def _tile_z3(self, chunk_idx: int) -> dict:
        """Full pipeline — same as TRIAGE Dive."""
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
