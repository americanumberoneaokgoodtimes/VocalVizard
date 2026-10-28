import numpy as np
import pytest
from dsp.hpss import apply_hpss, compute_hps_f0


def test_hpss_output_shape():
    mag = np.abs(np.random.randn(100, 512)).astype(np.float32)
    h, p = apply_hpss(mag)
    assert h.shape == mag.shape
    assert p.shape == mag.shape


def test_hpss_harmonic_plus_percussive_approx_input():
    mag = np.abs(np.random.randn(100, 512)).astype(np.float32)
    h, p = apply_hpss(mag, margin=1.0)
    reconstructed = h + p
    np.testing.assert_allclose(reconstructed, mag, rtol=0.01)


def test_hps_detects_known_f0():
    sr = 24000
    num_bins = 512
    target = 120.0
    freqs = np.linspace(0, sr / 2, num_bins)
    power = np.zeros(num_bins, dtype=np.float32)
    for h_n in range(1, 6):
        power += np.exp(-((freqs - h_n * target) ** 2) / (2 * 20 ** 2))
    f0 = compute_hps_f0(power, sr)
    assert abs(f0 - target) < 5.0


def test_hps_returns_zero_for_noise():
    power = np.random.uniform(1e-9, 1e-7, 512).astype(np.float32)
    f0 = compute_hps_f0(power, 24000)
    assert f0 == 0.0
