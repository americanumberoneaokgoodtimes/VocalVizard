"""ChunkedAudioReader — streams audio files as fixed-size float32 chunks resampled to target_sr."""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Optional

import numpy as np
import soundfile as sf
import soxr


@dataclass
class AudioInfo:
    duration_s: float
    sample_rate: int        # original, before resampling
    channels: int
    format: str             # e.g. "wav", "mp3"
    file_id: str            # md5 of first 64KB of file


class ChunkedAudioReader:
    """Reads an audio file in fixed-duration chunks, resampling each to target_sr."""

    chunk_duration_s: float
    target_sr: int

    def __init__(
        self,
        path: str,
        chunk_duration_s: float = 60.0,
        target_sr: int = 24000,
    ) -> None:
        self._path = path
        self.chunk_duration_s = chunk_duration_s
        self.target_sr = target_sr
        self._info: Optional[AudioInfo] = None
        self._native_sr: int = 0
        self._native_frames: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def open(self) -> AudioInfo:
        """Read metadata without loading the file into memory."""
        sf_info = sf.info(self._path)
        self._native_sr = sf_info.samplerate
        self._native_frames = sf_info.frames
        file_id = self._compute_file_id()

        # Report sample_rate as target_sr (the rate callers will see)
        self._info = AudioInfo(
            duration_s=sf_info.frames / sf_info.samplerate,
            sample_rate=self.target_sr,
            channels=sf_info.channels,
            format=sf_info.format.lower(),
            file_id=file_id,
        )
        return self._info

    @property
    def num_chunks(self) -> int:
        if self._info is None:
            raise RuntimeError("Call open() first")
        total_s = self._info.duration_s
        return max(1, math.ceil(total_s / self.chunk_duration_s))

    def read_chunk(self, chunk_idx: int) -> np.ndarray:
        """Return float32 samples for chunk_idx, resampled to target_sr.

        The final chunk may be shorter than chunk_duration_s — the array is
        returned as-is (not zero-padded here; callers pad if needed).
        """
        if self._info is None:
            raise RuntimeError("Call open() first")
        start_native, stop_native = self._chunk_native_bounds(chunk_idx)
        raw = self._read_native(start_native, stop_native)
        return self._resample(raw)

    def read_chunk_overlap(self, chunk_idx: int, overlap_s: float = 5.0) -> np.ndarray:
        """Return chunk_idx samples plus overlap_s on each side (clamped to file bounds)."""
        if self._info is None:
            raise RuntimeError("Call open() first")
        start_native, stop_native = self._chunk_native_bounds(chunk_idx)
        overlap_native = int(overlap_s * self._native_sr)
        ext_start = max(0, start_native - overlap_native)
        ext_stop = min(self._native_frames, stop_native + overlap_native)
        raw = self._read_native(ext_start, ext_stop)
        return self._resample(raw)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _chunk_native_bounds(self, chunk_idx: int) -> tuple[int, int]:
        chunk_native = int(self.chunk_duration_s * self._native_sr)
        start = chunk_idx * chunk_native
        stop = min(self._native_frames, start + chunk_native)
        return start, stop

    def _read_native(self, start: int, stop: int) -> np.ndarray:
        """Read samples from [start, stop) in native sample rate, return float32 mono."""
        data, _ = sf.read(
            self._path,
            start=start,
            stop=stop,
            dtype="float32",
            always_2d=True,
        )
        # Downmix to mono
        if data.shape[1] > 1:
            mono = data.mean(axis=1)
        else:
            mono = data[:, 0]
        return mono.astype(np.float32)

    def _resample(self, samples: np.ndarray) -> np.ndarray:
        if self._native_sr == self.target_sr:
            return samples
        resampled = soxr.resample(samples, self._native_sr, self.target_sr, quality="HQ")
        return resampled.astype(np.float32)

    def _compute_file_id(self) -> str:
        with open(self._path, "rb") as fh:
            return hashlib.md5(fh.read(65536)).hexdigest()
