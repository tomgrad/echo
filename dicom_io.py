"""Shared DICOM reading helpers used by Echo and the viewer."""

from pathlib import Path

import numpy as np
import pydicom
from pydicom.pixels import pixel_array

DEFAULT_FPS: float = 30.0


def read_header(path: str | Path) -> pydicom.Dataset:
    return pydicom.dcmread(path, stop_before_pixels=True)


def read_dataset(path: str | Path) -> pydicom.Dataset:
    return pydicom.dcmread(path)


def frame_count(ds: pydicom.Dataset) -> int:
    try:
        return max(1, int(ds.get("NumberOfFrames", 1) or 1))
    except (ValueError, TypeError):
        return 1


def _positive_float(value) -> float | None:
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    if number > 0:
        return number
    return None


def fps(ds: pydicom.Dataset) -> float:
    cine = _positive_float(ds.get("CineRate"))
    if cine is not None:
        return cine
    recommended = _positive_float(ds.get("RecommendedDisplayFrameRate"))
    if recommended is not None:
        return recommended
    frame_time = _positive_float(ds.get("FrameTime"))
    if frame_time is not None:
        return 1000.0 / frame_time
    return DEFAULT_FPS


def is_color(ds: pydicom.Dataset) -> bool:
    return int(ds.get("SamplesPerPixel", 1) or 1) > 1


def is_still(ds: pydicom.Dataset) -> bool:
    return frame_count(ds) == 1


def pixel_frames(ds: pydicom.Dataset) -> np.ndarray:
    return pixel_array(ds)


def pixel_frame(ds: pydicom.Dataset, index: int) -> np.ndarray:
    if frame_count(ds) == 1:
        return pixel_frames(ds)
    return pixel_array(ds, index=index)


def display_array(arr: np.ndarray, color: bool) -> np.ndarray:
    # ImageView takes (x=col, y=row); swap rows/cols and keep an RGB channel axis last.
    if color:
        return np.swapaxes(arr, -3, -2)
    return np.swapaxes(arr, -2, -1)


def mono_levels(frames: np.ndarray) -> tuple[float, float]:
    if frames.ndim > 2:
        count = frames.shape[0]
        idx = np.linspace(0, count - 1, min(16, count)).round().astype(int)
        sample = frames[idx]
    else:
        sample = frames
    low, high = np.percentile(sample, [1, 99])
    low, high = float(low), float(high)
    if high <= low:
        high = low + 1.0
    return low, high
