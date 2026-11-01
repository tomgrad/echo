import numpy as np
from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QImage

from echo_core import dicom_io
from echo_viewer.frames import decode_frame
from echo_viewer.session import RecordingInfo


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
    def __init__(self, provider: "ThumbnailProvider", info: RecordingInfo, generation: int):
        super().__init__()
        self._provider = provider
        self._info = info
        self._generation = generation

    def run(self):
        provider = self._provider
        if not provider.is_current(self._generation):
            return
        path = self._info.path
        try:
            frame = decode_frame(self._info, self._info.frames // 2)
            levels = None if self._info.is_color else dicom_io.mono_levels(frame)
            image = thumbnail_qimage(frame, levels)
        except Exception as exc:
            provider._raw_failed.emit(
                path, str(exc) or type(exc).__name__, self._generation
            )
            return
        provider._raw_ready.emit(path, image, self._generation)


class ThumbnailProvider(QObject):
    thumbnail_ready = Signal(object, object)
    thumbnail_failed = Signal(object, str)
    # Worker threads emit these; the GUI-thread slots below re-check the
    # generation before forwarding, so results from cancelled requests drop.
    _raw_ready = Signal(object, object, int)
    _raw_failed = Signal(object, str, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)
        self._generation = 0
        self._closed = False
        self._raw_ready.connect(self._on_raw_ready)
        self._raw_failed.connect(self._on_raw_failed)

    def is_current(self, generation: int) -> bool:
        return not self._closed and generation == self._generation

    def request(self, info: RecordingInfo) -> None:
        if self._closed:
            return
        self._pool.start(_ThumbnailTask(self, info, self._generation))

    def cancel_all(self) -> None:
        self._generation += 1
        self._pool.clear()

    def shutdown(self) -> None:
        self._closed = True
        self._pool.clear()
        self._pool.waitForDone()

    def _on_raw_ready(self, path, image, generation: int) -> None:
        if self.is_current(generation):
            self.thumbnail_ready.emit(path, image)

    def _on_raw_failed(self, path, message: str, generation: int) -> None:
        if self.is_current(generation):
            self.thumbnail_failed.emit(path, message)
