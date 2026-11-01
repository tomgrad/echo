"""Frame-to-display conversion shared by the apps: levels, axis order, QImage."""
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage


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


def normalize_mono(frame: np.ndarray, levels) -> np.ndarray:
    arr = np.asarray(frame, dtype=np.float32)
    if levels is None:
        low, high = float(arr.min()), float(arr.max())
    else:
        low, high = float(levels[0]), float(levels[1])
    if high <= low:
        high = low + 1.0
    scaled = (arr - low) / (high - low) * 255.0
    return np.clip(scaled, 0, 255).astype(np.uint8)


def qimage_from_frame(frame: np.ndarray, levels) -> QImage:
    if frame.ndim == 3 and frame.shape[-1] == 3:
        arr = np.ascontiguousarray(np.clip(frame, 0, 255).astype(np.uint8))
        fmt = QImage.Format_RGB888
        channels = 3
    else:
        arr = np.ascontiguousarray(normalize_mono(frame, levels))
        fmt = QImage.Format_Grayscale8
        channels = 1
    height, width = arr.shape[0], arr.shape[1]
    data = arr.tobytes()
    image = QImage(data, width, height, width * channels, fmt)
    return image.copy()


def thumbnail_qimage(frame: np.ndarray, levels, width: int = 180) -> QImage:
    image = qimage_from_frame(frame, levels)
    return image.scaledToWidth(width, Qt.SmoothTransformation)
