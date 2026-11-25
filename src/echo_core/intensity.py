"""Per-frame mean intensity of the masked area."""

import numpy as np


def masked_mean_intensity(volume: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Mean of `volume` over nonzero `mask` pixels, per frame.

    `volume` and `mask` are (T, H, W). Frames with an empty mask give NaN.
    """
    if volume.shape != mask.shape or volume.ndim != 3:
        raise ValueError(f"shape mismatch: volume {volume.shape}, mask {mask.shape}")
    result = np.full(volume.shape[0], np.nan, dtype=np.float64)
    for index in range(volume.shape[0]):
        selected = mask[index] > 0
        if selected.any():
            result[index] = volume[index][selected].mean(dtype=np.float64)
    return result


def masked_area(mask: np.ndarray) -> np.ndarray:
    """Number of nonzero `mask` pixels per frame; `mask` is (T, H, W)."""
    if mask.ndim != 3:
        raise ValueError(f"expected (T, H, W) mask, got {mask.shape}")
    return np.count_nonzero(mask.reshape(mask.shape[0], -1), axis=1).astype(np.float64)


def normalize_minmax(values: np.ndarray) -> np.ndarray:
    """Scale finite values to [0, 1]; NaN stays NaN, a flat series maps to 0.5."""
    values = np.asarray(values, dtype=np.float64)
    finite = np.isfinite(values)
    out = np.full(values.shape, np.nan)
    if not finite.any():
        return out
    lo = values[finite].min()
    hi = values[finite].max()
    if hi - lo < 1e-12:
        out[finite] = 0.5
    else:
        out[finite] = (values[finite] - lo) / (hi - lo)
    return out
