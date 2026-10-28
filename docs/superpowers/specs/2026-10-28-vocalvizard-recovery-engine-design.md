# VocalVizard — Vocal Recovery Engine Design Spec
**Date:** 2026-10-28
**Version:** v5.1 (Python backend added)
**Status:** Awaiting user approval before implementation planning

---

## 1. Mission Restatement

VocalVizard's primary function is **vocal recovery** — finding and reconstructing human voice patterns that are buried in, at, or below the noise floor of long recordings. The tool serves a human analyst who does final word-recognition manually. The computer's job is to make those words as **visible and audible as possible**.

- Recordings up to 6 hours long
- Voice may be deeply buried (ambient noise dominates)
- Output: cleaned spectrogram + recoverable audio playback
- Analyst manually deciphers words; tool maximizes legibility
- Not a transcription tool — a recovery and visualization instrument

---

## 2. Architecture Overview (v5.1 — Client/Server)

```
┌─────────────────────────────────┐       ┌────────────────────────────────────┐
│   BROWSER (localhost:8765)      │       │   PYTHON BACKEND (FastAPI)         │
│                                 │       │                                    │
│  VocalVizard.html               │       │  server.py                         │
│  ├── Canvas rendering           │◄─────►│  ├── /ws  WebSocket (DSP stream)   │
│  ├── Web Audio playback         │  WS   │  ├── /api REST (file/config/export) │
│  ├── UI controls & event loop   │  +    │  ├── dsp/                          │
│  ├── ROI selection & navigation │ HTTP  │  │   ├── pipeline.py (STFT/LPC)    │
│  └── PNG/JSON/CSV export        │       │  │   ├── recovery.py (Path A/B)    │
│                                 │       │  │   ├── vad.py (voice activity)   │
│  No DSP computation in JS       │       │  │   ├── synthesis.py (Klatt/WORLD)│
│  No file I/O in JS              │       │  │   └── hpss.py (source sep.)     │
│                                 │       │  ├── io/                           │
│                                 │       │  │   ├── reader.py (chunked read)  │
│                                 │       │  │   └── cache.py (file cache)     │
│                                 │       │  └── modes/                        │
│                                 │       │      ├── triage.py                 │
│                                 │       │      ├── atlas.py                  │
│                                 │       │      └── sweep.py                  │
└─────────────────────────────────┘       └────────────────────────────────────┘
```

**Deployment (v5.1):** User runs `python server.py` in terminal. Browser opens automatically to `http://localhost:8765`. Fully offline, no internet required after install. Packaging to executable deferred to later phase.

**What stays in JS/browser:**
- All Canvas 2D rendering (spectrogram, LPC inspector, vowel space, minimap)
- Web Audio API playback of Path A/B PCM buffers returned by server
- All UI controls, event handling, ROI drag-selection
- PNG/JSON/CSV export of display data
- WebSocket client — receives streamed DSP results as Python computes them

**What moves to Python (everything DSP):**
- STFT, noise floor estimation, Wiener filtering, HPSS, HPS F0
- LPC formant extraction (18th-order Levinson-Durbin)
- Cepstral F0 / CPP pitch tracking
- Phoneme classification
- Path A cleaned signal construction
- Path B Klatt/WORLD synthesis
- All file I/O (every audio format via soundfile/audioread)
- Long-file chunked streaming
- Processing mode orchestration (TRIAGE/ATLAS/SWEEP)
- Filesystem cache (replaces IndexedDB entirely)

---

## 3. Python Stack

| Purpose | Library | Notes |
|---------|---------|-------|
| Web server + WebSocket | `fastapi` + `uvicorn` + `websockets` | Async, fast, handles concurrent WS connections |
| FFT (fast) | `pyfftw` | Python bindings for FFTW3; 3–10× faster than NumPy FFT on large arrays |
| FFT (fallback) | `numpy.fft` | Used if pyfftw not installed; same API |
| STFT / spectral | `scipy.signal.stft`, `scipy.signal.istft` | Multi-resolution STFT, OLA reconstruction |
| LPC | `scipy.signal.lfilter` + custom Levinson-Durbin | Port existing JS LD recursion to NumPy; scipy has `lpc` in 1.11+ |
| Wiener filter | `scipy.signal.wiener` | Or custom Wiener from spectral subtraction |
| HPSS | `librosa.effects.hpss` | Median-filter harmonic-percussive separation |
| Audio I/O | `soundfile` + `audioread` | soundfile: WAV/FLAC/OGG/AIFF; audioread: MP3/AAC via ffmpeg |
| Resampling | `soxr` (via `soxr` or `librosa.resample`) | High-quality resampling to 24kHz internal rate |
| VAD | `webrtcvad` + scipy energy heuristic | webrtcvad: Google's battle-tested VAD; energy as fallback |
| Pitch (Path B Speaker Match) | `pyworld` | WORLD vocoder — DIO+StoneMask F0, spectral envelope, aperiodicity; far better than Klatt for speaker-characteristic preservation |
| Pitch (Path B Generic) | Custom Klatt (ported from JS to NumPy) | Direct port of existing KlattVocalTractCascade class |
| Noise reduction extras | `noisereduce` | Optional: stationary + non-stationary noise reduction |
| Parallelism | `multiprocessing.Pool` | For SWEEP mode; one process per CPU core up to 4 |
| Caching | `diskcache` or plain filesystem `shelve` | Stores computed chunk results keyed by (file_hash, chunk_idx, params_hash) |
| Numeric | `numpy` | Core array operations throughout |
| Signal utilities | `scipy.signal` | Filtering, resampling, window functions |

**Install target:** `pip install fastapi uvicorn websockets pyfftw scipy numpy librosa soundfile audioread soxr webrtcvad pyworld noisereduce diskcache`

---

## 4. Communication Protocol

### WebSocket (`ws://localhost:8765/ws`)

All messages are JSON. Binary PCM data uses a separate HTTP endpoint to avoid base64 overhead.

**Client → Server messages:**

```json
{ "type": "open_file",    "path": "/absolute/path/to/file.wav" }
{ "type": "set_mode",     "mode": "triage" | "atlas" | "sweep" }
{ "type": "request_chunk","chunk_idx": 42, "priority": "high" | "normal" }
{ "type": "cancel_chunk", "chunk_idx": 42 }
{ "type": "set_params",   "params": { "alpha": 2.2, "lpc_order": 18, ... } }
{ "type": "request_vad",  "start_s": 0, "end_s": 21600 }
{ "type": "set_recovery", "output": "A"|"B"|"blend", "synthesis": "generic"|"speaker_match",
                           "gaps": "strict"|"bridge", "blend_ratio": 0.5 }
```

**Server → Client messages:**

```json
{ "type": "file_opened",   "duration_s": 21420.5, "sample_rate": 44100, "channels": 2,
                            "file_id": "abc123", "format": "wav" }
{ "type": "vad_progress",  "chunk_idx": 42, "total_chunks": 360,
                            "timeline": [0.0, 0.0, 1.0, 0.8, ...] }
{ "type": "vad_complete",  "timeline": Float32Array_as_base64 }
{ "type": "chunk_ready",   "chunk_idx": 42,
                            "stft_url": "/api/chunk/42/stft",
                            "lpc_url":  "/api/chunk/42/lpc",
                            "path_a_url": "/api/chunk/42/path_a",
                            "path_b_url": "/api/chunk/42/path_b" }
{ "type": "chunk_progress","chunk_idx": 42, "stage": "stft"|"lpc"|"recovery", "pct": 67 }
{ "type": "chunk_error",   "chunk_idx": 42, "error": "..." }
{ "type": "sweep_progress","done": 42, "total": 360, "estimated_remaining_s": 840 }
{ "type": "log",           "level": "info"|"warn"|"forensic"|"pass", "msg": "..." }
```

### HTTP REST (`http://localhost:8765/api`)

```
GET  /api/chunk/{idx}/stft      → binary float32 array (frames × bins)
GET  /api/chunk/{idx}/lpc       → JSON: { formantTrack, pitchTrack, phonemeTrack }
GET  /api/chunk/{idx}/path_a    → binary float32 PCM (cleaned audio)
GET  /api/chunk/{idx}/path_b    → binary float32 PCM (synthetic audio)
GET  /api/chunk/{idx}/minimap   → binary float32 (downsampled amplitude envelope)
GET  /api/status                → JSON: { mode, file_id, progress, cache_size_mb }
POST /api/export/wav            → body: { chunk_idx, path, start_s, end_s } → WAV file
POST /api/export/json           → body: { chunk_idx } → forensic report JSON
POST /api/cache/clear           → clears filesystem cache for current file
```

---

## 5. Three Processing Modes (Mutually Exclusive)

Presented to the user as a single toggle group. Only one active at a time. Switching mode cancels in-progress work and restarts the pipeline.

---

### Mode 1 — TRIAGE
**Fast scan of the whole file first. Deep analysis only where you look.**

**Pass 1 — Scout (auto-runs on file open):**
- Single Python process streams the file in 10s chunks
- Per chunk: RMS amplitude (minimap), spectral flatness, webrtcvad VAD frames
- Sends `vad_progress` WebSocket messages as each chunk completes
- Frontend populates voice event timeline progressively
- Completes in 1–5 minutes for 6 hours

**Pass 2 — Dive (on-demand):**
- Triggered when analyst navigates to a region
- Python loads that 60s window + 5s overlap each side via chunked file reader
- Runs full pipeline: multi-res STFT → noise floor → LPC → pinpoint mask → Path A → Path B
- Sends `chunk_ready` with URLs; frontend fetches STFT data and Path A/B audio
- Result cached to filesystem; revisiting is instant
- Pre-fetches adjacent chunk in a second process

---

### Mode 2 — ATLAS
**Three zoom levels. Always see something. Drill in for precision.**

**Level 1 — Bird's Eye:** VAD timeline only, full file. Fast pass identical to TRIAGE Scout. Waveform amplitude.

**Level 2 — Overview:** Reduced-resolution spectrogram (1 frame per 50ms, scipy.signal.stft with large hop). Broad phoneme ribbon. No LPC. Cached per 60s tile.

**Level 3 — Surgical:** Full pipeline — same as TRIAGE Dive. LPC formants, Path A/B recovery, ROI loop.

**Tile cache:** Each (chunk_idx, zoom_level, params_hash) is a separate cache entry. Frontend requests tiles as user zooms/pans. Server pre-fetches adjacent tiles. Zoom-out shows coarser cached tiles instantly while finer loads.

---

### Mode 3 — SWEEP
**Full parallel processing. Mine the entire file while you work.**

- `multiprocessing.Pool` with 1–4 workers (user-configurable, default: `cpu_count // 2`)
- File split into 60s segments; each worker processes one segment at a time
- Priority queue: viewport segment always moves to front
- Each completed segment sends `chunk_ready` and contributes to sweep progress bar
- Voice event timeline fills in as segments complete
- Analyst can navigate and use any already-processed region immediately
- Estimated completion time shown (`sweep_progress.estimated_remaining_s`)

---

## 6. Vocal Recovery Engine — Dual Output

Every processed chunk produces two parallel PCM buffers:

### Path A — Raw Cleaned Signal (Python pipeline)

```python
# Simplified pipeline per 60s chunk
1. soundfile.read(chunk)                          # any format, auto-resample to 24kHz
2. scipy.signal.stft × 3 resolutions             # 512, 1024, 2048 windows
3. min-statistics noise floor (per-bin quantile) # more robust than 20th-pct for long files
4. Wiener filter (alpha-oversubtraction)          # scipy.signal.wiener or custom
5. librosa.effects.hpss on magnitude spectrogram # strip percussive noise
6. Harmonic Product Spectrum on cleaned stft      # sub-noise-floor F0 detection
7. scipy.signal.istft → cleaned PCM              # OLA reconstruction
```

Output: float32 PCM at 24kHz, same duration as input chunk (with 5s overlaps crossfaded).

### Path B — Synthetic Reconstruction (Python pipeline)

```python
# Per frame where LPC evidence meets threshold
if synthesis_mode == 'generic':
    # Klatt synthesizer (NumPy port of existing JS KlattVocalTractCascade)
    # Uses extracted F1/F2/F3 from LPC, F0 from HPS or cepstrum
    # Neutral source parameters: standard jitter/shimmer values

if synthesis_mode == 'speaker_match':
    # pyworld: DIO+StoneMask F0 extraction on Path A signal
    # pyworld spectral envelope (more accurate than LPC for resynthesis)
    # pyworld aperiodicity (breathiness)
    # pyworld.synthesize() → speaker-characteristic output
    # Speaker stats tracked across voiced frames: mean F0, F0 range, jitter, shimmer

# Gap handling
if gaps == 'bridge':
    # Cubic spline interpolation of F1/F2/F3 contours across silent gaps ≤ 80ms
    # Synthesize bridged frames, amplitude-tapered at gap edges
if gaps == 'strict':
    # Frames without sufficient LPC evidence → zero (silence)
```

Output: float32 PCM at 24kHz.

---

## 7. Server Entry Point

`server.py` — the single file users run:

```python
# python server.py
# → starts FastAPI on localhost:8765
# → opens http://localhost:8765 in default browser automatically
# → serves VocalVizard.html as static file at /
# → all API and WebSocket endpoints live on same port
```

`server.py` also:
- Creates `.vocvizard_cache/` in the working directory on first run
- Checks for required Python packages on startup, prints friendly install instructions if missing
- Logs to terminal (for debugging); errors surfaced via WebSocket `log` messages to frontend
- Graceful shutdown on Ctrl+C: closes open file handles, terminates worker pool

---

## 8. Project File Structure

```
VocalVizard/
├── server.py                    # entry point: `python server.py`
├── requirements.txt             # pip install -r requirements.txt
├── VocalVizard.html             # frontend (served as static file at /)
├── dsp/
│   ├── __init__.py
│   ├── pipeline.py              # STFT, noise floor, Wiener, full analysis pipeline
│   ├── lpc.py                   # Levinson-Durbin, formant extraction, cepstral F0
│   ├── recovery.py              # Path A and Path B construction, OLA reconstruction
│   ├── synthesis.py             # Klatt synthesizer (NumPy), pyworld wrapper
│   ├── hpss.py                  # librosa HPSS wrapper + HPS F0
│   └── vad.py                   # webrtcvad + energy fallback VAD
├── io/
│   ├── __init__.py
│   ├── reader.py                # ChunkedAudioReader: time→byte mapping, soundfile/audioread
│   └── cache.py                 # diskcache wrapper; keyed by (file_hash, chunk_idx, params)
├── modes/
│   ├── __init__.py
│   ├── triage.py                # Scout pass + Dive on-demand logic
│   ├── atlas.py                 # Tile cache, zoom level orchestration
│   └── sweep.py                 # multiprocessing.Pool coordinator, priority queue
├── api/
│   ├── __init__.py
│   ├── routes.py                # FastAPI HTTP route handlers
│   └── ws.py                    # WebSocket connection handler, message dispatch
└── docs/
    └── superpowers/specs/
        └── 2026-10-28-vocalvizard-recovery-engine-design.md
```

---

## 9. New UI Panels / Controls

### Left Sidebar Additions

**Processing Mode selector** (top of sidebar, above Signal Ingest):
```
┌─────────────────────────────────────┐
│  PROCESSING MODE                    │
│  ○ TRIAGE  ○ ATLAS  ● SWEEP        │
└─────────────────────────────────────┘
```
Radio-button style. Switching mode cancels active jobs, shows brief description.

**Vocal Recovery Engine panel** (new section, below LPC controls):
```
┌─────────────────────────────────────┐
│  VOCAL RECOVERY ENGINE              │
│  Output:    ○ Raw  ○ Path A         │
│             ○ Path B  ○ Blend       │
│  Synthesis: ○ Generic  ○ Spk Match  │
│  Gaps:      ○ Strict  ○ Bridge      │
│  Path B Threshold:  [▬▬▬▬▬] 0.28   │
│  A/B Mix (Blend):   [▬▬▬▬▬] 50%    │
└─────────────────────────────────────┘
```

**SWEEP mode panel** (visible only in SWEEP mode):
```
┌─────────────────────────────────────┐
│  SWEEP PROGRESS                     │
│  [▓▓▓▓▓▓▓░░░░░░░░] 42/360 chunks   │
│  Workers: [▬] 4   ETA: ~14 min      │
└─────────────────────────────────────┘
```

### Center Pane Additions
- **Voice Event Timeline** bar: full-width, between phoneme ribbon and spectrogram. Grey/amber/gold/green zones, clickable.
- **Recovery Confidence overlay** toggle in toolbar (toggles green hint layer on spectrogram)
- **Processing progress bar** in bottom log area header when a chunk is computing

### Playback Controls Update
```
[● RAW]  [◑ PATH A]  [◎ PATH B]  [⊕ BLEND]  [▶ Loop ROI]  [▶ Play Full]
```

### Right Sidebar Additions
- **Path A / Path B waveform comparison** mini panel (toggleable) below Vowel Space chart

---

## 10. Phased Implementation Plan (Revised)

| Phase | Scope | Key deliverable |
|-------|-------|-----------------|
| P1 | Python server scaffold | `server.py` running, serves `VocalVizard.html`, WebSocket echo test works |
| P2 | Audio I/O + ChunkedReader | Open any audio file, stream chunks to browser, minimap renders |
| P3 | DSP pipeline in Python | STFT, LPC, noise floor, phoneme mask — parity with v4.0 JS |
| P4 | Path A recovery | Multi-res STFT, HPSS, Wiener, HPS F0 — cleaned audio playable |
| P5 | Path B synthesis | Klatt generic + pyworld speaker-match, strict/bridge gap modes |
| P6 | Mode 1 — TRIAGE | VAD scout pass, on-demand dive, voice event timeline |
| P7 | Mode 2 — ATLAS | Tile cache, three zoom levels, smooth transitions |
| P8 | Mode 3 — SWEEP | multiprocessing pool, priority queue, full-file progress |
| P9 | Frontend UI updates | Mode toggles, recovery controls, playback trio, timeline bar |
| P10 | Bug fixes from TASKS.md A-01 to A-09 | HiDPI, AudioWorklet, DPR, stereo downmix, etc. |

---

## 11. What Is NOT Changing

- Existing JS DSP self-tests (6 tests) remain and still run in-browser as a sanity check for the rendering/synthesis paths
- Spectrogram visual design: dual-gradient yellow/blue + new recovery confidence overlay
- ROI bandpass loop mechanic (now operates on whichever Path is selected)
- Export formats: WAV, PNG, JSON, CSV
- All slider controls and visual parameter tuning — still in frontend, params sent to Python via WebSocket `set_params`

---

*Spec v5.1 self-review: All sections updated for Python backend. No TBDs. IndexedDB removed (replaced by filesystem cache). JS Worker architecture removed (replaced by Python multiprocessing). Communication protocol fully specified. File structure defined. 10 sequential phases, each independently deliverable.*
