import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

import dicom_io
from viewer.session import RecordingInfo


@dataclass(frozen=True)
class Loop:
    frames: np.ndarray
    levels: tuple[float, float] | None


class FrameCache:
    def __init__(self, budget_bytes: int = 1_200_000_000) -> None:
        self._budget = budget_bytes
        self._entries: OrderedDict[Path, Loop] = OrderedDict()
        self._lock = threading.Lock()
        self._bytes = 0

    def get(self, path: Path) -> Loop | None:
        with self._lock:
            loop = self._entries.get(path)
            if loop is not None:
                self._entries.move_to_end(path)
            return loop

    def put(self, path: Path, loop: Loop) -> None:
        with self._lock:
            old = self._entries.pop(path, None)
            if old is not None:
                self._bytes -= old.frames.nbytes
            self._entries[path] = loop
            self._bytes += loop.frames.nbytes
            while self._bytes > self._budget and len(self._entries) > 1:
                _, evicted = self._entries.popitem(last=False)
                self._bytes -= evicted.frames.nbytes

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._bytes = 0

    @property
    def bytes_used(self) -> int:
        with self._lock:
            return self._bytes

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


def decode_loop(info: RecordingInfo) -> Loop:
    # Decode into one preallocated array, frame by frame, from a single read of
    # the file. Stacking a list of frames or decoding the full pixel array in
    # one go roughly doubles peak memory per loop.
    ds = dicom_io.read_dataset(info.path)
    count = dicom_io.frame_count(ds)
    first = dicom_io.pixel_frame(ds, 0)
    frames = np.empty((count, *first.shape), dtype=first.dtype)
    frames[0] = first
    del first
    for index in range(1, count):
        frames[index] = dicom_io.pixel_frame(ds, index)
    del ds
    if info.is_color:
        return Loop(frames, None)
    return Loop(frames, dicom_io.mono_levels(frames))


def decode_frame(info: RecordingInfo, index: int) -> np.ndarray:
    ds = dicom_io.read_dataset(info.path)
    return dicom_io.pixel_frame(ds, index)


class _LoopTask(QRunnable):
    def __init__(self, pool: "PrefetchPool", info: RecordingInfo, generation: int):
        super().__init__()
        self._pool = pool
        self._info = info
        self._generation = generation

    def run(self):
        pool = self._pool
        path = self._info.path
        if not pool._is_current(path, self._generation):
            return
        try:
            loop = decode_loop(self._info)
        except Exception as exc:
            pool._raw_failed.emit(
                self._info, str(exc) or type(exc).__name__, self._generation
            )
            return
        pool._raw_ready.emit(self._info, loop, self._generation)


class PrefetchPool(QObject):
    loop_ready = Signal(object, object)  # RecordingInfo, Loop
    loop_failed = Signal(object, str)
    # Worker threads emit these; the GUI-thread slots re-check the generation
    # before forwarding, so results from cancelled requests are dropped.
    _raw_ready = Signal(object, object, int)
    _raw_failed = Signal(object, str, int)

    def __init__(self, parent=None, max_workers: int = 2) -> None:
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(max_workers)
        self._lock = threading.Lock()
        self._generations: dict[Path, int] = {}
        self._in_flight: set[Path] = set()
        self._closed = False
        self._raw_ready.connect(self._on_raw_ready)
        self._raw_failed.connect(self._on_raw_failed)

    def request(self, info: RecordingInfo) -> None:
        path = info.path
        with self._lock:
            if self._closed or path in self._in_flight:
                return
            self._in_flight.add(path)
            generation = self._generations.get(path, 0)
        self._pool.start(_LoopTask(self, info, generation))

    def cancel(self, info: RecordingInfo) -> None:
        path = info.path
        with self._lock:
            self._generations[path] = self._generations.get(path, 0) + 1
            self._in_flight.discard(path)

    def shutdown(self) -> None:
        with self._lock:
            self._closed = True
        self._pool.clear()
        self._pool.waitForDone()

    def _is_current(self, path: Path, generation: int) -> bool:
        with self._lock:
            return not self._closed and self._generations.get(path, 0) == generation

    def _finish(self, info: RecordingInfo, generation: int) -> bool:
        path = info.path
        with self._lock:
            if self._closed or self._generations.get(path, 0) != generation:
                return False
            self._in_flight.discard(path)
            return True

    def _on_raw_ready(self, info, loop, generation: int) -> None:
        if self._finish(info, generation):
            self.loop_ready.emit(info, loop)

    def _on_raw_failed(self, info, message: str, generation: int) -> None:
        if self._finish(info, generation):
            self.loop_failed.emit(info, message)
