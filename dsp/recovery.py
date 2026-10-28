"""Recovery engine — Path A (cleaned signal) and Path B (synthetic reconstruction)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple

import numpy as np
import scipy.signal


@dataclass
class RecoveryParams:
    alpha: float = 2.20
    hpss_margin: float = 1.0
    fft_sizes: Tuple[int, ...] = (512, 1024, 2048)
    hop_size: int = 128


# ---------------------------------------------------------------------------
# Path A: multi-resolution STFT + HPSS harmonic extraction
# ---------------------------------------------------------------------------

def build_path_a(
    samples: np.ndarray,
    sample_rate: int,
    params: RecoveryParams,
) -> np.ndarray:
    """Recover cleaned vocal signal via multi-resolution Wiener filtering + HPSS.

    Steps:
    1. Compute STFT at each of params.fft_sizes
    2. Per resolution: noise floor (20th pct) → Wiener spectral subtraction
    3. Apply HPSS on 1024-resolution to keep only harmonic component
    4. Fuse three resolutions (element-wise max, resampled to 1024 grid)
    5. Reconstruct via iSTFT using 1024 STFT phase + fused magnitude
    6. Peak-normalise to 0.9, clip to [-1, 1]

    Parameters
    ----------
    samples     : float32 PCM, any length
    sample_rate : Hz
    params      : RecoveryParams

    Returns
    -------
    float32 PCM, same length as input
    """
    from dsp.hpss import apply_hpss

    target_len = len(samples)

    # Compute STFT at each resolution
    stft_results = {}
    for fft_size in params.fft_sizes:
        noverlap = fft_size - params.hop_size
        f, t, Zxx = scipy.signal.stft(
            samples.astype(np.float64),
            fs=sample_rate,
            nperseg=fft_size,
            noverlap=noverlap,
            window="blackmanharris",
        )
        stft_results[fft_size] = (f, t, Zxx)

    # Reference resolution
    ref_size = 1024
    _, t_ref, Zxx_ref = stft_results[ref_size]
    num_bins_ref = ref_size // 2
    ref_mag = np.abs(Zxx_ref[:num_bins_ref, :]).T.astype(np.float32)  # [frames, bins]
    ref_phase = np.angle(Zxx_ref[:num_bins_ref, :]).T.astype(np.float32)

    # Clean each resolution
    cleaned_mags = {}
    for fft_size in params.fft_sizes:
        _, _, Zxx = stft_results[fft_size]
        num_bins = fft_size // 2
        mag = np.abs(Zxx[:num_bins, :]).T.astype(np.float32)  # [frames, bins]

        # Noise floor: 20th percentile per bin
        noise_floor = np.percentile(mag, 20, axis=0).astype(np.float32)
        noise_floor = np.maximum(noise_floor, 1e-20)

        # Wiener subtraction
        clean = np.maximum(
            params.alpha * noise_floor * 0.1,
            mag - params.alpha * noise_floor,
        )
        cleaned_mags[fft_size] = (clean, num_bins)

    # Apply HPSS on reference (1024) — keep harmonic component
    h_mag, _ = apply_hpss(cleaned_mags[ref_size][0], margin=params.hpss_margin)

    # Fuse by taking element-wise max across all resolutions, resampled to ref grid
    fused = h_mag.copy()
    for fft_size in params.fft_sizes:
        if fft_size == ref_size:
            continue
        clean, num_bins = cleaned_mags[fft_size]
        # Resample bin axis to match reference (num_bins_ref bins)
        resampled = np.zeros((clean.shape[0], num_bins_ref), dtype=np.float32)
        old_bins = np.linspace(0, 1, num_bins)
        new_bins = np.linspace(0, 1, num_bins_ref)
        for fi in range(min(clean.shape[0], fused.shape[0])):
            resampled[fi] = np.interp(new_bins, old_bins, clean[fi])
        frames_to_use = min(fused.shape[0], resampled.shape[0])
        fused[:frames_to_use] = np.maximum(fused[:frames_to_use], resampled[:frames_to_use])

    # Reconstruct via iSTFT: fused magnitude × reference phase
    fused_complex = fused * np.exp(1j * ref_phase)  # [frames, bins]

    # Build full (two-sided) complex spectrum for iSTFT
    # Zxx_ref shape: [fft_size//2+1, num_frames] — we need same layout
    fused_full = np.zeros_like(Zxx_ref)
    frames = min(fused.shape[0], fused_full.shape[1])
    fused_full[:num_bins_ref, :frames] = fused_complex[:frames].T

    _, recovered = scipy.signal.istft(
        fused_full,
        fs=sample_rate,
        nperseg=ref_size,
        noverlap=ref_size - params.hop_size,
        window="blackmanharris",
    )

    # Trim or pad to original length
    if len(recovered) >= target_len:
        recovered = recovered[:target_len]
    else:
        recovered = np.pad(recovered, (0, target_len - len(recovered)))

    recovered = recovered.astype(np.float32)

    # Peak-normalise to 0.9
    peak = np.max(np.abs(recovered))
    if peak > 1e-8:
        recovered = recovered * (0.9 / peak)

    return np.clip(recovered, -1.0, 1.0)


# ---------------------------------------------------------------------------
# Path B: synthetic reconstruction
# ---------------------------------------------------------------------------

def build_path_b(
    lpc_results,
    pitch_results,
    path_a_samples: np.ndarray,
    sample_rate: int,
    params,  # SynthesisParams
) -> np.ndarray:
    """Build Path B synthetic reconstruction from LPC + pitch evidence.

    Returns float32 PCM of the same length as path_a_samples.
    If no voiced frames exist (strict mode), returns a zero-filled array.
    """
    from dsp.synthesis import KlattSynthesizer, WorldSynthesizer, SynthesisParams
    import scipy.interpolate

    target_len = len(path_a_samples)
    num_frames = len(lpc_results)
    hop = params.path_b_threshold if hasattr(params, "path_b_threshold") else 0.28

    # Threshold for "has evidence"
    threshold = params.path_b_threshold

    has_evidence = [
        (lpc_results[i].f1 is not None and lpc_results[i].f1.prom >= threshold)
        for i in range(num_frames)
    ]

    # --- Speaker Match mode ---
    if params.mode == "speaker_match":
        synth = WorldSynthesizer(sample_rate)
        try:
            feats = synth.extract_features(path_a_samples)
        except Exception:
            # Fall back to generic if WORLD fails
            params = SynthesisParams(
                mode="generic", gaps=params.gaps,
                path_b_threshold=params.path_b_threshold,
            )
            return build_path_b(lpc_results, pitch_results, path_a_samples, sample_rate, params)

        # Replace F0 with our pitch estimates where available
        world_f0 = feats["f0"].copy()
        world_frames = len(world_f0)

        # Map LPC frame pitch to WORLD frame index
        lpc_frame_dur = target_len / sample_rate / num_frames if num_frames > 0 else 0.005
        for f_idx in range(num_frames):
            if not has_evidence[f_idx] and params.gaps == "strict":
                # Find corresponding WORLD frame
                t_center = f_idx * lpc_frame_dur
                w_idx = int(t_center / 0.005)  # WORLD frame period ≈ 5ms
                if 0 <= w_idx < world_frames:
                    world_f0[w_idx] = 0.0
            elif pitch_results[f_idx].f0 > 0:
                t_center = f_idx * lpc_frame_dur
                w_idx = int(t_center / 0.005)
                if 0 <= w_idx < world_frames:
                    world_f0[w_idx] = pitch_results[f_idx].f0

        out = synth.synthesize(world_f0, feats["sp"], feats["ap"])

        # Trim / pad to target_len
        if len(out) >= target_len:
            out = out[:target_len]
        else:
            out = np.pad(out, (0, target_len - len(out)))

        return out.astype(np.float32)

    # --- Generic mode (Klatt) ---
    klatt = KlattSynthesizer(sample_rate)
    samples_per_frame = max(1, target_len // num_frames) if num_frames > 0 else target_len
    output = np.zeros(target_len, dtype=np.float64)

    # Bridge mode: identify short gaps (≤ 80ms) and fill with interpolated formants
    bridge_gaps = set()
    if params.gaps == "bridge":
        max_gap_frames = max(1, int(0.08 * sample_rate / samples_per_frame))
        i = 0
        while i < num_frames:
            if not has_evidence[i]:
                # find gap end
                j = i
                while j < num_frames and not has_evidence[j]:
                    j += 1
                if (j - i) <= max_gap_frames:
                    for k in range(i, j):
                        bridge_gaps.add(k)
            i += 1

    for f_idx in range(num_frames):
        start = f_idx * samples_per_frame
        end = min(target_len, start + samples_per_frame)
        n_samples = end - start
        if n_samples <= 0:
            break

        if has_evidence[f_idx]:
            lpc = lpc_results[f_idx]
            f0 = pitch_results[f_idx].f0 if pitch_results[f_idx].f0 > 0 else 120.0
            f1 = lpc.f1.hz if lpc.f1 else 730.0
            bw1 = lpc.f1.bw if lpc.f1 else 80.0
            f2 = lpc.f2.hz if lpc.f2 else 1090.0
            bw2 = lpc.f2.bw if lpc.f2 else 100.0
            f3 = lpc.f3.hz if lpc.f3 else 2440.0
            bw3 = lpc.f3.bw if lpc.f3 else 120.0
            frame = klatt.synthesize_frame(f0, f1, bw1, f2, bw2, f3, bw3, n_samples)
            output[start:end] = frame
        elif f_idx in bridge_gaps:
            # Bridge: find nearest evidence frames on each side and interpolate
            left = f_idx - 1
            while left >= 0 and not has_evidence[left]:
                left -= 1
            right = f_idx + 1
            while right < num_frames and not has_evidence[right]:
                right += 1

            def get_f1(idx):
                return lpc_results[idx].f1.hz if (0 <= idx < num_frames and lpc_results[idx].f1) else 730.0

            def get_f0(idx):
                return pitch_results[idx].f0 if (0 <= idx < num_frames and pitch_results[idx].f0 > 0) else 120.0

            if left >= 0 and right < num_frames:
                t = (f_idx - left) / max(1, right - left)
            elif left >= 0:
                t = 1.0
            else:
                t = 0.0

            f0_interp = get_f0(left if left >= 0 else right) * (1 - t) + get_f0(right if right < num_frames else left) * t
            f1_interp = get_f1(left if left >= 0 else right) * (1 - t) + get_f1(right if right < num_frames else left) * t

            frame = klatt.synthesize_frame(f0_interp, f1_interp, 80, 1090, 100, 2440, 120, n_samples)
            output[start:end] = frame
        else:
            output[start:end] = 0.0  # strict: silence

    return output.astype(np.float32)
