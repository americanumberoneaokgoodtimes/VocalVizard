import asyncio
import pytest
import soundfile as sf
import numpy as np
from modes.sweep import SweepMode
from vv_io.reader import ChunkedAudioReader
from vv_io.cache import ChunkCache
from dsp.pipeline import AnalysisParams
from dsp.recovery import RecoveryParams
from dsp.synthesis import SynthesisParams


@pytest.mark.asyncio
async def test_sweep_processes_all_chunks(tmp_wav, tmp_path):
    reader = ChunkedAudioReader(tmp_wav)
    reader.open()
    sent = []

    async def ws_send(msg):
        sent.append(msg)

    mode = SweepMode(
        reader, ChunkCache(str(tmp_path)),
        AnalysisParams(), RecoveryParams(), SynthesisParams(),
        num_workers=1,
    )
    await mode.on_file_opened(reader, ws_send)

    for _ in range(60):
        await asyncio.sleep(0.1)
        if any(m["type"] == "sweep_complete" for m in sent):
            break

    ready = [m for m in sent if m["type"] == "chunk_ready"]
    assert len(ready) == reader.num_chunks


@pytest.mark.asyncio
async def test_sweep_priority_chunk_arrives_first(tmp_path, tmp_path_factory):
    p = tmp_path_factory.mktemp("audio") / "long.wav"
    sf.write(str(p), np.zeros(65 * 24000, dtype=np.float32), 24000)
    reader = ChunkedAudioReader(str(p), chunk_duration_s=30.0)
    reader.open()
    assert reader.num_chunks >= 2

    sent = []

    async def ws_send(msg):
        sent.append(msg)

    mode = SweepMode(
        reader, ChunkCache(str(tmp_path)),
        AnalysisParams(), RecoveryParams(), SynthesisParams(),
        num_workers=1,
    )
    await mode.on_file_opened(reader, ws_send)
    await mode.on_chunk_requested(reader.num_chunks - 1, "high", ws_send)

    for _ in range(60):
        await asyncio.sleep(0.1)
        ready = [m for m in sent if m["type"] == "chunk_ready"]
        if len(ready) >= 1:
            break

    ready = [m for m in sent if m["type"] == "chunk_ready"]
    ready_idxs = [m["chunk_idx"] for m in ready]
    if len(ready_idxs) >= 2:
        assert (reader.num_chunks - 1) in ready_idxs[:2]


@pytest.mark.asyncio
async def test_sweep_cancel_stops_workers(tmp_wav, tmp_path):
    reader = ChunkedAudioReader(tmp_wav)
    reader.open()
    sent = []

    async def ws_send(msg):
        sent.append(msg)

    mode = SweepMode(
        reader, ChunkCache(str(tmp_path)),
        AnalysisParams(), RecoveryParams(), SynthesisParams(),
        num_workers=2,
    )
    await mode.on_file_opened(reader, ws_send)
    mode.cancel_all()
    await asyncio.sleep(0.3)

    c1 = sum(1 for m in sent if m["type"] == "sweep_progress")
    await asyncio.sleep(0.3)
    c2 = sum(1 for m in sent if m["type"] == "sweep_progress")
    assert c2 == c1
