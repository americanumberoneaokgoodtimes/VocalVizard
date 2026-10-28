import numpy as np
import pytest
from dsp.lpc import (
    solve_levinson_durbin, extract_lpc_formants, extract_cepstral_pitch,
    LPCResult, PitchResult
)


def test_levinson_durbin_stability():
    # Autocorrelation of a 730 Hz sine should yield stable predictor
    sr = 24000
    t = np.linspace(0, 1, sr, endpoint=False)
    x = np.sin(2 * np.pi * 730 * t).astype(np.float64)
    R = np.array([np.dot(x[:sr - m], x[m:]) / sr for m in range(19)])
    a, Ep = solve_levinson_durbin(R, 18)
    assert Ep > 0
    assert len(a) == 19


def test_extract_formants_vowel_a():
    # /a/ vowel: F1=730, F2=1090, F3=2440 Hz at 24kHz
    sr = 24000
    num_bins = 512
    freqs = np.linspace(0, sr / 2, num_bins)
    power = np.ones(num_bins, dtype=np.float32) * 1e-6
    for f_center in [730, 1090, 2440]:
        bw = 80
        power += 0.1 * np.exp(-((freqs - f_center) ** 2) / (2 * bw ** 2))
    result = extract_lpc_formants(power, sr, 18)
    assert isinstance(result, LPCResult)
    assert result.f1 is not None
    assert abs(result.f1.hz - 730) < 80     # within 80 Hz
    assert result.f2 is not None
    assert abs(result.f2.hz - 1090) < 100


def test_cepstral_pitch_detects_f0():
    sr = 24000
    num_bins = 512
    target_f0 = 135.0
    freqs = np.linspace(0, sr / 2, num_bins)
    power = np.zeros(num_bins, dtype=np.float32)
    for h in range(1, 12):
        f_harm = h * target_f0
        if f_harm < sr / 2:
            power += (1.0 / h) * np.exp(-((freqs - f_harm) ** 2) / (2 * 30 ** 2))
    result = extract_cepstral_pitch(power, sr)
    assert isinstance(result, PitchResult)
    assert abs(result.f0 - target_f0) < 2.0
    assert result.cpp_db > 5.0


def test_cepstral_pitch_unvoiced_returns_zero():
    sr = 24000
    power = np.random.uniform(1e-8, 1e-6, 512).astype(np.float32)
    result = extract_cepstral_pitch(power, sr)
    assert result.f0 == 0.0
