"""STFT pipeline — short-time Fourier transform, noise floor estimation, spectral oversubtraction."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import scipy.signal


@dataclass
class AnalysisParams:
    fft_size: int = 1024
    hop_size: int = 128
    lpc_order: int = 18
    alpha: float = 2.20        # oversubtraction factor
    beta: float = 0.008        # spectral floor factor


@dataclass
class STFTResult:
    raw_power: np.ndarray      # shape [num_frames, num_bins], float32
    clean_power: np.ndarray    # shape [num_frames, num_bins], float32
    noise_floor: np.ndarray    # shape [num_bins], float32
    frequencies: np.ndarray    # shape [num_bins], float32 (Hz)
    time_stamps: np.ndarray    # shape [num_frames], float32 (seconds)
    num_frames: int
    num_bins: int


class STFTPipeline:
    def __init__(self, params: AnalysisParams, sample_rate: int = 24000) -> None:
        self._params = params
        self._sample_rate = sample_rate

    def compute(self, samples: np.ndarray) -> STFTResult:
        p = self._params
        sr = self._sample_rate

        f, t, Zxx = scipy.signal.stft(
            samples.astype(np.float32),
            fs=sr,
            nperseg=p.fft_size,
            noverlap=p.fft_size - p.hop_size,
            window="blackmanharris",
        )

        num_bins = p.fft_size // 2
        # Zxx shape: [num_bins+1, num_frames] — drop DC+Nyquist bin to keep num_bins
        mag = np.abs(Zxx[:num_bins, :])  # [num_bins, num_frames]

        # Power: shape [num_frames, num_bins]
        raw_power = (mag.T ** 2 / p.fft_size).astype(np.float32)

        # Per-bin noise floor: 20th percentile over time
        noise_floor = np.percentile(raw_power, 20, axis=0).astype(np.float32)
        # Guard against zeros
        noise_floor = np.maximum(noise_floor, 1e-20)

        # Wiener-style spectral oversubtraction
        clean_power = np.maximum(
            p.beta * noise_floor,
            raw_power - p.alpha * noise_floor,
        ).astype(np.float32)

        frequencies = f[:num_bins].astype(np.float32)
        time_stamps = t.astype(np.float32)

        return STFTResult(
            raw_power=raw_power,
            clean_power=clean_power,
            noise_floor=noise_floor,
            frequencies=frequencies,
            time_stamps=time_stamps,
            num_frames=raw_power.shape[0],
            num_bins=num_bins,
        )
