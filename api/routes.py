"""HTTP REST endpoints for VocalVizard backend."""
from __future__ import annotations

import struct

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from vv_io.reader import ChunkedAudioReader
from vv_io.cache import ChunkCache
from dsp.synthesis import SynthesisParams

router = APIRouter()

# ---------------------------------------------------------------------------
# App-level state
# ---------------------------------------------------------------------------
_current_reader: ChunkedAudioReader | None = None
_current_cache: ChunkCache | None = None
_current_mode: str | None = None
_synthesis_params: SynthesisParams = SynthesisParams()


def set_reader(reader: ChunkedAudioReader) -> None:
    global _current_reader
    _current_reader = reader


def set_cache(cache: ChunkCache) -> None:
    global _current_cache
    _current_cache = cache


def set_mode(mode: str | None) -> None:
    global _current_mode
    _current_mode = mode


def set_synthesis_params(params: SynthesisParams) -> None:
    global _synthesis_params
    _synthesis_params = params


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
    import numpy as np
    from dsp.pipeline import STFTPipeline, AnalysisParams

    chunk = _current_reader.read_chunk(idx)
    pipe = STFTPipeline(AnalysisParams(), _current_reader.target_sr)
    result = pipe.compute(chunk)
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

    chunk = _current_reader.read_chunk(idx)
    pipe = STFTPipeline(AnalysisParams(), _current_reader.target_sr)
    result = pipe.compute(chunk)
    lpc_list, pitch_list = analyze_chunk(result, _current_reader.target_sr)

    def serialize_pole(pole):
        if pole is None:
            return None
        return {"hz": pole.hz, "bw": pole.bw, "prom": pole.prom, "db": pole.db}

    frames_out = []
    for lpc, pitch in zip(lpc_list, pitch_list):
        frames_out.append({
            "f0": pitch.f0,
            "cpp": pitch.cpp_db,
            "f1": serialize_pole(lpc.f1),
            "f2": serialize_pole(lpc.f2),
            "f3": serialize_pole(lpc.f3),
            "f4": serialize_pole(lpc.f4),
        })
    return JSONResponse({"frames": frames_out})


@router.get("/api/chunk/{idx}/path_a")
async def api_chunk_path_a(idx: int) -> Response:
    if _current_reader is None:
        raise HTTPException(status_code=400, detail="No file open")
    import numpy as np
    from dsp.recovery import build_path_a, RecoveryParams

    chunk = _current_reader.read_chunk_overlap(idx, overlap_s=5.0)
    result = build_path_a(chunk, _current_reader.target_sr, RecoveryParams())
    chunk_samples = int(_current_reader.chunk_duration_s * _current_reader.target_sr)
    overlap_samples = int(5.0 * _current_reader.target_sr)
    start = overlap_samples if idx > 0 else 0
    trimmed = result[start: start + chunk_samples]
    return Response(
        content=trimmed.astype(np.float32).tobytes(),
        media_type="application/octet-stream",
    )


@router.get("/api/chunk/{idx}/path_b")
async def api_chunk_path_b(idx: int) -> Response:
    if _current_reader is None:
        raise HTTPException(status_code=400, detail="No file open")
    import numpy as np
    from dsp.pipeline import STFTPipeline, AnalysisParams
    from dsp.lpc import analyze_chunk
    from dsp.recovery import build_path_a, build_path_b, RecoveryParams

    sr = _current_reader.target_sr
    chunk = _current_reader.read_chunk_overlap(idx, overlap_s=5.0)
    path_a = build_path_a(chunk, sr, RecoveryParams())

    pipe = STFTPipeline(AnalysisParams(), sr)
    stft = pipe.compute(chunk)
    lpc_list, pitch_list = analyze_chunk(stft, sr)

    result = build_path_b(lpc_list, pitch_list, path_a, sr, _synthesis_params)

    chunk_samples = int(_current_reader.chunk_duration_s * sr)
    overlap_samples = int(5.0 * sr)
    start = overlap_samples if idx > 0 else 0
    trimmed = result[start: start + chunk_samples]
    return Response(
        content=trimmed.astype(np.float32).tobytes(),
        media_type="application/octet-stream",
    )
