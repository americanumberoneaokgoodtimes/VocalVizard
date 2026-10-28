import numpy as np
import pytest
from dsp.synthesis import KlattSynthesizer, WorldSynthesizer, SynthesisParams
from dsp.recovery import build_path_b
from dsp.lpc import LPCResult, PitchResult, FormantPole


def make_lpc_result(f1=730.0, f2=1090.0, f3=2440.0):
    return LPCResult(
        lpc_db=np.zeros(512, dtype=np.float32),
        f1=FormantPole(hz=f1, bw=80, prom=4.0, db=-10.0),
        f2=FormantPole(hz=f2, bw=100, prom=3.5, db=-12.0),
        f3=FormantPole(hz=f3, bw=120, prom=2.5, db=-15.0),
        f4=None,
    )


def test_klatt_frame_returns_correct_length():
    synth = KlattSynthesizer(24000)
    frame = synth.synthesize_frame(125.0, 730, 80, 1090, 100, 2440, 120, 256)
    assert len(frame) == 256
    assert frame.dtype == np.float32


def test_klatt_frame_voiced_has_energy():
    synth = KlattSynthesizer(24000)
    frame = synth.synthesize_frame(125.0, 730, 80, 1090, 100, 2440, 120, 512)
    assert np.sqrt(np.mean(frame ** 2)) > 1e-4


def test_build_path_b_correct_length():
    sr = 24000
    frames = 50
    lpc_list = [make_lpc_result() for _ in range(frames)]
    pitch_list = [PitchResult(f0=125.0, cpp_db=9.0) for _ in range(frames)]
    path_a = np.zeros(sr * 3, dtype=np.float32)
    result = build_path_b(lpc_list, pitch_list, path_a, sr, SynthesisParams())
    assert len(result) == len(path_a)
    assert result.dtype == np.float32


def test_build_path_b_all_noise_returns_silence():
    sr = 24000
    frames = 50
    lpc_list = [
        LPCResult(
            lpc_db=np.zeros(512, dtype=np.float32),
            f1=None, f2=None, f3=None, f4=None,
        )
        for _ in range(frames)
    ]
    pitch_list = [PitchResult(f0=0.0, cpp_db=0.0) for _ in range(frames)]
    path_a = np.zeros(sr * 3, dtype=np.float32)
    result = build_path_b(
        lpc_list, pitch_list, path_a, sr,
        SynthesisParams(mode="generic", gaps="strict"),
    )
    assert np.allclose(result, 0.0)   # strict + no evidence → all silence


def test_build_path_b_speaker_match_returns_audio(sine_24k):
    samples, sr = sine_24k
    lpc_list = [make_lpc_result() for _ in range(100)]
    pitch_list = [PitchResult(f0=125.0, cpp_db=9.0) for _ in range(100)]
    result = build_path_b(
        lpc_list, pitch_list, samples, sr,
        SynthesisParams(mode="speaker_match", gaps="strict"),
    )
    assert np.sqrt(np.mean(result ** 2)) > 1e-5
