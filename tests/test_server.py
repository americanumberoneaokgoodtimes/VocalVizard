import io
import pytest
import soundfile as sf
import numpy as np
from httpx import AsyncClient, ASGITransport
from server import app


@pytest.mark.asyncio
async def test_root_serves_html():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


@pytest.mark.asyncio
async def test_status_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert "mode" in body
    assert "file_id" in body


@pytest.mark.asyncio
async def test_upload_wav_returns_file_info(tmp_path):
    """POST /api/upload with a WAV file should return duration/sample_rate/num_chunks."""
    wav_path = tmp_path / "test.wav"
    samples = np.zeros(24000 * 3, dtype=np.float32)  # 3 seconds
    sf.write(str(wav_path), samples, 24000)
    wav_bytes = wav_path.read_bytes()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/upload",
            files={"file": ("test.wav", io.BytesIO(wav_bytes), "audio/wav")},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["duration_s"] == pytest.approx(3.0, abs=0.1)
    assert body["num_chunks"] == 1
    assert "file_id" in body


@pytest.mark.asyncio
async def test_websocket_echo():
    from fastapi.testclient import TestClient
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "ping"})
        msg = ws.receive_json()
    assert msg["type"] == "pong"
