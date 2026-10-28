"""HTTP REST endpoints for VocalVizard backend."""
from __future__ import annotations

import struct

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from vv_io.reader import ChunkedAudioReader
from vv_io.cache import ChunkCache

router = APIRouter()

# ---------------------------------------------------------------------------
# App-level state
# ---------------------------------------------------------------------------
_current_reader: ChunkedAudioReader | None = None
_current_cache: ChunkCache | None = None
_current_mode: str | None = None


def set_reader(reader: ChunkedAudioReader) -> None:
    global _current_reader
    _current_reader = reader


def set_cache(cache: ChunkCache) -> None:
    global _current_cache
    _current_cache = cache


def set_mode(mode: str | None) -> None:
    global _current_mode
    _current_mode = mode


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

class OpenFileRequest(BaseModel):
    path: str


@router.post("/api/open")
async def api_open(req: OpenFileRequest) -> JSONResponse:
    reader = ChunkedAudioReader(req.path)
    info = reader.open()
    set_reader(reader)
    return JSONResponse({
        "duration_s": info.duration_s,
        "sample_rate": info.sample_rate,
        "channels": info.channels,
        "format": info.format,
        "file_id": info.file_id,
        "num_chunks": reader.num_chunks,
    })


@router.get("/api/status")
async def api_status() -> JSONResponse:
    cache_mb = _current_cache.size_mb() if _current_cache else 0.0
    return JSONResponse({
        "mode": _current_mode,
        "file_id": (
            _current_reader._info.file_id
            if _current_reader and _current_reader._info
            else None
        ),
        "progress": 0,
        "cache_size_mb": round(cache_mb, 2),
    })


@router.get("/api/chunk/{idx}/stft")
async def api_chunk_stft(idx: int) -> Response:
    if _current_reader is None:
        raise HTTPException(status_code=400, detail="No file open")
    from dsp.pipeline import STFTPipeline, AnalysisParams
    import numpy as np

    chunk = _current_reader.read_chunk(idx)
    pipe = STFTPipeline(AnalysisParams(), _current_reader.target_sr)
    result = pipe.compute(chunk)
    # Serialize: raw_power as flat float32 bytes, prepend shape as 2 int32
    frames, bins = result.raw_power.shape
    header = struct.pack("<ii", frames, bins)
    payload = header + result.raw_power.astype(np.float32).tobytes()
    return Response(content=payload, media_type="application/octet-stream")


@router.get("/api/chunk/{idx}/lpc")
async def api_chunk_lpc(idx: int) -> JSONResponse:
    if _current_reader is None:
        raise HTTPException(status_code=400, detail="No file open")
    from dsp.pipeline import STFTPipeline, AnalysisParams
    from dsp.lpc import analyze_chunk
    import dataclasses

    chunk = _current_reader.read_chunk(idx)
    pipe = STFTPipeline(AnalysisParams(), _current_reader.target_sr)
    result = pipe.compute(chunk)
    lpc_list, pitch_list = analyze_chunk(result, _current_reader.target_sr)

    def serialize_pole(pole):
        if pole is None:
            return None
        return {"hz": pole.hz, "bw": pole.bw, "prom": pole.prom, "db": pole.db}

    frames = []
    for lpc, pitch in zip(lpc_list, pitch_list):
        frames.append({
            "f0": pitch.f0,
            "cpp": pitch.cpp_db,
            "f1": serialize_pole(lpc.f1),
            "f2": serialize_pole(lpc.f2),
            "f3": serialize_pole(lpc.f3),
            "f4": serialize_pole(lpc.f4),
        })
    return JSONResponse({"frames": frames})


@router.get("/api/chunk/{idx}/path_a")
async def api_chunk_path_a(idx: int) -> Response:
    raise HTTPException(status_code=404, detail="Path A not yet available — Task 4")


@router.get("/api/chunk/{idx}/path_b")
async def api_chunk_path_b(idx: int) -> Response:
    raise HTTPException(status_code=404, detail="Path B not yet available — Task 5")
