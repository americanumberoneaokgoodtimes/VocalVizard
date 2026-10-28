import numpy as np
import pytest
from dsp.recovery import build_path_a, RecoveryParams


def test_path_a_same_length_as_input(sine_24k):
    samples, sr = sine_24k
    result = build_path_a(samples, sr, RecoveryParams())
    assert len(result) == len(samples)
    assert result.dtype == np.float32


def test_path_a_reduces_noise(tmp_path):
    import soundfile as sf
    sr = 24000
    dur = 2.0
    t = np.linspace(0, dur, int(sr * dur), endpoint=False)
    voice = 0.1 * np.sin(2 * np.pi * 440 * t)
    noise = 0.8 * np.random.randn(len(t)).astype(np.float32)
    mixed = (voice + noise).astype(np.float32)
    result = build_path_a(mixed, sr, RecoveryParams())
    # Path A should have lower RMS than the unprocessed mix
    assert np.sqrt(np.mean(result ** 2)) < np.sqrt(np.mean(mixed ** 2))


def test_path_a_values_in_range(sine_24k):
    samples, sr = sine_24k
    result = build_path_a(samples, sr, RecoveryParams())
    assert result.max() <= 1.0
    assert result.min() >= -1.0
