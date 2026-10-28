import numpy as np
import pytest
from dsp.vad import compute_vad_chunk


def test_vad_silence_returns_low_scores(silence_24k):
    samples, sr = silence_24k
    scores = compute_vad_chunk(samples, sr)
    assert scores.dtype == np.float32
    assert np.mean(scores) < 0.2


def test_vad_voiced_sine_returns_high_scores(sine_24k):
    # Not a real voice, but high-energy — VAD should flag it
    samples, sr = sine_24k
    scores = compute_vad_chunk(samples, sr)
    assert np.mean(scores) > 0.3


def test_vad_output_length(sine_24k):
    samples, sr = sine_24k
    scores = compute_vad_chunk(samples, sr)
    frame_dur = 0.030
    expected_frames = int(len(samples) / sr / frame_dur)
    assert abs(len(scores) - expected_frames) <= 2
