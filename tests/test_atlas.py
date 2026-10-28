import asyncio
import pytest
from modes.atlas import AtlasMode
from vv_io.reader import ChunkedAudioReader
from vv_io.cache import ChunkCache
from dsp.pipeline import AnalysisParams
from dsp.recovery import RecoveryParams
from dsp.synthesis import SynthesisParams


@pytest.mark.asyncio
async def test_atlas_level1_tile_arrives_first(tmp_wav, tmp_path):
    reader = ChunkedAudioReader(tmp_wav)
    reader.open()
    sent = []

    async def ws_send(msg):
        sent.append(msg)

    mode = AtlasMode(
        reader, ChunkCache(str(tmp_path)),
        AnalysisParams(), RecoveryParams(), SynthesisParams(),
    )
    await mode.on_chunk_requested(0, "high", ws_send)
    tile_msgs = [m for m in sent if m["type"] == "tile_ready"]
    zoom_order = [m["zoom"] for m in tile_msgs]
    assert zoom_order.index(1) < zoom_order.index(3)


@pytest.mark.asyncio
async def test_atlas_all_three_zoom_levels_sent(tmp_wav, tmp_path):
    reader = ChunkedAudioReader(tmp_wav)
    reader.open()
    sent = []

    async def ws_send(msg):
        sent.append(msg)

    mode = AtlasMode(
        reader, ChunkCache(str(tmp_path)),
        AnalysisParams(), RecoveryParams(), SynthesisParams(),
    )
    await mode.on_chunk_requested(0, "high", ws_send)
    tile_zooms = {m["zoom"] for m in sent if m["type"] == "tile_ready"}
    assert 1 in tile_zooms
    assert 3 in tile_zooms


@pytest.mark.asyncio
async def test_atlas_cached_tile_skips_recompute(tmp_wav, tmp_path):
    reader = ChunkedAudioReader(tmp_wav)
    reader.open()
    cache = ChunkCache(str(tmp_path))

    async def ws_send(msg):
        pass

    mode = AtlasMode(reader, cache, AnalysisParams(), RecoveryParams(), SynthesisParams())
    await mode.on_chunk_requested(0, "high", ws_send)

    # Second call: should use cache, not recompute
    sent2 = []

    async def ws_send2(msg):
        sent2.append(msg)

    mode2 = AtlasMode(reader, cache, AnalysisParams(), RecoveryParams(), SynthesisParams())
    await mode2.on_chunk_requested(0, "high", ws_send2)
    computing_msgs = [m for m in sent2 if m["type"] == "tile_computing"]
    assert len(computing_msgs) == 0   # no recompute on cache hit
