"""LPC engine — Levinson-Durbin, formant extraction, cepstral F0 detection."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
import scipy.signal

from dsp.pipeline import STFTResult


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class FormantPole:
    hz: float
    bw: float
    prom: float
    db: float


@dataclass
class LPCResult:
    lpc_db: np.ndarray           # shape [num_bins], float32 — LPC envelope in dB
    f1: Optional[FormantPole]
    f2: Optional[FormantPole]
    f3: Optional[FormantPole]
    f4: Optional[FormantPole]


@dataclass
class PitchResult:
    f0: float       # 0.0 if unvoiced
    cpp_db: float   # normalised autocorrelation peak prominence × 100


# ---------------------------------------------------------------------------
# Levinson-Durbin
# ---------------------------------------------------------------------------

def solve_levinson_durbin(R: np.ndarray, p: int) -> Tuple[np.ndarray, float]:
    """Solve Yule-Walker equations via Levinson-Durbin recursion.

    Parameters
    ----------
    R : autocorrelation coefficients, length p+1
    p : LPC order

    Returns
    -------
    a  : predictor coefficients, length p+1 (a[0]=1)
    Ep : prediction error power
    """
    a = np.zeros(p + 1, dtype=np.float64)
    a[0] = 1.0
    E = float(R[0])
    if E == 0.0:
        return a, 0.0

    for m in range(1, p + 1):
        lam = -sum(a[j] * R[m - j] for j in range(m)) / E
        lam = max(-0.992, min(0.992, lam))

        a_new = a.copy()
        for j in range(1, m):
            a_new[j] = a[j] + lam * a[m - j]
        a_new[m] = lam
        a = a_new
        E *= 1.0 - lam * lam

    return a, E


# ---------------------------------------------------------------------------
# LPC formant extraction
# ---------------------------------------------------------------------------

_MIN_FORMANT_HZ = 200.0
_MAX_FORMANT_HZ = 4000.0
_MIN_PROMINENCE_DB = 0.5    # dB above surrounding valleys


def extract_lpc_formants(
    clean_power: np.ndarray,
    sample_rate: int,
    lpc_order: int = 18,
) -> LPCResult:
    """Estimate LPC envelope and extract up to 4 formant peaks.

    Approach:
    - LPC envelope computed from Wiener-Khinchin autocorrelation (for lpc_db display)
    - Formant poles detected via peak-finding on the log-power spectrum (robust)

    Parameters
    ----------
    clean_power : 1-D float32 power spectrum, shape [num_bins]
    sample_rate : Hz
    lpc_order   : predictor order (18 matches v4.0 JS)
    """
    num_bins = len(clean_power)
    n_eval = num_bins

    # --- LPC envelope via Wiener-Khinchin autocorrelation ---
    R = np.real(np.fft.irfft(clean_power.astype(np.float64), n=2 * n_eval))[: lpc_order + 1]
    a, Ep = solve_levinson_durbin(R, lpc_order)

    H = np.fft.rfft(a, n=2 * n_eval)[:n_eval]
    lpc_env = 1.0 / np.maximum(np.abs(H), 1e-20)
    lpc_db = (20.0 * np.log10(lpc_env)).astype(np.float32)
    lpc_db -= lpc_db.max()

    # --- Formant poles via direct peak-finding on log-power spectrum ---
    log_power = np.log(np.maximum(clean_power.astype(np.float64), 1e-20))
    eval_freqs = np.linspace(0.0, sample_rate / 2.0, n_eval)

    # Minimum peak distance: ~150 Hz
    hz_per_bin = (sample_rate / 2.0) / n_eval
    min_dist = max(1, int(150.0 / hz_per_bin))

    peak_indices, props = scipy.signal.find_peaks(
        log_power,
        prominence=_MIN_PROMINENCE_DB,
        distance=min_dist,
    )

    formants: List[FormantPole] = []
    for idx in peak_indices:
        hz = float(eval_freqs[idx])
        if hz < _MIN_FORMANT_HZ or hz > _MAX_FORMANT_HZ:
            continue

        peak_db = float(log_power[idx])

        # Bandwidth: half-power (-3 dB) width
        half = peak_db - 3.0
        lo = idx
        while lo > 0 and log_power[lo] > half:
            lo -= 1
        hi = idx
        while hi < n_eval - 1 and log_power[hi] > half:
            hi += 1
        bw = float(eval_freqs[hi] - eval_freqs[lo]) if hi > lo else 80.0

        prom = float(props["prominences"][np.where(peak_indices == idx)[0][0]])

        formants.append(FormantPole(hz=hz, bw=bw, prom=prom, db=peak_db))

    # Sort by frequency
    formants.sort(key=lambda p: p.hz)
    formants = formants[:4]

    f1 = formants[0] if len(formants) > 0 else None
    f2 = formants[1] if len(formants) > 1 else None
    f3 = formants[2] if len(formants) > 2 else None
    f4 = formants[3] if len(formants) > 3 else None

    return LPCResult(lpc_db=lpc_db, f1=f1, f2=f2, f3=f3, f4=f4)


# ---------------------------------------------------------------------------
# Cepstral F0 / autocorrelation pitch detection
# ---------------------------------------------------------------------------

_CPP_THRESHOLD = 10.0   # normalised autocorrelation peak prominence (units: %)
_F0_MIN = 75.0
_F0_MAX = 380.0


def extract_cepstral_pitch(
    clean_power: np.ndarray,
    sample_rate: int,
) -> PitchResult:
    """Detect fundamental frequency via autocorrelation peak prominence (CPP-equivalent).

    Uses Wiener-Khinchin autocorrelation of the power spectrum. The "cpp_db"
    field holds the normalised peak prominence × 100 (dimensionless).

    Returns PitchResult with f0=0.0, cpp_db=0.0 for unvoiced frames.
    """
    num_bins = len(clean_power)

    # Autocorrelation via Wiener-Khinchin (IFFT of power spectrum)
    autocorr = np.real(np.fft.irfft(clean_power.astype(np.float64), n=2 * num_bins))

    q_min = max(1, int(sample_rate / _F0_MAX))
    q_max = min(num_bins - 1, int(sample_rate / _F0_MIN))

    if q_max <= q_min:
        return PitchResult(f0=0.0, cpp_db=0.0)

    search = autocorr[q_min: q_max + 1]
    peak_idx_local = int(np.argmax(search))
    peak_q = peak_idx_local + q_min

    # Parabolic sub-sample interpolation
    if 0 < peak_idx_local < len(search) - 1:
        alpha = search[peak_idx_local - 1]
        beta = search[peak_idx_local]
        gamma = search[peak_idx_local + 1]
        denom = alpha - 2 * beta + gamma
        offset = 0.5 * (alpha - gamma) / denom if denom != 0 else 0.0
        peak_q_refined = float(peak_q) + offset
    else:
        peak_q_refined = float(peak_q)

    f0 = float(sample_rate / peak_q_refined) if peak_q_refined > 0 else 0.0

    # Normalised autocorrelation peak prominence (%)
    zero_lag = float(autocorr[0]) + 1e-20
    peak_val = float(autocorr[peak_q])
    baseline = float(np.mean(search))
    cpp = (peak_val - baseline) / zero_lag * 100.0

    if cpp < _CPP_THRESHOLD:
        return PitchResult(f0=0.0, cpp_db=0.0)

    return PitchResult(f0=f0, cpp_db=cpp)


# ---------------------------------------------------------------------------
# Chunk-level batch analysis
# ---------------------------------------------------------------------------

def analyze_chunk(
    stft_result: STFTResult,
    sample_rate: int,
    lpc_order: int = 18,
) -> Tuple[List[LPCResult], List[PitchResult]]:
    """Run LPC + F0 extraction on every frame in stft_result."""
    lpc_results: List[LPCResult] = []
    pitch_results: List[PitchResult] = []

    for frame_power in stft_result.clean_power:
        lpc_results.append(extract_lpc_formants(frame_power, sample_rate, lpc_order))
        pitch_results.append(extract_cepstral_pitch(frame_power, sample_rate))

    return lpc_results, pitch_results
