import numpy as np
import pytest
from dsp.pipeline import STFTPipeline, AnalysisParams, STFTResult


def test_stft_output_shape(sine_24k):
    samples, sr = sine_24k
    pipe = STFTPipeline(AnalysisParams(), sr)
    result = pipe.compute(samples)
    assert isinstance(result, STFTResult)
    assert result.raw_power.shape[1] == 512          # fft_size=1024 → 512 bins
    assert result.raw_power.dtype == np.float32
    assert len(result.frequencies) == 512
    assert result.frequencies[-1] == pytest.approx(sr / 2, rel=0.01)


def test_noise_floor_shape(sine_24k):
    samples, sr = sine_24k
    result = STFTPipeline(AnalysisParams(), sr).compute(samples)
    assert result.noise_floor.shape == (512,)
    assert np.all(result.noise_floor > 0)


def test_clean_power_never_negative(sine_24k):
    samples, sr = sine_24k
    result = STFTPipeline(AnalysisParams(), sr).compute(samples)
    assert np.all(result.clean_power >= 0)


def test_timestamps_span_signal(sine_24k):
    samples, sr = sine_24k
    result = STFTPipeline(AnalysisParams(), sr).compute(samples)
    assert result.time_stamps[0] >= 0.0
    assert result.time_stamps[-1] <= 3.1
