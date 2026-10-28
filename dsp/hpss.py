"""HPSS — Harmonic-Percussive Source Separation + Harmonic Product Spectrum F0."""
from __future__ import annotations

from typing import Tuple

import numpy as np


def apply_hpss(
    stft_magnitude: np.ndarray,
    margin: float = 1.0,
) -> Tuple[np.ndarray, np.ndarray]:
    """Separate a magnitude spectrogram into harmonic and percussive components.

    Parameters
    ----------
    stft_magnitude : 2-D float32 array, shape [num_frames, num_bins]
    margin         : separation margin (1.0 = soft, >1 = harder separation)

    Returns
    -------
    harmonic, percussive : same shape as input, harmonic + percussive ≈ input
    """
    import librosa

    # librosa.effects.hpss expects [bins, frames]
    mag_T = stft_magnitude.T  # [bins, frames]
    h_T, p_T = librosa.decompose.hpss(mag_T, margin=margin)
    harmonic = h_T.T.astype(np.float32)
    percussive = p_T.T.astype(np.float32)
    return harmonic, percussive


# ---------------------------------------------------------------------------
# Harmonic Product Spectrum F0 detection
# ---------------------------------------------------------------------------

_HPS_F0_MIN = 75.0
_HPS_F0_MAX = 380.0
_HPS_SCORE_THRESHOLD = 1e-20


def compute_hps_f0(
    power: np.ndarray,
    sample_rate: int,
    num_harmonics: int = 5,
) -> float:
    """Detect fundamental frequency via Harmonic Product Spectrum.

    Searches F0 candidates from 75–380 Hz in 1 Hz steps, computes the product
    of power at the first num_harmonics harmonic frequencies, returns the
    candidate with the highest HPS score. Returns 0.0 if no clear pitch.

    Parameters
    ----------
    power        : 1-D float32 power spectrum, shape [num_bins]
    sample_rate  : Hz
    num_harmonics: number of harmonics to multiply

    Returns
    -------
    f0 in Hz, or 0.0 if unvoiced
    """
    num_bins = len(power)
    freq_resolution = (sample_rate / 2.0) / num_bins  # Hz per bin

    best_f0 = 0.0
    best_score = 0.0

    # Step in 1 Hz steps for accuracy
    f0_candidates = np.arange(_HPS_F0_MIN, _HPS_F0_MAX + 1, 1.0)

    for f0 in f0_candidates:
        score = 1.0
        valid = True
        for h in range(1, num_harmonics + 1):
            bin_idx = int(round(h * f0 / freq_resolution))
            if bin_idx >= num_bins:
                valid = False
                break
            score *= float(power[bin_idx]) + 1e-30

        if valid and score > best_score:
            best_score = score
            best_f0 = f0

    if best_score <= _HPS_SCORE_THRESHOLD:
        return 0.0

    return float(best_f0)
