"""VocalVizard v5 — FastAPI server entry point."""
from __future__ import annotations

import os

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

from api.ws import manager

app = FastAPI(title="VocalVizard", version="5.0.0")

# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------

@app.get("/")
async def serve_frontend() -> FileResponse:
    return FileResponse("VocalVizard.html", media_type="text/html")


@app.get("/api/status")
async def api_status() -> JSONResponse:
    return JSONResponse({
        "mode": None,
        "file_id": None,
        "progress": 0,
        "cache_size_mb": 0,
    })


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await manager.connect(ws)
    try:
        while True:
            msg = await ws.receive_json()
            await manager.handle_message(ws, msg)
    except WebSocketDisconnect:
        await manager.disconnect(ws)
    except Exception as exc:
        await manager.disconnect(ws)
        raise


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import webbrowser
    import uvicorn

    port = int(os.getenv("PORT", "8765"))
    webbrowser.open(f"http://localhost:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port)
