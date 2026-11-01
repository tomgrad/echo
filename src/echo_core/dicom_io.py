"""Shared DICOM reading helpers used by Echo and the viewer."""

import math
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
    if math.isfinite(number) and number > 0:
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
        rate = 1000.0 / frame_time
        if math.isfinite(rate):
            return rate
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
