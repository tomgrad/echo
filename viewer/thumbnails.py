import numpy as np
from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QImage

import dicom_io
from viewer.frames import decode_frame
from viewer.session import RecordingInfo


def _normalize_mono(frame: np.ndarray, levels) -> np.ndarray:
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
        arr = np.ascontiguousarray(_normalize_mono(frame, levels))
        fmt = QImage.Format_Grayscale8
        channels = 1
    height, width = arr.shape[0], arr.shape[1]
    data = arr.tobytes()
    image = QImage(data, width, height, width * channels, fmt)
    return image.copy()


def thumbnail_qimage(frame: np.ndarray, levels, width: int = 180) -> QImage:
    image = qimage_from_frame(frame, levels)
    return image.scaledToWidth(width, Qt.SmoothTransformation)


class _ThumbnailTask(QRunnable):
    def __init__(self, provider: "ThumbnailProvider", info: RecordingInfo):
        super().__init__()
        self._provider = provider
        self._info = info

    def run(self):
        path = self._info.path
        try:
            frame = decode_frame(self._info, self._info.frames // 2)
            levels = None if self._info.is_color else dicom_io.mono_levels(frame)
            image = thumbnail_qimage(frame, levels)
        except Exception as exc:
            self._provider.thumbnail_failed.emit(path, str(exc) or type(exc).__name__)
            return
        self._provider.thumbnail_ready.emit(path, image)


class ThumbnailProvider(QObject):
    thumbnail_ready = Signal(object, object)
    thumbnail_failed = Signal(object, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)

    def request(self, info: RecordingInfo) -> None:
        self._pool.start(_ThumbnailTask(self, info))
