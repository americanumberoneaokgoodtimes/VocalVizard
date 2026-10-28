# VocalVizard — Vocal Recovery Engine Design Spec
**Date:** 2026-10-28  
**Version:** v5.0  
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

## 2. Three Processing Modes (Mutually Exclusive)

Presented to the user as a single toggle group. Only one may be active at a time. Selecting a new mode resets and re-runs the active processing pipeline.

---

### Mode 1 — TRIAGE
**Two-pass streaming: cheap fast scan first, surgical detail on demand**

**Pass 1 — Scout (runs immediately on file open, streams entire file):**
- Reads file in 10-second chunks, never loads more than one chunk at a time
- For each chunk: compute RMS amplitude envelope (for minimap), spectral flatness index, and a lightweight Voice Activity Detector (energy ratio in 200–3400 Hz band vs total)
- Output: a full-file voice event timeline — green bars where voice was detected, grey otherwise
- Runs in one background Worker; completes in 1–5 minutes for a 6-hour file
- Minimap populates progressively as Pass 1 runs

**Pass 2 — Dive (on-demand, triggered by analyst navigation):**
- When analyst clicks/navigates to a region: load that 60-second window + 5s buffer each side
- Run full STFT → noise floor → LPC → pinpoint mask → dual-output recovery on that window
- Cache result in IndexedDB keyed by `[fileId, chunkIndex]`
- Pre-fetch adjacent 60s window in background Worker
- Seeking to a cached region: instant. Seeking to new region: 3–10s processing delay shown via progress bar

**Best for:** Long recordings where the analyst doesn't know where voice is. Scout shows them; Dive reveals it.

---

### Mode 2 — ATLAS
**Level-of-detail tile cache: always see something, zoom in for precision**

Three zoom levels, each computed on demand and cached in IndexedDB:

**Level 1 — Bird's Eye (full-file to ~10 min/div):**
- Waveform amplitude envelope only
- Binary voice/silence color band below waveform (from a fast VAD pass)
- No spectrogram at this level — just the map

**Level 2 — Overview (~1 min to ~1 min/div):**
- Full-resolution spectrogram rendered at reduced time resolution (1 frame per ~50ms)
- Phoneme segmentation ribbon (broad categories: voiced / unvoiced / silence)
- No LPC formant tracking at this level

**Level 3 — Surgical (< 30s view):**
- Full STFT + 18th-order LPC + formant overlay + dual-output vocal recovery
- All existing v4.0 features active
- ROI bandpass loop available

**Tile mechanics:**
- Each tile is a fixed 60-second segment × zoom level combination
- Tiles computed in background Worker, cached in IndexedDB
- Adjacent tiles pre-fetched when viewport is within 20% of edge
- Zoom transitions animate smoothly — coarser tile shown until finer one loads
- "Tile ready" indicator in minimap (filled = cached, striped = computing, empty = unprocessed)

**Best for:** Analysts who work spatially — orient on the map, zoom into detail, pan fluidly. Feels like a geographic map of the audio.

---

### Mode 3 — SWEEP
**Full background parallel processing: Workers mine the entire file while you work**

**On file open:**
- Immediately splits the file into 60-second segments
- Dispatches up to 4 parallel Web Workers (configurable), each processing one segment at a time
- Each Worker runs: full STFT → noise floor → LPC → pinpoint mask → dual-output recovery
- Results written to IndexedDB as each segment completes
- A full-file progress bar shows `[segments done] / [total]`
- On a modern CPU: 6-hour file fully processed in ~20–40 minutes

**While processing runs:**
- Analyst can navigate freely. Any region already processed shows full detail immediately
- Unprocessed regions show "Computing..." placeholder
- Voice recovery results appear in the timeline as each segment finishes

**Priority queue:**
- Viewport region always jumps to front of queue
- Segments flagged by quick VAD pre-scan are prioritized over silent regions

**Best for:** Power users who want the entire file fully analyzed. Set it running, come back after a coffee, explore the full result.

---

## 3. Vocal Recovery Engine — Dual Output

Every processed region produces two parallel output tracks:

### Path A — Raw Cleaned Signal
Classical DSP enhancement of the actual recorded audio:
1. Multi-resolution STFT (512 + 1024 + 2048 windows fused) for transient + tonal balance
2. Minimum statistics noise floor tracker (more accurate than current percentile method for long recordings)
3. Aggressive Wiener filter (alpha-oversubtraction, beta-floor)
4. HPSS (Harmonic-Percussive Source Separation via median filter on spectrogram magnitude) — strips percussive noise, retains harmonic/voiced content
5. Harmonic Product Spectrum (HPS) for sub-noise-floor F0 detection — finds pitch even when individual harmonics are invisible
6. Reconstructed output is the cleaned/filtered waveform — real audio, just denoised

**What it sounds like:** The actual recording, with noise aggressively removed. May still sound noisy or partial. Words may be recognizable or not depending on SNR.

### Path B — Synthetic Reconstruction
Model-driven reconstruction from vocal tract evidence:
1. LPC analysis runs on the cleaned Path A signal (better input → better model)
2. For each frame where LPC has sufficient formant evidence (F1+F2 detected with prom > threshold), drive the Klatt synthesizer with extracted parameters
3. Frames with insufficient evidence → silence (no fabrication)
4. Adjacent evidence frames interpolate smoothly (no abrupt cuts)

**Two synthesis sub-modes (user toggle, applies to Path B only):**

- **Generic Voice:** Neutral Klatt voice with standard source parameters. F0 defaults to extracted pitch or 120 Hz male / 200 Hz female estimate if undetected. Sounds like a clean neutral speaker saying approximately what was said. Best for maximum intelligibility.

- **Speaker Match:** Preserves extracted speaker characteristics — F0 mean and contour, jitter (frame-to-frame F0 variation), shimmer (amplitude modulation), CPP-derived breathiness estimate, and F0 range classification (bass/baritone/tenor/alto/soprano). Sounds like the original speaker, synthesized. Better for speaker identification by ear.

**Gap handling (user toggle, applies to Path B only):**

- **Strict:** Silence on frames with insufficient LPC evidence. Never interpolates. Most honest — gaps mean "no data."

- **Bridge:** Interpolates formant trajectories across gaps of up to 80ms using cubic spline. Fills brief unrecoverable segments with plausible continuation. Useful when words are mostly there but momentary noise bursts punch holes.

---

## 4. Spectrogram — New Visual Layers

The spectrogram gains a third display layer on top of the existing dual-gradient (yellow voice / blue ambient):

**Recovery Confidence Layer** (overlay, toggleable):
- Dim green tint at TF bins where Path B synthesis has evidence (LPC found formants, even weakly)
- Bright gold at bins where Path A cleaning revealed recoverable signal
- Shows the analyst exactly where the computer found voice evidence, even if the spectrogram itself still looks noisy

**Voice Event Timeline** (new panel below phoneme ribbon):
- Full-file horizontal bar showing:
  - Grey: unprocessed or silence
  - Amber: voice detected (VAD-level confidence)
  - Gold: voice confirmed with LPC formant evidence
  - Green: Path B synthesis succeeded (words likely recoverable)
- Clickable: clicking any segment navigates to it and triggers deep analysis

---

## 5. Playback — Three-Way Audio Toggle

Replaces the current "Play Full" / "Loop ROI" buttons with a more structured playback system:

```
[● RAW]  [◑ PATH A]  [◎ PATH B]  [BLEND ▶]
```

- **RAW:** Unprocessed original audio. Reference for comparison.
- **PATH A:** Cleaned raw signal (Wiener + HPSS denoised). Real audio, maximally denoised.
- **PATH B:** Klatt synthetic reconstruction. Clean, possibly more intelligible.
- **BLEND:** Mix of Path A and Path B. User adjustable A/B mix ratio slider.

The ROI bandpass loop works on whichever output is currently selected.

---

## 6. Large File Architecture

### File Access
- Use the **File System Access API** (`showOpenFilePicker()`) instead of `<input type="file">` for large files
- Keep a `FileSystemFileHandle` reference; read chunks on demand via `file.slice(byteOffset, byteEnd).arrayBuffer()`
- Maintain a `ChunkReader` class that maps time offsets → byte offsets for any audio format
- For formats requiring container decoding (MP3, FLAC, OGG): decode in Workers, cache raw PCM to IndexedDB
- Fallback to `<input type="file">` for files under 200MB (current path still works)

### Memory Model
- Maximum simultaneous PCM in main-thread RAM: **2 × 60-second windows** (current + pre-fetch) = ~5.5MB at 24kHz float32
- Maximum PCM in Worker RAM: **4 × 60-second windows** (one per Worker in Mode 3) = ~11MB total
- All computed matrices (STFT power, LPC envelopes, masks): stored in **IndexedDB**, never all in RAM simultaneously
- Minimap waveform: **downsampled to 1 sample per 50ms** = 432,000 points for 6h = 1.7MB — always in RAM

### IndexedDB Schema
```
stores:
  audio_chunks:     { fileId, chunkIdx, format } → Float32Array PCM
  stft_chunks:      { fileId, chunkIdx, params } → rawPower matrix (compressed)
  lpc_chunks:       { fileId, chunkIdx, params } → formantTrack, pitchTrack, phonemeTrack
  recovery_chunks:  { fileId, chunkIdx, mode }   → pathA buffer, pathB buffer
  vad_timeline:     { fileId }                   → Float32Array (one value per 50ms)
  minimap_data:     { fileId }                   → Float32Array amplitude envelope
```

### Worker Architecture
```
MainThread
  ├── UIWorker (rendering, event handling — stays responsive)
  ├── CoordWorker (chunk scheduler, IndexedDB manager, priority queue)
  └── DSPWorkers × 1–4 (STFT + LPC + Recovery — configurable count)
         Each DSPWorker processes one 60s segment at a time
         Reports progress back to CoordWorker via MessagePort
         Receives cancel signal for pre-emption
```

---

## 7. New UI Panels / Controls

### Left Sidebar Additions
**Processing Mode selector** (top of sidebar, above Signal Ingest):
```
┌─────────────────────────────────────┐
│  PROCESSING MODE                    │
│  ○ TRIAGE  ○ ATLAS  ● SWEEP        │
└─────────────────────────────────────┘
```
Radio-button style toggle. Switching mode shows a brief description of the selected mode.

**Recovery Engine controls** (new section, below LPC controls):
```
┌─────────────────────────────────────┐
│  VOCAL RECOVERY ENGINE              │
│  Output: ○ Path A  ○ Path B  ○ Mix │
│  Synthesis: ○ Generic  ○ Spk Match  │
│  Gaps: ○ Strict  ○ Bridge           │
│  Path B Confidence Threshold: [▬]   │
│  A/B Mix Ratio (if Mix): [▬]        │
└─────────────────────────────────────┘
```

### Center Pane Additions
- **Voice Event Timeline** bar: full-width, between phoneme ribbon and spectrogram
- **Recovery Confidence overlay** toggle in toolbar
- **Processing progress bar** replaces the bottom log area header when processing

### Right Sidebar Additions
- **Path A / Path B waveform comparison** panel (small, toggleable) showing cleaned vs synthetic waveform for the inspected frame region

---

## 8. Phased Implementation Plan (High Level)

| Phase | Scope |
|-------|-------|
| P1 | Large file infrastructure: File System Access API, ChunkReader, IndexedDB schema, Worker scaffold |
| P2 | Mode 1 — TRIAGE: VAD fast pass, on-demand dive, minimap progress |
| P3 | Dual-output recovery engine: Path A (multi-res STFT + HPSS + HPS), Path B (Klatt from LPC) |
| P4 | Path B sub-modes: Generic vs Speaker Match, Strict vs Bridge gaps |
| P5 | Mode 2 — ATLAS: tile cache, zoom levels, smooth transitions |
| P6 | Mode 3 — SWEEP: Worker pool, priority queue, whole-file processing |
| P7 | Voice Event Timeline, Recovery Confidence overlay, playback three-way toggle |
| P8 | Fix all Section A bugs from TASKS.md (HiDPI, AudioWorklet, etc.) |

---

## 9. What Is NOT Changing

- Core DSP algorithms: Blackman-Harris STFT, Levinson-Durbin LPC, cepstral F0 tracking, Klatt IIR resonators — these are correct and stay
- Single-file HTML architecture: still one `.html` file (build step bundles modules)
- No external API calls, no server, fully offline
- Export formats: WAV, PNG, JSON, CSV (CSV added per TASKS.md C-10)
- The 6 automated DSP self-tests — extended to cover new recovery engine

---

*Spec self-review: No TBDs. All sections internally consistent. Scope is large but decomposed into 8 sequential phases, each independently deliverable. Phase 1 is prerequisite for all others.*
