import asyncio
import pytest
from modes.triage import TriageMode
from vv_io.reader import ChunkedAudioReader
from vv_io.cache import ChunkCache
from dsp.pipeline import AnalysisParams
from dsp.recovery import RecoveryParams
from dsp.synthesis import SynthesisParams


@pytest.mark.asyncio
async def test_scout_sends_vad_progress(tmp_wav, tmp_path):
    reader = ChunkedAudioReader(tmp_wav, chunk_duration_s=60.0)
    reader.open()
    cache = ChunkCache(str(tmp_path))
    sent = []

    async def ws_send(msg):
        sent.append(msg)

    mode = TriageMode(reader, cache, AnalysisParams(), RecoveryParams(), SynthesisParams())
    await mode.on_file_opened(reader, ws_send)
    await asyncio.sleep(0.1)
    types = [m["type"] for m in sent]
    assert "vad_progress" in types or "vad_complete" in types


@pytest.mark.asyncio
async def test_dive_sends_chunk_ready(tmp_wav, tmp_path):
    reader = ChunkedAudioReader(tmp_wav, chunk_duration_s=60.0)
    reader.open()
    cache = ChunkCache(str(tmp_path))
    sent = []

    async def ws_send(msg):
        sent.append(msg)

    mode = TriageMode(reader, cache, AnalysisParams(), RecoveryParams(), SynthesisParams())
    await mode.on_chunk_requested(0, "high", ws_send)
    types = [m["type"] for m in sent]
    assert "chunk_ready" in types


@pytest.mark.asyncio
async def test_cancel_stops_scout(tmp_wav, tmp_path):
    reader = ChunkedAudioReader(tmp_wav, chunk_duration_s=60.0)
    reader.open()
    cache = ChunkCache(str(tmp_path))
    sent = []

    async def ws_send(msg):
        sent.append(msg)

    mode = TriageMode(reader, cache, AnalysisParams(), RecoveryParams(), SynthesisParams())
    await mode.on_file_opened(reader, ws_send)
    mode.cancel_all()
    await asyncio.sleep(0.2)
    count_before = sum(1 for m in sent if m["type"] == "vad_progress")
    await asyncio.sleep(0.2)
    count_after = sum(1 for m in sent if m["type"] == "vad_progress")
    assert count_after == count_before
