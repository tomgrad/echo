import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

import numpy as np

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
    ds = dicom_io.read_dataset(info.path)
    frames = dicom_io.pixel_frames(ds)
    if info.is_still:
        frames = frames[np.newaxis, ...]
    if info.is_color:
        return Loop(frames, None)
    return Loop(frames, dicom_io.mono_levels(frames))


def decode_frame(info: RecordingInfo, index: int) -> np.ndarray:
    ds = dicom_io.read_dataset(info.path)
    return dicom_io.pixel_frame(ds, index)
