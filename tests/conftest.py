import numpy as np
import pytest


@pytest.fixture
def sine_24k():
    """440 Hz sine, 3 seconds, 24000 Hz, float32 [-1, 1]"""
    sr = 24000
    t = np.linspace(0, 3.0, 3 * sr, endpoint=False)
    return (np.sin(2 * np.pi * 440 * t)).astype(np.float32), sr


@pytest.fixture
def silence_24k():
    sr = 24000
    return np.zeros(sr * 3, dtype=np.float32), sr


@pytest.fixture
def tmp_wav(tmp_path, sine_24k):
    import soundfile as sf
    samples, sr = sine_24k
    p = tmp_path / "test.wav"
    sf.write(str(p), samples, sr)
    return str(p)
