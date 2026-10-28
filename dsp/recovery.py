"""Recovery engine — Path A (cleaned signal) and Path B (synthetic reconstruction)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple

import numpy as np
import scipy.signal


@dataclass
class RecoveryParams:
    alpha: float = 2.20
    hpss_margin: float = 1.0
    fft_sizes: Tuple[int, ...] = (512, 1024, 2048)
    hop_size: int = 128


# ---------------------------------------------------------------------------
# Path A: multi-resolution STFT + HPSS harmonic extraction
# ---------------------------------------------------------------------------

def build_path_a(
    samples: np.ndarray,
    sample_rate: int,
    params: RecoveryParams,
) -> np.ndarray:
    """Recover cleaned vocal signal via multi-resolution Wiener filtering + HPSS.

    Steps:
    1. Compute STFT at each of params.fft_sizes
    2. Per resolution: noise floor (20th pct) → Wiener spectral subtraction
    3. Apply HPSS on 1024-resolution to keep only harmonic component
    4. Fuse three resolutions (element-wise max, resampled to 1024 grid)
    5. Reconstruct via iSTFT using 1024 STFT phase + fused magnitude
    6. Peak-normalise to 0.9, clip to [-1, 1]

    Parameters
    ----------
    samples     : float32 PCM, any length
    sample_rate : Hz
    params      : RecoveryParams

    Returns
    -------
    float32 PCM, same length as input
    """
    from dsp.hpss import apply_hpss

    target_len = len(samples)

    # Compute STFT at each resolution
    stft_results = {}
    for fft_size in params.fft_sizes:
        noverlap = fft_size - params.hop_size
        f, t, Zxx = scipy.signal.stft(
            samples.astype(np.float64),
            fs=sample_rate,
            nperseg=fft_size,
            noverlap=noverlap,
            window="blackmanharris",
        )
        stft_results[fft_size] = (f, t, Zxx)

    # Reference resolution
    ref_size = 1024
    _, t_ref, Zxx_ref = stft_results[ref_size]
    num_bins_ref = ref_size // 2
    ref_mag = np.abs(Zxx_ref[:num_bins_ref, :]).T.astype(np.float32)  # [frames, bins]
    ref_phase = np.angle(Zxx_ref[:num_bins_ref, :]).T.astype(np.float32)

    # Clean each resolution
    cleaned_mags = {}
    for fft_size in params.fft_sizes:
        _, _, Zxx = stft_results[fft_size]
        num_bins = fft_size // 2
        mag = np.abs(Zxx[:num_bins, :]).T.astype(np.float32)  # [frames, bins]

        # Noise floor: 20th percentile per bin
        noise_floor = np.percentile(mag, 20, axis=0).astype(np.float32)
        noise_floor = np.maximum(noise_floor, 1e-20)

        # Wiener subtraction
        clean = np.maximum(
            params.alpha * noise_floor * 0.1,
            mag - params.alpha * noise_floor,
        )
        cleaned_mags[fft_size] = (clean, num_bins)

    # Apply HPSS on reference (1024) — keep harmonic component
    h_mag, _ = apply_hpss(cleaned_mags[ref_size][0], margin=params.hpss_margin)

    # Fuse by taking element-wise max across all resolutions, resampled to ref grid
    fused = h_mag.copy()
    for fft_size in params.fft_sizes:
        if fft_size == ref_size:
            continue
        clean, num_bins = cleaned_mags[fft_size]
        # Resample bin axis to match reference (num_bins_ref bins)
        resampled = np.zeros((clean.shape[0], num_bins_ref), dtype=np.float32)
        old_bins = np.linspace(0, 1, num_bins)
        new_bins = np.linspace(0, 1, num_bins_ref)
        for fi in range(min(clean.shape[0], fused.shape[0])):
            resampled[fi] = np.interp(new_bins, old_bins, clean[fi])
        frames_to_use = min(fused.shape[0], resampled.shape[0])
        fused[:frames_to_use] = np.maximum(fused[:frames_to_use], resampled[:frames_to_use])

    # Reconstruct via iSTFT: fused magnitude × reference phase
    fused_complex = fused * np.exp(1j * ref_phase)  # [frames, bins]

    # Build full (two-sided) complex spectrum for iSTFT
    # Zxx_ref shape: [fft_size//2+1, num_frames] — we need same layout
    fused_full = np.zeros_like(Zxx_ref)
    frames = min(fused.shape[0], fused_full.shape[1])
    fused_full[:num_bins_ref, :frames] = fused_complex[:frames].T

    _, recovered = scipy.signal.istft(
        fused_full,
        fs=sample_rate,
        nperseg=ref_size,
        noverlap=ref_size - params.hop_size,
        window="blackmanharris",
    )

    # Trim or pad to original length
    if len(recovered) >= target_len:
        recovered = recovered[:target_len]
    else:
        recovered = np.pad(recovered, (0, target_len - len(recovered)))

    recovered = recovered.astype(np.float32)

    # Peak-normalise to 0.9
    peak = np.max(np.abs(recovered))
    if peak > 1e-8:
        recovered = recovered * (0.9 / peak)

    return np.clip(recovered, -1.0, 1.0)
