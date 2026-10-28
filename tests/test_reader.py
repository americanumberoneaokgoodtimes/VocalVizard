import numpy as np
import pytest
from vv_io.reader import ChunkedAudioReader, AudioInfo


def test_open_returns_audio_info(tmp_wav):
    r = ChunkedAudioReader(tmp_wav)
    info = r.open()
    assert isinstance(info, AudioInfo)
    assert info.duration_s == pytest.approx(3.0, abs=0.1)
    assert info.sample_rate == 24000
    assert len(info.file_id) == 32          # md5 hex


def test_read_chunk_returns_float32(tmp_wav):
    r = ChunkedAudioReader(tmp_wav)
    r.open()
    chunk = r.read_chunk(0)
    assert chunk.dtype == np.float32
    assert chunk.max() <= 1.0
    assert chunk.min() >= -1.0


def test_read_chunk_resamples_to_24k(tmp_path):
    import soundfile as sf
    # Write a 44100 Hz file
    samples = np.sin(2 * np.pi * 440 * np.linspace(0, 3, 3 * 44100)).astype(np.float32)
    p = tmp_path / "44k.wav"
    sf.write(str(p), samples, 44100)
    r = ChunkedAudioReader(str(p), target_sr=24000)
    r.open()
    chunk = r.read_chunk(0)
    expected_len = 3 * 24000
    assert abs(len(chunk) - expected_len) < 100   # within 100 samples of expected


def test_short_final_chunk_does_not_crash(tmp_path):
    # File is 65 seconds — produces one 60s chunk and one 5s chunk
    import soundfile as sf
    sr = 24000
    samples = np.zeros(65 * sr, dtype=np.float32)
    p = tmp_path / "65s.wav"
    sf.write(str(p), samples, sr)
    r = ChunkedAudioReader(str(p), chunk_duration_s=60.0)
    r.open()
    assert r.num_chunks == 2
    last = r.read_chunk(1)
    assert len(last) > 0        # does not crash, returns partial chunk


def test_read_chunk_overlap_adds_padding(tmp_wav):
    r = ChunkedAudioReader(tmp_wav, chunk_duration_s=60.0)
    r.open()
    base = r.read_chunk(0)
    overlapped = r.read_chunk_overlap(0, overlap_s=1.0)
    assert len(overlapped) >= len(base)
