"""Video (MPEG-4 / AVI) reading helpers, the counterpart of dicom_io."""

from pathlib import Path

import cv2
import numpy as np

VIDEO_SUFFIXES = frozenset({".mp4", ".m4v", ".mpg", ".mpeg", ".avi"})


def is_video(path: str | Path) -> bool:
    return Path(path).suffix.lower() in VIDEO_SUFFIXES


def _open(path: str | Path) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        cap.release()
        raise ValueError(f"cannot open video: {path}")
    return cap


def read_meta(path: str | Path) -> tuple[int, int, int, float]:
    """Return (frames, rows, cols, fps); fps falls back to 30 if unreported."""
    cap = _open(path)
    try:
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cols = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        rows = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(cap.get(cv2.CAP_PROP_FPS))
    finally:
        cap.release()
    if frames <= 0 or rows <= 0 or cols <= 0:
        raise ValueError(f"video has no readable frames: {path}")
    if not np.isfinite(fps) or fps <= 0:
        fps = 30.0
    return frames, rows, cols, fps


def read_frames(path: str | Path, count: int, rows: int, cols: int) -> np.ndarray:
    """Decode up to `count` RGB frames into one preallocated array."""
    cap = _open(path)
    try:
        frames = np.empty((count, rows, cols, 3), dtype=np.uint8)
        n = 0
        while n < count:
            ok, bgr = cap.read()
            if not ok:
                break
            frames[n] = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            n += 1
    finally:
        cap.release()
    if n == 0:
        raise ValueError(f"video has no readable frames: {path}")
    return frames[:n]


def read_frame(path: str | Path, index: int) -> np.ndarray:
    cap = _open(path)
    try:
        cap.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, bgr = cap.read()
        if not ok and index > 0:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, bgr = cap.read()
    finally:
        cap.release()
    if not ok:
        raise ValueError(f"cannot read frame {index}: {path}")
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
