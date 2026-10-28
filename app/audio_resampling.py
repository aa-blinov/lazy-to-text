"""Bounded-memory polyphase resampling using the NumPy already in the runtime."""

from __future__ import annotations

from math import gcd

import numpy as np

_OUTPUT_CHUNK = 8_192


def resample_audio(audio: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    """Resample audio with a windowed-sinc anti-alias filter.

    The FIR is evaluated by polyphase in bounded output chunks. This keeps the
    microphone stop path independent of SciPy's Windows BLAS DLL import and
    avoids allocating a full-length coordinate grid for long recordings.
    """
    if source_rate <= 0 or target_rate <= 0:
        raise ValueError("sample rates must be positive")
    if source_rate == target_rate or audio.shape[0] == 0:
        return audio.astype(np.float32, copy=False)

    divisor = gcd(int(source_rate), int(target_rate))
    up = int(target_rate) // divisor
    down = int(source_rate) // divisor
    input_length = audio.shape[0]
    output_length = (input_length * up + down - 1) // down
    output = np.empty((output_length, *audio.shape[1:]), dtype=np.float32)

    max_rate = max(up, down)
    half_length = 10 * max_rate
    taps_count = 2 * half_length + 1
    offsets = np.arange(taps_count, dtype=np.float64) - half_length
    taps = np.sinc(offsets / max_rate) / max_rate
    window_arg = np.clip(1.0 - (offsets / half_length) ** 2, 0.0, 1.0)
    taps *= np.i0(5.0 * np.sqrt(window_arg)) / np.i0(5.0)
    taps /= taps.sum()
    taps *= up

    # Center the symmetric FIR so output sample zero is aligned to input zero,
    # matching the delay removal used by the usual polyphase construction.
    pre_padding = down - half_length % down
    first_output_delay = (half_length + pre_padding) // down
    tap_count_per_phase = (taps_count + up - 1) // up + 1
    tap_offsets = np.arange(tap_count_per_phase, dtype=np.int64)

    for start in range(0, output_length, _OUTPUT_CHUNK):
        end = min(start + _OUTPUT_CHUNK, output_length)
        output_indices = np.arange(start, end, dtype=np.int64)
        filter_positions = (output_indices + first_output_delay) * down
        delayed_positions = filter_positions - pre_padding
        input_max = delayed_positions // up
        input_indices = input_max[:, None] - tap_offsets
        filter_indices = delayed_positions[:, None] - input_indices * up
        valid = (
            (input_indices >= 0)
            & (input_indices < input_length)
            & (filter_indices >= 0)
            & (filter_indices < taps_count)
        )
        safe_input = np.clip(input_indices, 0, input_length - 1)
        safe_filter = np.clip(filter_indices, 0, taps_count - 1)
        weights = np.where(valid, taps[safe_filter], 0.0)
        samples = audio[safe_input]
        if audio.ndim == 1:
            output[start:end] = np.sum(samples * weights, axis=1).astype(np.float32)
        else:
            output[start:end] = np.sum(
                samples * weights[:, :, None], axis=1
            ).astype(np.float32)

    return output
