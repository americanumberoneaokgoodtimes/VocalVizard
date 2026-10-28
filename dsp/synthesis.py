"""Path B synthesis — Klatt cascade IIR synthesizer + pyworld Speaker Match."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass
class SynthesisParams:
    mode: str = "generic"            # "generic" | "speaker_match"
    gaps: str = "strict"             # "strict" | "bridge"
    path_b_threshold: float = 0.28   # minimum LPC prominence to synthesize frame
    blend_ratio: float = 0.5         # used by routes layer, not synthesis


# ---------------------------------------------------------------------------
# Klatt cascade IIR resonator
# ---------------------------------------------------------------------------

class _IIRResonator:
    """Single 2nd-order digital resonator (Klatt form)."""

    def __init__(self) -> None:
        self._y1 = 0.0
        self._y2 = 0.0

    def process(
        self, signal: np.ndarray, f_hz: float, bw_hz: float, sample_rate: int
    ) -> np.ndarray:
        Ts = 1.0 / sample_rate
        r = math.exp(-math.pi * bw_hz * Ts)
        theta = 2.0 * math.pi * f_hz * Ts
        B = 2.0 * r * math.cos(theta)
        C = -(r * r)
        A = 1.0 - B - C

        output = np.empty_like(signal)
        y1 = self._y1
        y2 = self._y2
        for i, x in enumerate(signal):
            y = A * float(x) + B * y1 + C * y2
            y2 = y1
            y1 = y
            output[i] = y
        self._y1 = y1
        self._y2 = y2
        return output


class KlattSynthesizer:
    """Cascade Klatt synthesizer: Rosenberg pulse → 3 IIR resonators → lip radiation."""

    def __init__(self, sample_rate: int = 24000) -> None:
        self._sr = sample_rate

    def synthesize_frame(
        self,
        f0: float,
        f1: float, bw1: float,
        f2: float, bw2: float,
        f3: float, bw3: float,
        num_samples: int,
    ) -> np.ndarray:
        """Generate one frame of voiced speech synthesis.

        Parameters
        ----------
        f0             : fundamental frequency (Hz); 0 = unvoiced → returns zeros
        f1..f3, bw1..3 : formant frequencies and bandwidths (Hz)
        num_samples    : number of output samples

        Returns
        -------
        float32 array of length num_samples
        """
        if f0 <= 0.0 or num_samples <= 0:
            return np.zeros(num_samples, dtype=np.float32)

        # Rosenberg glottal pulse train
        glottal = self._rosenberg_pulse(f0, num_samples)

        # Cascade through 3 resonators
        r1 = _IIRResonator()
        r2 = _IIRResonator()
        r3 = _IIRResonator()
        out = r1.process(glottal, f1, bw1, self._sr)
        out = r2.process(out, f2, bw2, self._sr)
        out = r3.process(out, f3, bw3, self._sr)

        # Lip radiation differentiator
        diff = np.zeros_like(out)
        diff[0] = out[0]
        diff[1:] = out[1:] - 0.95 * out[:-1]

        # Normalise
        peak = np.max(np.abs(diff))
        if peak > 1e-10:
            diff = diff / peak

        return diff.astype(np.float32)

    def _rosenberg_pulse(self, f0: float, num_samples: int) -> np.ndarray:
        """Generate a Rosenberg B glottal pulse train."""
        period = self._sr / f0
        pulse = np.zeros(num_samples, dtype=np.float64)
        t_open = 0.6 * period  # open phase
        t_pos = 0.0
        sample_in_period = 0
        for i in range(num_samples):
            pos = sample_in_period / period
            if pos < 0.6:
                # Rising: 0.5 * (1 - cos(π * pos / 0.6))
                pulse[i] = 0.5 * (1.0 - math.cos(math.pi * pos / 0.6))
            elif pos < 1.0:
                # Falling
                pulse[i] = 0.5 * (1.0 - math.cos(math.pi * (pos - 0.6) / 0.4))
                pulse[i] = 1.0 - pulse[i]
            sample_in_period += 1
            if sample_in_period >= int(period):
                sample_in_period = 0
        return pulse


# ---------------------------------------------------------------------------
# pyworld Speaker-Match synthesizer
# ---------------------------------------------------------------------------

class WorldSynthesizer:
    """WORLD vocoder wrapper for speaker-match synthesis."""

    def __init__(self, sample_rate: int = 24000) -> None:
        self._sr = sample_rate

    def extract_features(self, path_a_chunk: np.ndarray) -> dict:
        """Extract F0, spectral envelope, aperiodicity from Path A audio."""
        import pyworld

        x = path_a_chunk.astype(np.float64)
        f0, t = pyworld.dio(x, self._sr)
        f0 = pyworld.stonemask(x, f0, t, self._sr)
        sp = pyworld.cheaptrick(x, f0, t, self._sr)
        ap = pyworld.d4c(x, f0, t, self._sr)
        return {"f0": f0, "sp": sp, "ap": ap, "t": t}

    def synthesize(
        self, f0: np.ndarray, sp: np.ndarray, ap: np.ndarray
    ) -> np.ndarray:
        """Synthesize speech from WORLD features."""
        import pyworld

        out = pyworld.synthesize(f0, sp, ap, self._sr)
        out = np.clip(out, -1.0, 1.0)
        return out.astype(np.float32)
