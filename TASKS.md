# VocalVizard — Comprehensive Development Task Tracker
**Audit Date:** 2026-10-28 | **Version Audited:** v4.0 | **File:** `VocalVizard.html`

---

## LEGEND
- `[BUG]` — Confirmed defect affecting correctness or visual fidelity
- `[INCOMPLETE]` — Feature wired up in UI/state but not fully implemented
- `[MISSING]` — Feature absent but required for field-ready operation
- `[RESEARCH]` — Web research / reference material gathering tasks
- `[PERF]` — Performance / scalability improvement
- Priority: 🔴 Critical | 🟠 High | 🟡 Medium | 🟢 Low

---

## SECTION A — CONFIRMED BUGS

### A-01 🔴 [BUG] Main Spectrogram Canvas Missing `devicePixelRatio` Scaling
- **Location:** `renderMainSpectrogram()` ~line 1843–1923
- **Problem:** `canvas.width = Math.floor(rect.width)` — no DPR multiplication. All other canvases (minimap, overlay, phoneme ribbon, axes, LPC slice, vowel space) correctly scale by `window.devicePixelRatio`. The main spectrogram renders at 1× on Retina/HiDPI displays, producing blurry visuals — the primary forensic display.
- **Fix:** Add `const dpr = window.devicePixelRatio || 1;`, scale canvas dimensions by dpr, apply `ctx.scale(dpr, dpr)`, and adjust pixel loop accordingly (render at native resolution, map each CSS pixel to the corresponding dpr-scaled canvas pixels).

### A-02 🔴 [BUG] `createScriptProcessor` Deprecated in Live Mic Mode
- **Location:** `btnLiveMic` handler ~line 2881–2907
- **Problem:** `state.audioCtx.createScriptProcessor(2048, 1, 1)` is a deprecated Web Audio API method. Chrome 107+ emits deprecation warnings; it will be removed in a future release. The `onaudioprocess` event is not guaranteed to fire reliably in modern browsers.
- **Fix:** Replace with `AudioWorklet` + `AudioWorkletProcessor`. Create a dedicated worklet script (inline via Blob URL or data URI to keep the single-file architecture), register it with `audioCtx.audioWorklet.addModule(...)`, then use `AudioWorkletNode` with a `MessagePort` to pipe PCM chunks back to the main thread for analysis.

### A-03 🔴 [BUG] AudioContext Sample Rate Mismatch Between Sessions
- **Location:** `ensureAudioContext()` ~line 2434–2441, `btnLiveMic` handler
- **Problem:** The `AudioContext` is created once using `{ sampleRate: state.sampleRate }`. If a live mic session is started first (browser chooses its native rate, e.g. 48000 Hz), then a 24 kHz audio file is loaded, `state.sampleRate` changes to 24000 but the existing AudioContext remains at 48000 Hz. All subsequent playback will play at the wrong pitch/speed.
- **Fix:** In `loadAudioSamplesIntoEngine()`, if `state.audioCtx` exists and `state.audioCtx.sampleRate !== sr`, close and nullify the context before creating a new one. Guard this against active playback.

### A-04 🟠 [BUG] Stereo / Multi-Channel Audio: Silent Channel Discard
- **Location:** `fileInputAudio` change handler ~line 2805
- **Problem:** `decoded.getChannelData(0)` takes only channel 0. For stereo or surround recordings, all other channels are silently discarded with no user notification. Forensic recordings may have important evidence on channel 1 (e.g., a recording device's second track, a conference room recording with separate near/far mics).
- **Fix:** Check `decoded.numberOfChannels > 1`, offer the user a channel selection dropdown or perform proper mono downmix: `(ch0 + ch1) / 2` (or per-channel loudness-weighted sum). Log a warning if multi-channel is detected.

### A-05 🟠 [BUG] STFT/LPC Analysis Blocks Main Thread (UI Freeze)
- **Location:** `analyzeFullAudioBuffer()` ~line 1340–1406, `recomputeLPCAndPinpointMask()` ~line 1408–1629
- **Problem:** Both passes are synchronous. On large audio files (> ~10 seconds at 24 kHz), the browser tab freezes for several seconds — unacceptable for field use. Additionally, `colBuf.sort()` at line 1395 on a `Float32Array` sorts correctly but still executes synchronously.
- **Fix:** Offload `analyzeFullAudioBuffer()` and `recomputeLPCAndPinpointMask()` to a `Web Worker`. The worker serializes the computed arrays and `postMessage`s results back. Show a progress overlay with per-pass status during processing.

### A-06 🟡 [BUG] F4 Formant Pole Tracked But Not Rendered in Spectrogram Overlay
- **Location:** `renderOverlaysAndFormants()` ~line 1945–1991
- **Problem:** `state.formantTrack[f].f4` is populated by the LPC engine and displayed in the right-panel table, but the overlay rendering only plots F0 (emerald), F1 (yellow), F2 (gold), F3 (cyan). F4 (purple `#a855f7`) is marked in the slice inspector (`markPole` function) but absent from the 2D spectrogram overlay dots.
- **Fix:** Add `drawPoleDot(fm.f4, '#a855f7')` after F3 in the overlay render loop. Conditionally show only when `fm.f4 && fm.f4.hz <= maxHz * 0.9`.

### A-07 🟡 [BUG] "Drag: Time Zoom" Mode Broken — Sets ROI Instead of Zooming
- **Location:** `window.addEventListener('mouseup', ...)` ~line 3184, drag mode check ~line 3208
- **Problem:** When `state.dragMode === 'zoom'`, the mouseup handler calls `updateRoiBoxPosition()` and `updateRoiTelemetry()` after the else branch, but the `roi.t0/t1` have already been updated by the `mousedown` handler which always writes to `state.roi` regardless of drag mode. The zoom branch at line 3208 checks `state.dragMode === 'zoom'` and zooms correctly, but the preceding code still updates the ROI box. The behavior is inconsistent: ROI gets modified even in zoom mode.
- **Fix:** In `mousedown`, only update `state.roi` if `state.dragMode === 'roi'`. In zoom mode, use separate `dragState.zoomT0/T1` variables. On mouseup in zoom mode, set `state.viewT0/T1` and call `renderAllCanvases()` without touching the ROI.

### A-08 🟡 [BUG] Live Mic Ring Buffer: Data Race Between Audio Callback and Analysis
- **Location:** `proc.onaudioprocess` ~line 2886–2899
- **Problem:** `state.audioSamples = ringBuf` assigns the shared `Float32Array` reference. On every 4th chunk (`chunkCounter % 4 === 0`), `analyzeFullAudioBuffer()` runs synchronously while the `onaudioprocess` callback may be mutating `ringBuf` in parallel. This is a data race — the analysis may read partially-updated ring buffer data.
- **Fix:** Pass a copy of `ringBuf.slice()` to the analysis instead of the live reference: `state.audioSamples = ringBuf.slice()`. The copy is captured at the moment of analysis invocation.

### A-09 🟢 [BUG] ROI Bandpass: Nyquist Bin Conjugate Symmetry
- **Location:** `buildIsolatedRoiBandpassBuffer()` ~line 2396–2402
- **Problem:** The loop `for (let k = 0; k <= (N >> 1); k++)` sets `im[N - k] = -im[k]` for conjugate symmetry. At `k = N/2` (Nyquist), `N - k = N/2`, so `im[N/2] = -im[N/2]`. If `im[N/2]` is nonzero before IFFT, this sets it to its own negation (not zero). The Nyquist bin should be purely real. While in practice `im[N/2]` is typically near-zero after an FFT of a real signal, explicitly setting it to 0 is more correct.
- **Fix:** After the gain loop, add `im[N >> 1] = 0.0; re[0] = gain_k0 > 0 ? re[0] : 0.0;` to ensure DC and Nyquist bins are purely real.

---

## SECTION B — INCOMPLETE INTEGRATIONS

### B-01 🔴 [INCOMPLETE] RF Audio Analysis: Title Promises, Code Delivers Nothing
- **Location:** App title, filename (`acoustic_speech_rf_audio_spectrogram_analyzer`)
- **Problem:** The application title advertises "RF audio spectrogram analysis" but the entire codebase is focused exclusively on acoustic speech (20 Hz–12 kHz, vocal tract LPC, phoneme classification). There is zero support for RF signal ingestion (SDR, baseband IQ, AM/FM/SSB demodulation, DTMF/signaling tone detection, or wide-band spectral analysis beyond 12 kHz).
- **Fix (Minimum viable):** Either rename the app to remove "RF" from the title, OR add a second mode panel with:
  - IQ file ingestion (complex float32 interleaved I/Q samples)
  - AM/FM/SSB demodulation options
  - Wide-band frequency display up to Nyquist (currently capped at `displayMaxHz = 6500` in LPC inspector)
  - DTMF / sub-tone (CTCSS/DCS) detection
  - Waterfall display option
  See Section D (Research Tasks) for SDR/RF reference material.

### B-02 🟠 [INCOMPLETE] Live Mic Recording Cannot Be Saved to File
- **Location:** `btnLiveMic` handler ~line 2861–2907
- **Problem:** The live mic mode captures audio into a 4-second ring buffer and analyzes it in real-time, but there is no way to save the captured audio. A forensic user recording live from mic in the field has no export path for what they recorded.
- **Fix:** Add a "Save Mic Recording" button that appears while mic is active. On click: stop capture, snapshot the current `ringBuf`, encode to WAV (reuse existing WAV writer logic), and trigger download.

### B-03 🟠 [INCOMPLETE] Mouse Wheel Zoom Not Implemented
- **Location:** `specViewport` element, `bindEventListeners()` ~line 2989
- **Problem:** Mouse wheel zoom is expected UX for a spectrogram tool. Currently the only zoom method is the `+`/`-` buttons in the toolbar, or drag-mode. No `wheel` event listener exists on `specViewport`.
- **Fix:** Add `els.specViewport.addEventListener('wheel', (e) => {...}, { passive: false })`. On wheel: zoom in/out around the cursor's time position. `e.deltaY < 0` = zoom in (reduce view span by 0.6×), `e.deltaY > 0` = zoom out (expand by 1.4×). Clamp to `[0.05s, state.duration]`.

### B-04 🟡 [INCOMPLETE] Phoneme Classifier: Missing Nasal, Lateral, and Approximant Categories
- **Location:** Phoneme classification ~line 1507–1531
- **Problem:** The phoneme classifier identifies: plosives (/t/, /k/), sibilants (/s/, /ʃ/), vowels (/a/, /i/, /u/), diphthongs (/aɪ/), and whispers. Missing: nasals (/m/, /n/, /ŋ/), laterals (/l/), approximants (/r/, /w/, /j/), voiced fricatives (/z/, /v/, /ð/), affricates (/tʃ/, /dʒ/). These are common in English speech and their absence produces incorrect or "noise" classifications.
- **Fix:** Extend the phoneme logic. Nasals: voiced (F0 > 0) + F1 < 400 Hz + low F2 anti-formant pattern + low overall SNR. Laterals: F0 > 0 + F1 moderate + lateral resonances at 1100/2300 Hz. Research acoustic signatures for each and add classification branches.

### B-05 🟡 [INCOMPLETE] Minimap Click Navigation Ignores Zoom Level
- **Location:** `moveMini()` ~line 3261–3267
- **Problem:** Clicking the minimap centers the viewport at the click position. However, it always uses `span = state.viewT1 - state.viewT0` which is correct. BUT when the viewport is zoomed in and the user clicks near the edge of the minimap, `state.viewT0` can go slightly negative (no lower clamp is effective) or exceed `state.duration - span`. The `Math.max(0, ...)` clamp is present but `state.viewT1 = state.viewT0 + span` may still push `viewT1 > state.duration`.
- **Fix:** After computing `state.viewT0`, clamp: `state.viewT0 = Math.max(0, Math.min(state.duration - span, state.viewT0)); state.viewT1 = state.viewT0 + span;`

### B-06 🟢 [INCOMPLETE] Vowel Space Chart: Only 5 Reference Vowels, No F3 Dimension
- **Location:** `renderVowelSpacePlane()` ~line 2211–2269
- **Problem:** Only 5 reference vowels (/i/, /e/, /a/, /o/, /u/) are plotted in the F1-F2 plane. IPA English has 10+ monophthongs. Also, the F3 dimension (which distinguishes retroflex /r/ from other vowels, and is crucial for rhotic vowels) is not shown anywhere.
- **Fix:** Add the full cardinal vowel set (at minimum /ɪ/, /ɛ/, /æ/, /ɑ/, /ɔ/, /ʊ/). Add a history trail of the last N frames as faded dots so the user can see formant trajectory. Optionally add a 3D view toggle (F2 vs F3) for rhotic analysis.

---

## SECTION C — MISSING FEATURES (FIELD-READINESS)

### C-01 🔴 [MISSING] Web Worker for Background STFT/LPC Processing
- **Dependencies:** Requires Section A-05 bug fix architecture
- **Description:** Create a `worker.js` (or inline via Blob URL) that accepts `{samples, sampleRate, fftSize, hopSize, lpcOrder, alpha, ...}` and returns the full computed matrices. The main thread renders a progress overlay while waiting. Recompute-on-slider-change should debounce (150ms) and cancel in-flight worker computation.

### C-02 🔴 [MISSING] Processing Progress Indicator
- **Description:** When `analyzeFullAudioBuffer()` runs on a large file, the UI freezes with no feedback. Add a blocking overlay or inline progress bar showing "Pass 1/3: STFT (42%)... Pass 2/3: Noise Floor... Pass 3/3: LPC+Mask..." per-frame progress. Blocked by C-01 (needs Worker) for non-blocking progress.

### C-03 🟠 [MISSING] Touch Event Support (Mobile / Tablet)
- **Description:** The entire interaction layer uses only mouse events (`mousedown`, `mousemove`, `mouseup`, `wheel`). Touch events (`touchstart`, `touchmove`, `touchend`) are absent. A field agent using a tablet cannot use ROI selection, panning, or pinch-zoom.
- **Fix:** Add touch→mouse event shims or native touch handlers. For pinch-zoom: track two-touch distance delta to drive zoom. For single-touch drag: mirror mouse drag ROI behavior.

### C-04 🟠 [MISSING] Session Save / Load (localStorage)
- **Description:** All DSP parameters (tightness, alpha, boost, whitening, gamma, VAD threshold, scale, palette, minDb, ROI) are lost on page refresh. A field user needs to save their configured session state.
- **Fix:** Add "Save Session" button that serializes `state` parameters + ROI + sourceName to `localStorage`. Add "Load Session" on startup if a saved session exists. Optionally export/import as JSON file.

### C-05 🟠 [MISSING] Keyboard Shortcuts Help Panel
- **Description:** Only SPACEBAR and ESC are documented (in the tiny HUD bar). The tool has many interactions but no discoverable shortcut guide.
- **Fix:** Add a `?` button (or `Shift+?` shortcut) that opens a modal listing all keyboard shortcuts: SPACE (loop ROI), ESC (close modals), `Z`/`X` (zoom in/out), `R` (reset zoom), `F` (toggle formant dots), `W` (toggle whisper tracking), `M` (toggle solo voice), `P` (pin/unpin slice), `[`/`]` (nudge ROI start/end), arrow keys (pan viewport).

### C-06 🟠 [MISSING] FFT Window Size Control
- **Description:** FFT size is hardcoded at 1024 (state.fftSize = 1024). For detailed tonal analysis of music or RF signals, a 4096 or 8192 FFT offers much better frequency resolution. For highly transient speech (plosives), a smaller 512 FFT offers better time resolution.
- **Fix:** Add a dropdown in "Scale & Colormap" section: 512, 1024 (default), 2048, 4096. Changing this triggers `analyzeFullAudioBuffer()` re-run. Note: `lpcOrder` may need adjustment for larger FFT sizes.

### C-07 🟠 [MISSING] Hop Size (Time Resolution) Control
- **Description:** Hop size is hardcoded at 128 samples (state.hopSize = 128), giving 5.3ms per frame. For ultra-fine temporal resolution of speech transitions, a smaller hop (64 or 32) is needed; for performance on long files, a larger hop (256, 512) is needed.
- **Fix:** Add a hop size selector: 32, 64, 128 (default), 256, 512. Expose as "Time Resolution" control in the Signal Ingest section.

### C-08 🟡 [MISSING] Waveform Time-Domain Panel
- **Description:** The minimap shows amplitude but is tiny. There is no full-resolution time-domain waveform view. Forensic analysis often requires seeing waveform clipping, DC offset, or impulse transients that aren't clearly visible in the spectrogram.
- **Fix:** Add a toggle button to show/hide a tall waveform panel between the minimap and the phoneme ribbon. Render using the same viewport time window as the spectrogram, with the same playhead and ROI time markers synchronized.

### C-09 🟡 [MISSING] Amplitude / Gain Normalization Control
- **Description:** Audio files at very low levels (e.g., covert recordings at -40 dBFS) will show very little in the spectrogram even with whisper boost. There is no global pre-amp/normalization control.
- **Fix:** Add a "Pre-Amp Gain" slider (range: 0 to +60 dB) that scales `state.audioSamples` before analysis. Also add a "Peak Normalize" button that auto-scales to 0 dBFS.

### C-10 🟡 [MISSING] Formant Trajectory CSV Export
- **Description:** The JSON export is comprehensive but includes all frames sampled at 4× downsample. A CSV of F0, F1, F2, F3, F4 trajectories at full frame resolution is needed for import into statistical tools (R, MATLAB, Python/Praat-style analysis).
- **Fix:** Add "Export CSV" button. Output columns: `time_s, phoneme, f0_hz, f1_hz, f2_hz, f3_hz, f4_hz, f1_bw, f2_bw, f3_bw, cpp_db, mask_sparsity`.

### C-11 🟡 [MISSING] Noise Profile Reference Import/Export
- **Description:** The noise floor is estimated from the 20th percentile of the current audio buffer. For recordings where the first portion IS signal (no silence at the start), this estimate is poor. A reference noise file (recorded in the same room without speech) should be importable to provide a more accurate noise floor.
- **Fix:** Add "Import Noise Reference" button that loads a second audio file, computes its power spectrum, and stores it as `state.noiseFloorPow`. Add "Export Noise Profile" to save the current floor estimate.

### C-12 🟡 [MISSING] Playback Speed / Pitch Control
- **Description:** For forensic analysis of fast speech or strong accents, slowing playback to 50% (with or without pitch correction) is essential. Currently there is no speed control.
- **Fix:** Expose `AudioBufferSourceNode.playbackRate` on the `Full Play` button. Add a speed selector: 0.25×, 0.5×, 0.75×, 1.0× (default), 1.5×. For pitch-preserving time-stretch, this requires a phase vocoder (see Research section).

### C-13 🟡 [MISSING] DTMF / Tone Squelch Detection
- **Description:** Forensic audio from radio intercepts often contains DTMF tones, CTCSS sub-audible tones (67–254 Hz), DCS digital tones, and two-tone paging sequences. None of these are detected or highlighted.
- **Fix:** Add a "Tone Detection" sub-panel with toggles for: DTMF (detect digit matrix from 697/770/852/941 Hz × 1209/1336/1477/1633 Hz pairs), CTCSS (scan 67–255 Hz for tones with < 2 Hz bandwidth), and a generic single-tone detector (user-specified Hz). Highlight detected tones in the phoneme ribbon with distinct color.

### C-14 🟡 [MISSING] Per-Panel Screenshot / Export
- **Description:** The "Export PNG" button exports only the main spectrogram canvas. The LPC slice inspector, vowel space chart, and phoneme ribbon cannot be independently exported.
- **Fix:** Add per-panel export buttons (small save icon on each panel header). Use `canvas.toDataURL('image/png')` for each canvas.

### C-15 🟢 [MISSING] Multi-File Comparison Mode
- **Description:** Forensic voice comparison (speaker identification) requires side-by-side comparison of two recordings. Currently only one file can be loaded at a time.
- **Fix:** Add a second file slot and a split-view or overlay mode. In overlay mode, draw second file's formant tracks in a different color (e.g., dashed) over the first file's display.

### C-16 🟢 [MISSING] Speaker Gender / Register Estimation
- **Description:** Given the F0 track, a simple heuristic can estimate speaker register: Typical female F0: 165–255 Hz, male: 85–155 Hz, child: 250–400 Hz. This is displayed in the header telemetry as a rough indicator useful for field identification.
- **Fix:** After `recomputeLPCAndPinpointMask`, compute voiced frame mean F0 (already done for `telMeanF0`). Add a derived "REGISTER" telemetry pill showing "M (bass)" / "M" / "F" / "Child" / "?" based on F0 range.

### C-17 🟢 [MISSING] Accessibility: No ARIA Labels, No Keyboard Navigation for Sliders
- **Description:** All sliders, canvases, and buttons lack `aria-label` attributes. The tool is unusable for users relying on screen readers or keyboard-only navigation.
- **Fix:** Add `aria-label` attributes to all interactive controls. Ensure all buttons are focusable. Add `aria-live` region for the log console.

---

## SECTION D — RESEARCH TASKS (REFERENCE MATERIAL)

### D-01 🔴 [RESEARCH] Web Audio API — AudioWorklet Architecture & Migration from ScriptProcessor
- **Goal:** Understand AudioWorklet lifecycle, `AudioWorkletProcessor` class, `MessagePort` communication pattern, and how to inline worklet code as a Blob URL (to keep single-file architecture).
- **Search terms:** "AudioWorklet tutorial MDN", "AudioWorkletProcessor onaudioprocess replacement", "inline AudioWorklet Blob URL", "Web Audio API live mic AudioWorklet 2024"
- **Key docs:** https://developer.mozilla.org/en-US/docs/Web/API/AudioWorklet, W3C Web Audio API spec §AudioWorklet

### D-02 🔴 [RESEARCH] Web Workers — Transferable Objects for Audio DSP
- **Goal:** Learn how to pass large Float32Arrays to workers using `Transferable` objects (zero-copy), how to post progress messages back, and how to cancel in-flight computation.
- **Search terms:** "Web Worker Transferable Float32Array", "Web Worker postMessage progress callback", "Web Worker terminate cancel", "SharedArrayBuffer audio DSP"
- **Key docs:** MDN Web Workers API, "Using Web Workers" guide

### D-03 🔴 [RESEARCH] SDR / RF Signal Processing in JavaScript
- **Goal:** Research existing JS SDR libraries and approaches for IQ sample ingestion, AM/FM/SSB demodulation, and waterfall display — to implement the "RF audio" capability promised in the app title.
- **Search terms:** "JavaScript SDR library IQ demodulation", "WebSDR browser-based", "rtl-sdr.js npm", "DSP.js SDR browser", "GNU Radio JavaScript", "WebUSB RTL-SDR"
- **Key candidates:** `rtlsdr.js`, `dsp.js`, `sdr.js`, GNU Radio web extensions, WebUSB-based SDR drivers

### D-04 🟠 [RESEARCH] Phase Vocoder / Time-Stretch in JavaScript
- **Goal:** Implement pitch-preserving playback speed control (C-12). Phase vocoders are the standard algorithm. Need to understand overlap-add phase vocoder, or find a battle-tested JS implementation.
- **Search terms:** "phase vocoder JavaScript", "Web Audio API time stretch", "SoundTouchJS", "RubberBand audio time stretch WASM", "pitch-preserving time stretch browser"
- **Key candidates:** SoundTouch.js, RubberBand (has WASM build), Paulstretch algorithm

### D-05 🟠 [RESEARCH] DTMF / CTCSS / DCS Detection Algorithms
- **Goal:** Implement tone detection (C-13). Need frequency domain detection for DTMF matrix (8 tones), CTCSS sub-tones (51 standard tones 67–254 Hz), and DCS (digital coded squelch) bit sequences.
- **Search terms:** "DTMF detection Goertzel algorithm JavaScript", "CTCSS frequency list standard", "DCS codes table", "tone detection Web Audio API", "Goertzel algorithm DSP"
- **Key algorithm:** Goertzel Algorithm (efficient single-frequency DFT, far better than full FFT for known-tone detection)

### D-06 🟠 [RESEARCH] LPC Vocal Tract Model — Higher-Order and MFCC Alternatives
- **Goal:** Understand whether 18th-order LPC is optimal for all sample rates (currently hardcoded `p=18`). Research optimal order selection (rule of thumb: `p = sr/1000 + 4` → at 24kHz, p=28). Also research MFCC (Mel Frequency Cepstral Coefficients) as an alternative feature set for phoneme classification.
- **Search terms:** "LPC order selection speech analysis", "optimal LPC order 24kHz", "MFCC vs LPC formant extraction", "Levinson-Durbin order selection criteria", "Burg LPC algorithm vs autocorrelation"

### D-07 🟠 [RESEARCH] Formant Tracking — Kalman Filter / Dynamic Programming Smoothing
- **Goal:** The current formant extraction uses 3-frame neighbor continuity verification. This is primitive. Research Kalman filter-based formant tracking (used in Praat, WaveSurfer) for smoother trajectories, especially across fricative/plosive boundaries.
- **Search terms:** "Kalman filter formant tracking speech", "formant tracking dynamic programming", "Praat formant algorithm", "formant continuity interpolation Viterbi", "formant tracker robust noise"

### D-08 🟡 [RESEARCH] WASM / Emscripten Audio DSP Libraries
- **Goal:** The STFT+LPC pipeline is pure JS. Research whether compiling a C++ DSP library (e.g., libsndfile, FFTW, libspeex) to WASM would yield a significant speedup for large files.
- **Search terms:** "FFTW WASM Emscripten browser", "libspeex WebAssembly LPC", "Web Audio WASM DSP comparison benchmark", "Essentia.js WASM audio analysis", "Meyda.js audio features"
- **Key candidates:** Essentia.js (WASM, includes LPC + MFCC), Meyda.js (Web Audio features), FFTW3 WASM port

### D-09 🟡 [RESEARCH] Canvas 2D Rendering Performance — OffscreenCanvas & ImageData Optimization
- **Goal:** The main spectrogram redraws every pixel on each render. For 1920×800 displays, this is ~1.5M pixel operations per render. Research OffscreenCanvas + `transferToImageBitmap()` for background rendering, typed array RGBA optimization, and WebGL-based spectrogram rendering.
- **Search terms:** "OffscreenCanvas spectrogram rendering", "Canvas2D ImageData performance optimization", "WebGL spectrogram shader", "Canvas typed array RGBA loop optimization", "createImageBitmap transferToImageBitmap"

### D-10 🟡 [RESEARCH] Browser-Based Speech Recognition / Phoneme Alignment APIs
- **Goal:** Research whether the Web Speech API or WASM speech engines (Whisper.cpp, Vosk) can provide phoneme-level transcription to augment the LPC-based phoneme classifier.
- **Search terms:** "Whisper.cpp WebAssembly browser", "Vosk speech recognition WASM", "Web Speech API phoneme alignment", "wav2vec2 ONNX browser", "speaker diarization JavaScript"
- **Key candidates:** Whisper.cpp WASM (OpenAI), Vosk WASM, transformers.js (Hugging Face), wav2vec2 via ONNX Runtime Web

### D-11 🟡 [RESEARCH] Audio Fingerprinting & Speaker Identification
- **Goal:** For voice comparison (C-15), research speaker identification features: i-vectors, x-vectors, Gaussian Mixture Models trained on MFCC. Research if any pre-trained models run in-browser via ONNX/WASM.
- **Search terms:** "speaker identification WASM browser", "i-vector speaker verification JavaScript", "x-vector ONNX inference browser", "pyannote audio ONNX export", "speaker diarization lightweight"

### D-12 🟡 [RESEARCH] IPA Phoneme Set & Acoustic Feature Databases
- **Goal:** The phoneme classifier needs reference F1/F2/F3 ranges for all IPA vowels and consonant features. Compile a reference table from existing acoustic phonetics databases.
- **Search terms:** "IPA vowel formant database F1 F2 reference values", "Peterson Barney 1952 vowel formants", "Hillenbrand 1995 vowel formant data", "acoustic correlates consonants IPA", "open source formant database speech"
- **Key references:** Peterson & Barney (1952), Hillenbrand et al. (1995), Kent & Read "The Acoustic Analysis of Speech"

### D-13 🟡 [RESEARCH] Praat / Acoustic Analysis Tool Reference
- **Goal:** Study Praat's algorithms (the gold standard in phonetic analysis) for formant extraction, pitch tracking, and spectrogram generation to identify any algorithmic gaps in VocalVizard's implementation.
- **Search terms:** "Praat formant algorithm source code", "Praat LPC implementation", "Praat spectrogram Gaussian window", "Praat pitch algorithm autocorrelation", "Praat vs LPC Burg method"

### D-14 🟢 [RESEARCH] WebRTC Audio Processing Pipeline
- **Goal:** The live mic mode disables echo cancellation and AGC, but WebRTC's AEC (Acoustic Echo Cancellation) and noise suppression algorithms are mature and battle-tested. Research whether `insertable-streams` or `MediaStreamTrack.getCapabilities()` can selectively apply/bypass WebRTC processing for forensic mic capture.
- **Search terms:** "WebRTC AEC bypass forensic audio", "getUserMedia echoCancellation false", "MediaStreamTrack noise suppression disable", "WebRTC audio pipeline raw capture"

### D-15 🟢 [RESEARCH] Single-File App Bundling & Offline Deployment
- **Goal:** VocalVizard relies on CDN (Tailwind CSS, Google Fonts). For field use in network-denied environments (bunkers, SCIF, remote locations), all dependencies must be embedded.
- **Search terms:** "embed Tailwind CSS single file HTML", "Google Fonts self-hosted embed base64", "inline CDN resources single HTML file", "html-inline tool", "webpack single HTML bundle"
- **Key tools:** `htmlmin`, `monolith` CLI, `wget --page-requisites`, Tailwind CLI (local build), `pyinstaller` for Python wrapper

---

## SECTION E — ARCHITECTURE & REFACTORING

### E-01 🟠 [PERF] Spectrogram Column Caching — Skip Re-render on Pan
- **Description:** When panning the view (Shift+drag), `renderMainSpectrogram` redraws all pixels from scratch. Since the DSP matrices don't change on pan, the rendered pixel columns should be cached and only the new visible columns need to be computed. Use an offscreen canvas as a tile cache.

### E-02 🟡 [PERF] `Float32Array.sort()` for Percentile Noise Floor — Replace with nth_element
- **Location:** `analyzeFullAudioBuffer()` ~line 1393–1399
- **Description:** Sorting the entire `colBuf` (numFrames elements) per bin to find the 20th percentile is O(n log n). For 300 frames × 512 bins, this is ~300×512×log(300) ≈ 1.2M operations. Replace with a partial sort / nth-element algorithm (O(n)) or maintain a running histogram per bin.

### E-03 🟡 Code Organization — Split Single File into Logical Modules
- **Description:** The 3300-line file is difficult to maintain. Consider splitting into:
  - `dsp-core.js` (FFT, LPC, Klatt, pitch)
  - `renderer.js` (all canvas rendering)
  - `audio-io.js` (file load, mic, raw PCM, AudioContext)
  - `ui-events.js` (event binding)
  - `exports.js` (WAV, PNG, JSON, CSV)
  Then use a simple build step (esbuild or rollup) to bundle back to a single file for deployment.

### E-04 🟢 [PERF] Phoneme Ribbon — Use Pre-Computed Segment Array
- **Location:** `renderPhonemeRibbon()` ~line 1785–1841
- **Description:** The phoneme ribbon re-segments the `phonemeTrack` array on every render. For 300+ frames, this runs 300 iterations on every frame of animation. Cache the segment array and only recompute when `phonemeTrack` changes (i.e., after `recomputeLPCAndPinpointMask`).

---

## IMPLEMENTATION PRIORITY ORDER

1. **A-01** HiDPI spectrogram fix (visual quality — immediate impact)
2. **B-03** Mouse wheel zoom (critical UX)
3. **A-05 + C-01** Web Worker (performance — enables all large-file work)
4. **C-02** Progress indicator (depends on Worker)
5. **A-02** AudioWorklet mic fix (stability)
6. **A-03** AudioContext rate fix (correctness)
7. **A-04** Stereo downmix (data integrity)
8. **B-01** RF integration or title fix (scope clarification — decide direction first)
9. **A-06** F4 overlay (quick win)
10. **A-07** Zoom mode fix (correctness)
11. **B-02** Save mic recording (field utility)
12. **C-05** Keyboard shortcuts panel
13. **C-04** Session save/load
14. **C-03** Touch support
15. **C-10** CSV export
16. **C-06/C-07** FFT/hop controls
17. **B-04** Phoneme classifier expansion (D-12 research first)
18. **C-12** Playback speed control (D-04 research first)
19. **C-13** DTMF/tone detection (D-05 research first)
20. **C-08** Waveform panel

---

*Generated by automated audit — 2026-10-28. Update status as tasks are completed.*
