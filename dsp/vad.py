"""Voice Activity Detection — webrtcvad blended with energy-based detection."""
from __future__ import annotations

import numpy as np
import soxr

_FRAME_DUR_MS = 30       # webrtcvad supports 10, 20, 30 ms
_WEBRTCVAD_SR = 16000    # webrtcvad only supports 8k/16k/32k/48k
_ENERGY_BAND_LO = 200    # Hz — speech band lower bound
_ENERGY_BAND_HI = 3400   # Hz — speech band upper bound
_ENERGY_THRESHOLD = 0.25 # band ratio for energy-based voiced decision


def compute_vad_chunk(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    """Return float32 array with one score per 30ms frame (1.0=voiced, 0.0=unvoiced).

    Blends webrtcvad (speech-pattern detector) with energy-based detection.
    A frame is voiced if EITHER detector says voiced.
    Falls back to energy-only if webrtcvad is unavailable.
    """
    try:
        webrtc_scores = _vad_webrtcvad(samples, sample_rate)
    except Exception:
        webrtc_scores = None

    energy_scores = _vad_energy(samples, sample_rate)

    if webrtc_scores is not None and len(webrtc_scores) == len(energy_scores):
        # Voiced if either detector votes yes
        combined = np.maximum(webrtc_scores, energy_scores)
        return combined.astype(np.float32)

    return energy_scores


def _vad_webrtcvad(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    import webrtcvad

    frame_dur = _FRAME_DUR_MS / 1000.0
    if sample_rate != _WEBRTCVAD_SR:
        s16k = soxr.resample(samples, sample_rate, _WEBRTCVAD_SR, quality="HQ")
    else:
        s16k = samples.copy()

    s16k = np.clip(s16k.astype(np.float32), -1.0, 1.0)
    frame_len = int(_WEBRTCVAD_SR * frame_dur)
    vad = webrtcvad.Vad(3)

    scores = []
    offset = 0
    while offset + frame_len <= len(s16k):
        frame = s16k[offset: offset + frame_len]
        pcm = (frame * 32767).astype(np.int16).tobytes()
        voiced = vad.is_speech(pcm, _WEBRTCVAD_SR)
        scores.append(1.0 if voiced else 0.0)
        offset += frame_len

    return np.array(scores, dtype=np.float32)


def _vad_energy(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    """Energy-band VAD: voiced if speech-band energy > threshold × total energy."""
    frame_dur = _FRAME_DUR_MS / 1000.0
    frame_len = int(sample_rate * frame_dur)

    scores = []
    offset = 0
    while offset + frame_len <= len(samples):
        frame = samples[offset: offset + frame_len]
        total_energy = float(np.dot(frame, frame))

        if total_energy < 1e-12:
            scores.append(0.0)
            offset += frame_len
            continue

        fft = np.fft.rfft(frame)
        freqs = np.fft.rfftfreq(len(frame), d=1.0 / sample_rate)
        band_mask = (freqs >= _ENERGY_BAND_LO) & (freqs <= _ENERGY_BAND_HI)
        band_energy = float(np.sum(np.abs(fft[band_mask]) ** 2))
        total_fft_energy = float(np.sum(np.abs(fft) ** 2)) + 1e-20
        ratio = band_energy / total_fft_energy

        scores.append(1.0 if ratio > _ENERGY_THRESHOLD else 0.0)
        offset += frame_len

    return np.array(scores, dtype=np.float32)
