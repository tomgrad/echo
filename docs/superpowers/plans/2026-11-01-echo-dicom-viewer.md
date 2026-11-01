# Echocardiography DICOM Viewer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the MVP review viewer: import an echo session folder, browse recordings as thumbnails, place four in a 2×2 grid, and play them with independent or wall-clock-synced cine playback.

**Architecture:** A standalone `viewer/` PySide6 package with its own Qt Designer `.ui`, backed by a shared root `dicom_io.py` also used by Echo. Playback is driven by a monotonic-seconds clock; each tile has a `Timeline` mapping time to frames, so synced/independent/custom-loop/ECG-aligned modes share one mechanism. Decoding is hybrid: thumbnails decode one frame, opened tiles prefetch their full loop in a worker under an LRU memory budget, with on-demand single-frame fallback.

**Tech Stack:** Python 3.14, PySide6 6.12, pyqtgraph 0.14, pydicom 3.0.2, numpy, pytest.

**Spec:** `docs/superpowers/specs/2026-11-01-echo-dicom-viewer-design.md`

## Global Constraints

- Run Python and pytest through the repo venv: `.venv/bin/python`, `.venv/bin/python -m pytest`.
- Generate UI code only with `.venv/bin/pyside6-uic viewer/viewer_window.ui -o viewer/ui_viewer_window.py`; never hand-edit `viewer/ui_viewer_window.py` (repo rule).
- `viewer/` and `dicom_io.py` must not import `torch`, `medseg2`, or `sam2`.
- Decode with `pydicom.pixels.pixel_array` (pydicom 3 API); do not rely on `Dataset.pixel_array` for indexed decoding.
- `data/` is a gitignored symlink; no test may depend on it. Unit tests build tiny DICOMs in `tmp_path`.
- Display frames with x=column, y=row (swap the spatial axes), matching Echo's `ImageView`.
- Commit after every task; never commit `data/`, `__pycache__`, `checkpoints/`, or `.venv`.
- The Echo GUI and its analysis behavior must not change; only `open_dicom_file` in `main.py` may be refactored in Task 1.

## Review Focus

Each line names an input or failure mode the spec implies, and the task whose tests pin it.

1. DICOM headers with missing, zero, or non-numeric `CineRate`/`NumberOfFrames`, or no `RecommendedDisplayFrameRate`/`FrameTime` — display must still work with fps 30 and one frame. Pinned in Task 1.
2. A session folder containing non-DICOM files and a corrupt `.dcm` — scanning must skip the former, surface the latter, and never crash. Pinned in Task 2.
3. Monochrome 16-bit and single-frame recordings — correct shape, geometry, stable levels, no crash. Pinned in Task 1 (levels, display axes for multi-frame mono), Task 3 (mono still decode), Task 7 (viewport, stable levels).
4. Opening an empty folder, or a scan failing while a session is open — the previous session stays visible and the reason is reported. Pinned in Task 2 (empty scan) and Task 6 (window keeps previous session).
5. Four loaded 93-frame loops — cache eviction keeps decoded memory bounded and the UI stays responsive. Pinned in Task 3 (eviction) and Task 8 (manual acceptance).
6. Echo opening a monochrome multi-frame file — the shared display swap must give the same axes as before the refactor. Pinned in Task 1 (`display_array` tests).
7. Synced-playback logic (longest-visible period, hold at end, loop on/off, hidden tiles, scrub, sync re-base) — pinned in Task 4 with fake viewports.
8. The same recording shown in two tiles, or a tile reassigned while another tile shows the same recording — prefetch must not be cancelled for the surviving tile. Pinned in Task 7 (`PrefetchPool` tests, assignment rules).
9. Image rows whose byte width is not a multiple of 4 — pinned in Task 6 (stride test).

---

### Task 1: Shared DICOM core and Echo refactor

**Files:**
- Create: `dicom_io.py`
- Create: `tests/conftest.py`
- Create: `tests/test_dicom_io.py`
- Modify: `main.py:8` and `main.py:1427-1465` (`open_dicom_file`)

**Interfaces:**
- Produces:
  - `DEFAULT_FPS: float = 30.0`
  - `read_header(path: str | Path) -> pydicom.Dataset`
  - `read_dataset(path: str | Path) -> pydicom.Dataset`
  - `frame_count(ds: pydicom.Dataset) -> int`
  - `fps(ds: pydicom.Dataset) -> float`
  - `is_color(ds: pydicom.Dataset) -> bool`
  - `is_still(ds: pydicom.Dataset) -> bool`
  - `pixel_frames(ds: pydicom.Dataset) -> np.ndarray`
  - `pixel_frame(ds: pydicom.Dataset, index: int) -> np.ndarray`
  - `display_array(arr: np.ndarray, color: bool) -> np.ndarray`
  - `mono_levels(frames: np.ndarray) -> tuple[float, float]`

- [ ] **Step 1: Write the synthetic DICOM fixture**

Create `tests/conftest.py`. This fixture is used by every later task, so it must produce both RGB and monochrome multi-frame files that pydicom can decode.

```python
import numpy as np
import pytest
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import (
    ExplicitVRLittleEndian,
    UltrasoundMultiFrameImageStorage,
    generate_uid,
)


@pytest.fixture
def write_dicom(tmp_path):
    def _write(
        name="rec.dcm",
        *,
        frames=3,
        rows=8,
        cols=10,
        color=False,
        fps=25.0,
        frame_time=None,
        instance=1,
        dt="20260101120000.000",
        study_uid=None,
        series_uid=None,
        study_description="",
        series_description="",
        heart_rate=60,
        **extra,
    ):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        ds = Dataset()
        ds.file_meta = FileMetaDataset()
        ds.file_meta.MediaStorageSOPClassUID = UltrasoundMultiFrameImageStorage
        ds.file_meta.MediaStorageSOPInstanceUID = generate_uid()
        ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        ds.SOPClassUID = UltrasoundMultiFrameImageStorage
        ds.SOPInstanceUID = ds.file_meta.MediaStorageSOPInstanceUID
        ds.Modality = "US"
        ds.PatientName = "Test^Patient"
        ds.PatientID = "1"
        ds.StudyInstanceUID = study_uid or generate_uid()
        ds.SeriesInstanceUID = series_uid or generate_uid()
        ds.StudyDate = "20260101"
        ds.StudyDescription = study_description
        ds.SeriesDescription = series_description
        ds.AcquisitionDateTime = dt
        ds.InstanceNumber = instance
        ds.HeartRate = heart_rate
        ds.Rows = rows
        ds.Columns = cols
        ds.NumberOfFrames = frames
        if fps is not None:
            ds.CineRate = str(int(fps))
        if frame_time is not None:
            ds.FrameTime = frame_time
        if color:
            ds.SamplesPerPixel = 3
            ds.PhotometricInterpretation = "RGB"
            ds.PlanarConfiguration = 0
            arr = np.zeros((frames, rows, cols, 3), dtype=np.uint8)
            arr[..., 1] = 128
        else:
            ds.SamplesPerPixel = 1
            ds.PhotometricInterpretation = "MONOCHROME2"
            arr = np.arange(frames * rows * cols, dtype=np.uint16).reshape(
                frames, rows, cols
            )
        ds.BitsAllocated = 8 if color else 16
        ds.BitsStored = 8 if color else 12
        ds.HighBit = 7 if color else 11
        ds.PixelRepresentation = 0
        ds.PixelData = arr.tobytes()
        for key, value in extra.items():
            setattr(ds, key, value)
        ds.save_as(path, enforce_file_format=True)
        return path, arr

    return _write
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_dicom_io.py`:

```python
import numpy as np
import pytest
from pydicom.dataset import Dataset

import dicom_io


def test_metadata_fallbacks():
    ds = Dataset()
    assert dicom_io.frame_count(ds) == 1
    assert dicom_io.is_still(ds)
    assert not dicom_io.is_color(ds)
    assert dicom_io.fps(ds) == 30.0

    ds.CineRate = "0"
    assert dicom_io.fps(ds) == 30.0

    ds.RecommendedDisplayFrameRate = 20
    assert dicom_io.fps(ds) == 20.0

    del ds.RecommendedDisplayFrameRate
    ds.FrameTime = 40.0
    assert dicom_io.fps(ds) == 25.0

    ds.SamplesPerPixel = 3
    assert dicom_io.is_color(ds)


def test_pixel_frames_and_single_frame(write_dicom):
    path, arr = write_dicom("rgb.dcm", frames=3, color=True)
    ds = dicom_io.read_dataset(path)
    frames = dicom_io.pixel_frames(ds)
    assert frames.shape == (3, 8, 10, 3)
    assert np.array_equal(dicom_io.pixel_frame(ds, 1), arr[1])


def test_monochrome_pixel_frames(write_dicom):
    path, arr = write_dicom("mono.dcm", frames=2, color=False)
    ds = dicom_io.read_dataset(path)
    frames = dicom_io.pixel_frames(ds)
    assert frames.shape == (2, 8, 10)
    assert np.array_equal(dicom_io.pixel_frame(ds, 0), arr[0])


def test_frame_count_tolerates_bad_values():
    ds = Dataset()
    ds.NumberOfFrames = "abc"
    assert dicom_io.frame_count(ds) == 1
    ds.NumberOfFrames = "0"
    assert dicom_io.frame_count(ds) == 1
    ds.NumberOfFrames = "7"
    assert dicom_io.frame_count(ds) == 7


def test_display_array_swaps_spatial_axes():
    # Same axes Echo used before the refactor: color swaps -3,-2; mono swaps -2,-1.
    assert dicom_io.display_array(np.zeros((8, 10)), False).shape == (10, 8)
    assert dicom_io.display_array(np.zeros((3, 8, 10)), False).shape == (3, 10, 8)
    assert dicom_io.display_array(np.zeros((8, 10, 3)), True).shape == (10, 8, 3)
    assert dicom_io.display_array(np.zeros((4, 8, 10, 3)), True).shape == (4, 10, 8, 3)


def test_mono_levels_are_percentiles():
    frames = np.arange(100, dtype=np.uint16).reshape(2, 5, 10)
    low, high = dicom_io.mono_levels(frames)
    assert low == pytest.approx(0.99)
    assert high == pytest.approx(98.01)


def test_mono_levels_expand_constant_frames():
    low, high = dicom_io.mono_levels(np.full((2, 4, 4), 7, dtype=np.uint16))
    assert high > low
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_dicom_io.py -v`

Expected: collection fails with `ModuleNotFoundError: No module named 'dicom_io'`.

- [ ] **Step 4: Implement `dicom_io.py`**

Behavior to implement exactly:

- `read_header`: `pydicom.dcmread(path, stop_before_pixels=True)`.
- `read_dataset`: `pydicom.dcmread(path)`.
- `frame_count`: `int(ds.get("NumberOfFrames", 1) or 1)`, minimum 1; a value that
  cannot be converted (`ValueError`/`TypeError`) returns 1.
- `fps`: take the first positive number from `CineRate`, `RecommendedDisplayFrameRate`,
  `1000 / FrameTime` (FrameTime is milliseconds), else `DEFAULT_FPS`. Non-numeric
  or non-positive values are skipped, not raised.
- `is_color`: `int(ds.get("SamplesPerPixel", 1) or 1) > 1`.
- `is_still`: `frame_count(ds) == 1`.
- `pixel_frames`: `pydicom.pixels.pixel_array(ds)` (import from `pydicom.pixels`,
  not the `ds.pixel_array` property).
- `pixel_frame`: `pydicom.pixels.pixel_array(ds, index=index)`; when
  `frame_count(ds) == 1`, return `pixel_frames(ds)` (some decoders only
  accept an index for multi-frame objects).
- `display_array(arr, color)`: swap the two spatial axes exactly as Echo did:
  `np.swapaxes(arr, -3, -2)` when `color`, else `np.swapaxes(arr, -2, -1)`.
  The flag is required because a 3D array is `(rows, cols, 3)` for a color
  frame but `(frames, rows, cols)` for monochrome.
- `mono_levels`: monochrome only. A 3D array is `(frames, rows, cols)` and a
  2D array is one frame. Sample at most 16 evenly spaced frames when there is
  a frame axis, then return 1st/99th percentiles as floats; if `high <= low`,
  set `high = low + 1.0`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_dicom_io.py -v`

Expected: 7 passed.

- [ ] **Step 6: Refactor Echo's `open_dicom_file`**

In `main.py`, replace `import pydicom` with `import dicom_io`, and inside
`open_dicom_file` make exactly these substitutions:

```python
dicom = dicom_io.read_dataset(dicom_file_path)
pixel_array = dicom_io.pixel_frames(dicom)
...
self.is_color = dicom_io.is_color(dicom)
...
display_array = dicom_io.display_array(self.pixel_array, self.is_color)
```

Delete only the old `if self.is_color: display_array = np.swapaxes(...) else: ...`
block (the new call replaces it). Leave the `FRAMES_LIMIT` slice untouched.
No other Echo change.

- [ ] **Step 7: Verify Echo still loads the real file**

Run:

```bash
.venv/bin/python -m py_compile main.py
.venv/bin/python -c "import main; print('main imports')"
.venv/bin/python - <<'EOF'
import dicom_io
ds = dicom_io.read_dataset("data/series-00000/image-00000.dcm")
assert dicom_io.frame_count(ds) == 93
assert dicom_io.is_color(ds)
assert dicom_io.display_array(dicom_io.pixel_frame(ds, 0), True).shape == (1016, 708, 3)
print("real DICOM ok")
EOF
```

Expected: `main imports` and `real DICOM ok`, no traceback. Then launch
`.venv/bin/python main.py`, open `data/series-00000/image-00000.dcm`, and
confirm the image and 93-frame timeline appear. Close Echo.

- [ ] **Step 8: Commit**

```bash
git add dicom_io.py main.py tests/conftest.py tests/test_dicom_io.py
git commit -m "feat: add shared DICOM reading core"
```

---

### Task 2: Session scanning and recording metadata

**Files:**
- Create: `viewer/__init__.py` (empty)
- Create: `viewer/session.py`
- Create: `tests/test_session.py`

**Interfaces:**
- Consumes: `dicom_io.read_header`, `frame_count`, `fps`, `is_color`, `is_still`
- Produces:

```python
@dataclass(frozen=True)
class RecordingInfo:
    path: Path
    instance_number: int
    sop_instance_uid: str
    frames: int
    rows: int
    cols: int
    fps: float
    is_color: bool
    is_still: bool
    study_uid: str
    series_uid: str
    study_description: str
    series_description: str
    patient_name: str
    patient_id: str
    study_date: str
    acquisition_datetime: str
    heart_rate: int | None
    error: str | None = None

    @property
    def duration_s(self) -> float: ...

@dataclass(frozen=True)
class Session:
    folder: Path
    study_label: str
    recordings: tuple[RecordingInfo, ...]

def scan_session(folder: str | Path) -> Session: ...
def recording_label(info: RecordingInfo, index: int) -> str: ...
```

- [ ] **Step 1: Write the failing tests**

Create `tests/test_session.py`:

```python
import pytest

from viewer.session import recording_label, scan_session


def test_scan_orders_by_instance_and_reads_metadata(write_dicom, tmp_path):
    write_dicom("b.dcm", instance=2, dt="20260101120100.000")
    write_dicom("a.dcm", instance=1, dt="20260101120000.000")
    session = scan_session(tmp_path)
    assert [r.instance_number for r in session.recordings] == [1, 2]
    first = session.recordings[0]
    assert first.frames == 3
    assert first.fps == 25.0
    assert first.rows == 8 and first.cols == 10
    assert first.duration_s == pytest.approx(0.12)
    assert first.heart_rate == 60


def test_scan_is_recursive_and_skips_non_dicom(write_dicom, tmp_path):
    write_dicom("nested/rec.dcm", instance=1)
    (tmp_path / "notes.txt").write_text("not a study")
    session = scan_session(tmp_path)
    assert len(session.recordings) == 1
    assert session.recordings[0].path == (tmp_path / "nested/rec.dcm").resolve()


def test_corrupt_dcm_is_reported_not_skipped(tmp_path):
    (tmp_path / "bad.dcm").write_text("not a dicom")
    session = scan_session(tmp_path)
    assert len(session.recordings) == 1
    assert session.recordings[0].error
    assert recording_label(session.recordings[0], 1) == "REC 01 · error"


def test_empty_folder_returns_empty_session(tmp_path):
    session = scan_session(tmp_path)
    assert session.recordings == ()
    assert session.study_label == tmp_path.name


def test_study_label_prefers_description(write_dicom, tmp_path):
    write_dicom("rec.dcm", study_description="TTE Study")
    assert scan_session(tmp_path).study_label == "TTE Study"


def test_recording_label_format(write_dicom, tmp_path):
    write_dicom("rec.dcm", dt="20260101120000.000")
    info = scan_session(tmp_path).recordings[0]
    assert recording_label(info, 1) == (
        "REC 01 · inst 1 · 3f · 25 fps · 0.12s · 12:00:00"
    )


def test_still_label(write_dicom, tmp_path):
    write_dicom("still.dcm", frames=1, instance=2)
    info = scan_session(tmp_path).recordings[0]
    assert recording_label(info, 1) == (
        "REC 01 · inst 2 · 1f · 25 fps · 0.04s · 12:00:00 · STILL"
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_session.py -v`

Expected: fails with `ModuleNotFoundError: No module named 'viewer'`.

- [ ] **Step 3: Implement `viewer/session.py`**

Key rules:

- Resolve the folder and every path with `.resolve()`.
- Iterate `sorted(folder.rglob("*"))`; skip directories.
- Try `dicom_io.read_header(path)`. On `pydicom.errors.InvalidDicomError`:
  skip the file when its suffix is not `.dcm` (case-insensitive); otherwise add
  an error `RecordingInfo`. On any other exception apply the same suffix rule.
- A valid dataset produces `RecordingInfo` with `int(ds.get("InstanceNumber", 0) or 0)`,
  UIDs as `str(ds.get(tag, ""))`, `rows`/`cols`/`frames`/`fps`/`is_color`/
  `is_still` from `dicom_io`, `heart_rate = int(ds.HeartRate)` when present,
  and `acquisition_datetime = str(ds.get("AcquisitionDateTime", ""))`.
- Sort by `(instance_number, acquisition_datetime, path.name)`.
- `study_label` = first non-empty `study_description` among non-error
  recordings, else `folder.name`.
- `recording_label(info, index)`: for errors return
  `f"REC {index:02d} · error"`. Otherwise
  `f"REC {index:02d} · inst {info.instance_number} · {info.frames}f · {info.fps:g} fps · {info.duration_s:.2f}s · {clock}"`,
  where `clock` is `HH:MM:SS` from characters 8–14 of
  `acquisition_datetime`, or `--:--:--` when it is shorter. Append
  `" · STILL"` when `info.is_still`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_session.py -v`

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add viewer/__init__.py viewer/session.py tests/test_session.py
git commit -m "feat: scan echo sessions into recording metadata"
```

---

### Task 3: Frame decoding and LRU cache

**Files:**
- Create: `viewer/frames.py`
- Create: `tests/test_frames.py`

**Interfaces:**
- Consumes: `RecordingInfo`, `dicom_io.pixel_frames`, `pixel_frame`, `mono_levels`
- Produces:

```python
@dataclass(frozen=True)
class Loop:
    frames: np.ndarray
    levels: tuple[float, float] | None

class FrameCache:
    def __init__(self, budget_bytes: int = 1_200_000_000) -> None: ...
    def get(self, path: Path) -> Loop | None: ...
    def put(self, path: Path, loop: Loop) -> None: ...
    def clear(self) -> None: ...
    @property
    def bytes_used(self) -> int: ...
    def __len__(self) -> int: ...

def decode_loop(info: RecordingInfo) -> Loop: ...
def decode_frame(info: RecordingInfo, index: int) -> np.ndarray: ...
```

- [ ] **Step 1: Write the failing tests**

Create `tests/test_frames.py`:

```python
from pathlib import Path

import numpy as np
import pytest

from viewer.frames import FrameCache, Loop, decode_frame, decode_loop
from viewer.session import scan_session


def _info(write_dicom, **kwargs):
    path, arr = write_dicom("rec.dcm", **kwargs)
    return scan_session(path.parent).recordings[0], arr


def test_decode_color_loop(write_dicom):
    info, arr = _info(write_dicom, frames=3, color=True)
    loop = decode_loop(info)
    assert loop.frames.shape == (3, 8, 10, 3)
    assert loop.levels is None
    assert np.array_equal(loop.frames, arr)


def test_decode_monochrome_loop_has_levels(write_dicom):
    info, arr = _info(write_dicom, frames=3, color=False)
    loop = decode_loop(info)
    assert loop.frames.shape == (3, 8, 10)
    low, high = loop.levels
    assert low < high


def test_decode_single_frame(write_dicom):
    info, arr = _info(write_dicom, frames=4, color=True)
    assert np.array_equal(decode_frame(info, 2), arr[2])


def test_decode_still_loop_has_frame_axis(write_dicom):
    info, arr = _info(write_dicom, frames=1, color=True)
    loop = decode_loop(info)
    assert loop.frames.shape == (1, 8, 10, 3)


def test_decode_monochrome_still_has_frame_axis_and_levels(write_dicom):
    info, arr = _info(write_dicom, frames=1, color=False)
    loop = decode_loop(info)
    assert loop.frames.shape == (1, 8, 10)
    assert np.array_equal(decode_frame(info, 0), arr[0])
    low, high = loop.levels
    assert low < high


def test_cache_evicts_least_recently_used():
    cache = FrameCache(budget_bytes=120)
    a = Loop(np.zeros(50, dtype=np.uint8), None)
    b = Loop(np.zeros(50, dtype=np.uint8), None)
    c = Loop(np.zeros(50, dtype=np.uint8), None)
    cache.put(Path("a"), a)
    cache.put(Path("b"), b)
    assert cache.get(Path("a")) is a
    cache.put(Path("c"), c)
    assert cache.get(Path("b")) is None
    assert cache.get(Path("a")) is a
    assert cache.bytes_used == 100


def test_cache_replaces_same_path():
    cache = FrameCache(budget_bytes=1000)
    first = Loop(np.zeros(10, dtype=np.uint8), None)
    second = Loop(np.zeros(20, dtype=np.uint8), None)
    cache.put(Path("a"), first)
    cache.put(Path("a"), second)
    assert cache.get(Path("a")) is second
    assert cache.bytes_used == 20
    assert len(cache) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_frames.py -v`

Expected: fails with `ModuleNotFoundError: No module named 'viewer.frames'`.

- [ ] **Step 3: Implement `viewer/frames.py`**

- `Loop.frames` is the decoded array; `levels` is `None` for color and
  `dicom_io.mono_levels(frames)` for monochrome.
- `decode_loop` reads the dataset once, decodes all frames, computes levels,
  and returns; the dataset goes out of scope (its `PixelData` is released).
  For single-frame recordings pydicom returns no frame axis, so normalize
  with `frames = frames[np.newaxis, ...]` before building the `Loop`.
- `decode_frame` reads the dataset and returns `dicom_io.pixel_frame(ds, index)`.
  For single-frame recordings, index 0 must work.
- `FrameCache` uses `collections.OrderedDict` plus a `threading.Lock`.
  `put` replaces an existing key, moves it to the end, and evicts from the
  front while `bytes_used > budget_bytes` and more than one entry remains.
  `get` moves a hit to the end. `bytes_used` sums `loop.frames.nbytes`.
  A single entry larger than the budget is still stored.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_frames.py -v`

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add viewer/frames.py tests/test_frames.py
git commit -m "feat: add frame decoding and bounded loop cache"
```

---

### Task 4: Timeline, clock, and playback controller

**Files:**
- Create: `viewer/playback.py`
- Create: `tests/test_playback.py`

**Interfaces:**
- Consumes: `RecordingInfo`
- Produces:

```python
@dataclass
class Timeline:
    frame_count: int
    fps: float
    loop_start: int = 0
    loop_end: int = -1
    offset_s: float = 0.0

    @property
    def loop_duration_s(self) -> float: ...
    def frame_at(self, t: float) -> int: ...

class PlaybackClock(QObject):
    position_changed = Signal(float)
    def __init__(self, parent=None, interval_ms: int = 16) -> None: ...
    def play(self) -> None: ...
    def pause(self) -> None: ...
    @property
    def is_playing(self) -> bool: ...
    @property
    def position_s(self) -> float: ...
    def set_position_s(self, t: float) -> None: ...

class PlaybackController(QObject):
    state_changed = Signal(bool)  # True while playing
    def __init__(self, parent=None) -> None: ...
    def add_viewport(self, viewport) -> None: ...
    def set_synced(self, synced: bool) -> None: ...
    def set_loop(self, enabled: bool) -> None: ...
    def play(self) -> None: ...
    def pause(self) -> None: ...
    def restart(self) -> None: ...
    def scrub(self, viewport, frame_index: int) -> None: ...
    def show_current(self) -> None: ...
    def _on_shared_tick(self, t: float) -> None: ...  # connected to shared_clock.position_changed
    shared_clock: PlaybackClock   # public attribute
    @property
    def synced(self) -> bool: ...
    @property
    def loop_enabled(self) -> bool: ...
    @property
    def is_playing(self) -> bool: ...
```

Viewport contract consumed by `PlaybackController` (implemented in Task 7):
`viewport.recording: RecordingInfo | None`, `viewport.timeline: Timeline | None`,
`viewport.show_time(t: float, hold_at_end: bool) -> None`,
`viewport.scrub_requested` signal `(object, int)`, `viewport.isHidden() -> bool`.

- [ ] **Step 1: Write the failing timeline and controller tests**

Create `tests/test_playback.py`:

```python
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from viewer.playback import PlaybackController, Timeline  # noqa: E402


class FakeViewport(QObject):
    scrub_requested = Signal(object, int)

    def __init__(self, frames, fps, *, still=False, hidden=False):
        super().__init__()
        self.recording = SimpleNamespace(frames=frames, fps=fps, is_still=still)
        self.timeline = Timeline(frame_count=frames, fps=fps)
        self.hidden = hidden
        self.calls = []

    def isHidden(self):
        return self.hidden

    def show_time(self, t, hold_at_end):
        self.calls.append((t, hold_at_end))


@pytest.fixture
def controller():
    QApplication.instance() or QApplication([])
    ctrl = PlaybackController()
    yield ctrl
    ctrl.pause()


def _viewports(controller):
    long = FakeViewport(10, 10)  # 1.0 s
    short = FakeViewport(5, 10)  # 0.5 s
    still = FakeViewport(1, 30, still=True)
    hidden = FakeViewport(20, 10, hidden=True)  # 2.0 s, must not set the period
    for viewport in (long, short, still, hidden):
        controller.add_viewport(viewport)
        viewport.calls.clear()
    return long, short, still, hidden


def test_wraps_at_loop_duration():
    timeline = Timeline(frame_count=10, fps=10)
    assert timeline.frame_at(0.0) == 0
    assert timeline.frame_at(0.35) == 3
    assert timeline.frame_at(0.99) == 9
    assert timeline.frame_at(1.0) == 0


def test_loop_range_and_offset():
    timeline = Timeline(
        frame_count=10, fps=10, loop_start=2, loop_end=5, offset_s=0.5
    )
    assert timeline.loop_duration_s == pytest.approx(0.4)
    assert timeline.frame_at(0.5) == 2
    assert timeline.frame_at(0.85) == 5
    assert timeline.frame_at(0.95) == 2


def test_still_recording_always_frame_zero():
    assert Timeline(frame_count=1, fps=30).frame_at(2.5) == 0


def test_defaults_and_clamping():
    timeline = Timeline(frame_count=10, fps=10)
    assert timeline.loop_start == 0
    assert timeline.loop_end == 9
    clamped = Timeline(frame_count=5, fps=10, loop_start=-3, loop_end=99)
    assert clamped.loop_start == 0
    assert clamped.loop_end == 4


def test_rejects_non_positive_fps():
    with pytest.raises(ValueError):
        Timeline(frame_count=5, fps=0)


def test_synced_tick_holds_short_tile_and_skips_hidden(controller):
    long, short, still, hidden = _viewports(controller)
    controller.play()
    controller._on_shared_tick(0.7)
    assert long.calls[-1] == (0.7, True)
    assert short.calls[-1] == (0.7, True)  # 0.5 s tile holds its last frame
    assert still.calls[-1] == (0.7, True)
    assert hidden.calls == []
    assert controller.is_playing


def test_synced_loop_restarts_at_longest_visible_period(controller):
    long, short, *_ = _viewports(controller)
    controller.play()
    controller._on_shared_tick(1.0)  # hidden 2 s tile is ignored
    assert controller.shared_clock.position_s == pytest.approx(0.0, abs=0.05)
    assert long.calls[-1] == (0.0, True)
    assert short.calls[-1] == (0.0, True)
    assert controller.is_playing


def test_synced_without_loop_pauses_at_period(controller):
    long, *_ = _viewports(controller)
    states = []
    controller.state_changed.connect(states.append)
    controller.set_loop(False)
    controller.play()
    controller._on_shared_tick(1.2)
    assert not controller.is_playing
    assert states[-1] is False
    assert long.calls[-1] == (pytest.approx(1.0), True)
    assert controller.shared_clock.position_s == pytest.approx(1.0)


def test_synced_scrub_moves_all_visible_tiles(controller):
    long, short, still, hidden = _viewports(controller)
    controller.scrub(long, 5)
    assert controller.shared_clock.position_s == pytest.approx(0.5)
    assert short.calls[-1] == (pytest.approx(0.5), True)
    assert hidden.calls == []


def test_independent_scrub_moves_only_that_tile(controller):
    long, short, *_ = _viewports(controller)
    controller.set_synced(False)
    long.calls.clear()
    short.calls.clear()
    controller.scrub(long, 5)
    assert long.calls[-1] == (pytest.approx(0.5), False)
    assert short.calls == []


def test_toggling_sync_rebases_to_zero(controller):
    long, short, *_ = _viewports(controller)
    controller.scrub(long, 5)
    controller.set_synced(False)
    assert long.calls[-1] == (0.0, False)
    assert short.calls[-1] == (0.0, False)
    controller.set_synced(True)
    assert controller.shared_clock.position_s == pytest.approx(0.0, abs=0.05)
    assert long.calls[-1] == (0.0, True)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_playback.py -v`

Expected: fails with `ModuleNotFoundError: No module named 'viewer.playback'`.

- [ ] **Step 3: Implement `Timeline` and `PlaybackClock`**

`Timeline` rules:

- `__post_init__` raises `ValueError` when `fps <= 0`, clamps `loop_start`
  to `0..frame_count-1` and `loop_end` to `loop_start..frame_count-1`;
  `loop_end == -1` resolves to `frame_count - 1`.
- `loop_duration_s = (loop_end - loop_start + 1) / fps`.
- `frame_at(t)`: for `frame_count <= 1` return 0; otherwise
  `local = (t - offset_s) % loop_duration_s`,
  `index = loop_start + floor(local * fps)`, clamped to
  `loop_start..loop_end`.

`PlaybackClock` rules:

- One `QTimer` with `interval_ms` (default 16, about 60 Hz).
- `position_s` advances by `time.monotonic()` deltas while playing; it never
  counts ticks. `play` sets the last timestamp and starts the timer; `pause`
  stops it; each tick emits `position_changed(position_s)`.
- `set_position_s` updates the position and last timestamp without emitting.
  Callers that need a repaint call `show_current`.

- [ ] **Step 4: Implement `PlaybackController`**

- The controller starts synced with looping on. It owns a public
  `self.shared_clock = PlaybackClock(self)` whose `position_changed` is
  connected to `self._on_shared_tick`.
- `add_viewport` registers the viewport, creates a private `PlaybackClock`
  for independent mode, connects its `position_changed` to
  `lambda t, v=viewport: v.show_time(t, hold_at_end=False)`, and connects
  `viewport.scrub_requested` to `self.scrub`.
- `set_synced(True)`: remember playing state, pause, reset the shared clock to
  0, show time 0 on every viewport with `hold_at_end=True`, resume if it was
  playing. `set_synced(False)`: same but reset each private clock and show
  time 0 with `hold_at_end=False`.
- `_on_shared_tick(t)`: if synced, compute
  `period = max(v.timeline.loop_duration_s for visible v with a recording and not v.recording.is_still, default=0)`.
  When `t >= period > 0`: if looping, reset the shared clock to 0 and apply
  time 0 to all viewports; otherwise set the shared position to `period`,
  show `period` with `hold_at_end=True` on visible viewports, and pause. Otherwise call
  `v.show_time(t, hold_at_end=True)` for every visible viewport with a
  recording. Hidden viewports are skipped (1×1 layout).
- `play`: if synced and not looping and the position is at/after the period,
  reset to 0 first; then start the shared clock or every private clock.
- `scrub(viewport, index)`: time = `index / timeline.fps`. If synced, set the
  shared time and call `show_current`; otherwise set that viewport's private
  clock and call its `show_time(time, hold_at_end=False)`.
- `show_current`: synced uses the shared position; independent applies each
  private clock's position to its viewport.
- `restart`: pause, set the shared and private positions to 0, call
  `show_current`, and emit `state_changed(False)`.
- `play` and `pause` emit `state_changed(self._playing)` at the end; the
  shared clock tick also emits `state_changed(False)` when it auto-pauses at
  the end with looping disabled.
- `set_loop` only stores the flag; the synced tick handles it. Independent
  playback always loops each tile; the flag does not apply there.

- [ ] **Step 5: Run playback tests**

Run: `.venv/bin/python -m pytest tests/test_playback.py -v`

Expected: 11 passed (5 timeline, 6 controller).

- [ ] **Step 6: Commit**

```bash
git add viewer/playback.py tests/test_playback.py
git commit -m "feat: add wall-clock playback timeline and controller"
```

---

### Task 5: Viewer package, Designer UI, and window shell

**Files:**
- Create: `viewer/viewer_window.ui`
- Create: `viewer/ui_viewer_window.py` (generated only)
- Create: `viewer/main_window.py`
- Create: `viewer/__main__.py`
- Create: `tests/test_viewer_smoke.py`
- Modify: `.vscode/tasks.json` (tracked); `.zed/tasks.json` locally only (`.zed` is gitignored and untracked, so never `git add` it)

**Interfaces:**
- Produces: `ViewerWindow(QMainWindow, Ui_ViewerWindow)` with these widgets:
  `openSessionButton`, `layoutCombo`, `playButton`, `stopButton`,
  `syncCheckBox`, `loopCheckBox`, `sessionLabel`, `thumbnailList`,
  `gridContainer`, `gridLayout`, and the `statusbar` from `QMainWindow`.

- [ ] **Step 1: Write the failing smoke test**

Create `tests/test_viewer_smoke.py`:

```python
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from viewer.main_window import ViewerWindow  # noqa: E402


def test_viewer_window_constructs():
    app = QApplication.instance() or QApplication([])
    window = ViewerWindow()
    assert window.windowTitle() == "Echo Viewer"
    assert window.gridContainer.objectName() == "gridContainer"
    assert window.layoutCombo.count() == 2
    window.close()
    app.processEvents()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_viewer_smoke.py -v`

Expected: fails with `ModuleNotFoundError: No module named 'viewer.main_window'`.

- [ ] **Step 3: Create `viewer/viewer_window.ui`**

Widget tree (names are the contract):

```
QMainWindow "ViewerWindow" (title "Echo Viewer", 1280x800)
  centralwidget QWidget
    QVBoxLayout (margins 0, spacing 0)
      toolbarFrame QFrame
        QHBoxLayout
          openSessionButton QPushButton ("Open session")
          layoutCombo QComboBox (items "1×1", "2×2"; current index 1)
          playButton QPushButton ("Play")
          stopButton QPushButton ("Stop")
          syncCheckBox QCheckBox ("Sync", checked)
          loopCheckBox QCheckBox ("Loop", checked)
          stretch spacer
      bodyWidget QWidget
        QHBoxLayout
          leftPanel QFrame (minimumWidth 220, maximumWidth 260)
            QVBoxLayout
              sessionLabel QLabel ("No session")
              thumbnailList QListWidget
                viewMode IconMode, resizeMode Adjust, iconSize 180x120,
                gridSize 200x170, wordWrap True, uniformItemSizes True
          gridContainer QWidget
            gridLayout QGridLayout (margins 4, spacing 4)
  statusbar QStatusBar
```

`thumbnailList` and `gridContainer` must keep those object names; the window
assigns viewports into `gridLayout` in code.

- [ ] **Step 4: Generate the UI module**

Run: `.venv/bin/pyside6-uic viewer/viewer_window.ui -o viewer/ui_viewer_window.py`

Expected: the file exists and starts with `# -*- coding: utf-8 -*-`; do not
edit it.

Add two tasks to `.vscode/tasks.json` (committed) and to `.zed/tasks.json`
(local edit, not committed):
`designer viewer` runs `.venv/bin/pyside6-designer viewer/viewer_window.ui`,
`generate viewer` runs `.venv/bin/pyside6-uic viewer/viewer_window.ui -o viewer/ui_viewer_window.py`.

- [ ] **Step 5: Implement `viewer/main_window.py` and `viewer/__main__.py`**

`main_window.py` for this task:

```python
from PySide6.QtWidgets import QMainWindow

from viewer.ui_viewer_window import Ui_ViewerWindow


class ViewerWindow(QMainWindow, Ui_ViewerWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
```

`__main__.py`:

```python
import sys

from PySide6.QtWidgets import QApplication

from viewer.main_window import ViewerWindow


def main() -> int:
    app = QApplication(sys.argv)
    window = ViewerWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: Run the smoke test and launch the shell**

Run: `.venv/bin/python -m pytest tests/test_viewer_smoke.py -v`

Expected: 1 passed.

Run: `.venv/bin/python -m viewer`

Expected: window titled "Echo Viewer" with toolbar, empty rail, empty grid,
status bar. Close it.

- [ ] **Step 7: Commit**

```bash
git add viewer/viewer_window.ui viewer/ui_viewer_window.py viewer/main_window.py \
  viewer/__main__.py tests/test_viewer_smoke.py .vscode/tasks.json
git commit -m "feat: add viewer window shell and Designer UI"
```

---

### Task 6: Session import and thumbnail rail

**Files:**
- Create: `viewer/thumbnails.py`
- Create: `tests/test_thumbnails.py`
- Create: `tests/test_viewer_session.py`
- Modify: `viewer/main_window.py`

**Interfaces:**
- Consumes: `scan_session`, `RecordingInfo`, `recording_label`, `decode_frame`,
  `mono_levels`
- Produces:
  - `qimage_from_frame(frame: np.ndarray, levels: tuple[float, float] | None) -> QImage`
  - `thumbnail_qimage(frame: np.ndarray, levels, width: int = 180) -> QImage`
  - `ThumbnailProvider(QObject)` with
    `thumbnail_ready = Signal(object, object)` (path, QImage) and
    `thumbnail_failed = Signal(object, str)`; `request(info: RecordingInfo) -> None`.
  - `ViewerWindow.open_session() -> None` (button handler),
    `ViewerWindow.load_session(session: Session) -> None`,
    `ViewerWindow.session: Session | None`, `ViewerWindow._items_by_path`,
    `ViewerWindow._on_scan_succeeded(session: Session)`,
    `ViewerWindow._on_scan_failed(message: str)`.

- [ ] **Step 1: Write the failing image-conversion tests**

Create `tests/test_thumbnails.py`:

```python
import numpy as np
from PySide6.QtGui import QImage

from viewer.thumbnails import qimage_from_frame, thumbnail_qimage


def test_color_qimage_geometry_and_format():
    frame = np.zeros((8, 10, 3), dtype=np.uint8)
    image = qimage_from_frame(frame, None)
    assert image.format() == QImage.Format_RGB888
    assert (image.width(), image.height()) == (10, 8)


def test_mono_qimage_maps_levels_to_full_range():
    frame = np.array([[0, 100]], dtype=np.uint16)
    image = qimage_from_frame(frame, (0.0, 100.0))
    assert image.format() == QImage.Format_Grayscale8
    assert image.pixelColor(0, 0).red() == 0
    assert image.pixelColor(1, 0).red() == 255


def test_qimage_respects_row_stride_for_unaligned_widths():
    # Width 5: 15 bytes per RGB row and 5 per gray row, neither a multiple of 4.
    color = np.zeros((2, 5, 3), dtype=np.uint8)
    color[1, 0] = (10, 20, 30)
    pixel = qimage_from_frame(color, None).pixelColor(0, 1)
    assert (pixel.red(), pixel.green(), pixel.blue()) == (10, 20, 30)

    mono = np.zeros((2, 5), dtype=np.uint16)
    mono[1, 0] = 100
    image = qimage_from_frame(mono, (0.0, 100.0))
    assert image.pixelColor(0, 1).red() == 255
    assert image.pixelColor(4, 0).red() == 0


def test_thumbnail_scales_to_requested_width():
    image = thumbnail_qimage(np.zeros((100, 200, 3), dtype=np.uint8), None, width=50)
    assert image.width() == 50
    assert image.height() == 25
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_thumbnails.py -v`

Expected: fails with `ModuleNotFoundError: No module named 'viewer.thumbnails'`.

- [ ] **Step 3: Implement `viewer/thumbnails.py`**

- `qimage_from_frame`: color frames become `QImage.Format_RGB888`;
  monochrome frames are normalized with `levels` (fall back to the frame's
  min/max, then `high = low + 1` when equal) and become
  `QImage.Format_Grayscale8`. Make the array C-contiguous
  (`np.ascontiguousarray`) and build the image with an explicit
  `bytesPerLine` (`width * channels`); QImage otherwise assumes 4-byte-aligned
  rows and skews images whose row width is not a multiple of 4. Always
  `.copy()` the image so the numpy buffer may be released.
- `thumbnail_qimage`: `qimage.scaledToWidth(width, Qt.SmoothTransformation)`.
- `ThumbnailProvider`: `QThreadPool` with `maxThreadCount = 2`. Each request
  decodes the middle frame (`info.frames // 2`) with `decode_frame`, computes
  monochrome levels with `mono_levels(frame)`, builds/scales the QImage, and
  emits `thumbnail_ready(path, image)`. Exceptions emit
  `thumbnail_failed(path, str(exc))`. QImage may be created off the GUI
  thread; QPixmap may not.

- [ ] **Step 4: Wire import into `viewer/main_window.py`**

- `ViewerWindow.__init__`: create `self.session = None`,
  `self._items_by_path: dict[Path, QListWidgetItem] = {}`,
  `self._thumbnails = ThumbnailProvider(self)`, connect its two signals, and
  connect `openSessionButton.clicked` to `open_session`.
- `open_session`: `QFileDialog.getExistingDirectory(self, "Open session")`;
  return on empty. Start a `ScanWorker(QThread)` (defined in this module) that
  runs `scan_session(folder)` and emits `succeeded(Session)` or `failed(str)`.
  Disable `openSessionButton` while scanning; show `"Scanning …"` in the
  status bar. The worker's `succeeded` connects to `_on_scan_succeeded` and
  `failed` to `_on_scan_failed`.
- `_on_scan_failed(message)`: re-enable the button, `QMessageBox.warning`, and
  keep the existing session.
- `_on_scan_succeeded(session)` with zero recordings: re-enable,
  `QMessageBox.information` ("No DICOM recordings found"), keep the existing
  session. With recordings: re-enable and call `load_session(session)`.
- `load_session(session)`: store it, clear the rail and
  `_items_by_path`; set `sessionLabel` to
  `f"{session.folder.name} · {len(session.recordings)} recordings"`; for each
  recording add a `QListWidgetItem(recording_label(info, i + 1))` with
  `Qt.UserRole = i`, add it to the rail, map the recording path to the item,
  and request a thumbnail. Keep a reference to the `ScanWorker` until it
  finishes so it is not garbage-collected.
- `_on_thumbnail_ready(path, image)`: find the item, set
  `QIcon(QPixmap.fromImage(image))` as its icon.
- `_on_thumbnail_failed(path, message)`: append `" ⚠"` once to the item text
  and set the tooltip to `message`.
- Show `"Loaded N recordings"` when the scan finishes; thumbnail generation
  may continue.

- [ ] **Step 5: Write the session-keeping test, run tests, manual check**

Create `tests/test_viewer_session.py`:

```python
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from viewer.main_window import ViewerWindow  # noqa: E402
from viewer.session import scan_session  # noqa: E402


def test_empty_or_failed_scan_keeps_previous_session(
    write_dicom, tmp_path, monkeypatch
):
    app = QApplication.instance() or QApplication([])
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append("w"))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append("i"))
    write_dicom("rec.dcm")
    window = ViewerWindow()
    session = scan_session(tmp_path)
    window.load_session(session)
    empty = tmp_path / "empty"
    empty.mkdir()

    window._on_scan_succeeded(scan_session(empty))
    assert window.session is session
    assert shown == ["i"]

    window._on_scan_failed("boom")
    assert window.session is session
    assert shown == ["i", "w"]
    assert window.openSessionButton.isEnabled()
    assert len(window._items_by_path) == 1
    window.close()
    app.processEvents()
```

Run: `.venv/bin/python -m pytest tests/test_thumbnails.py tests/test_viewer_smoke.py tests/test_viewer_session.py -v`

Expected: 6 passed.

Launch `.venv/bin/python -m viewer`, click "Open session", choose
`data/series-00000`. Expect: rail fills with 48 items labelled
`REC nn · inst …`; thumbnails appear progressively; stills end in `STILL`;
the window stays responsive. Try an empty folder: a message appears and the
previous session remains.

- [ ] **Step 6: Commit**

```bash
git add viewer/thumbnails.py tests/test_thumbnails.py tests/test_viewer_session.py viewer/main_window.py
git commit -m "feat: import sessions and show thumbnail rail"
```

---

### Task 7: Viewport tiles, tile assignment, and loop prefetch

**Files:**
- Create: `viewer/viewport.py`
- Create: `tests/test_viewport.py`
- Modify: `viewer/frames.py` (add `PrefetchPool`)
- Modify: `viewer/main_window.py`

**Interfaces:**
- Consumes: `Loop`, `FrameCache`, `decode_frame`, `Timeline`, `RecordingInfo`,
  `display_array`
- Produces:

```python
class RecordingViewport(QFrame):
    activated = Signal(object)
    closed = Signal(object)
    scrub_requested = Signal(object, int)
    error = Signal(str)

    def __init__(self, cache: FrameCache, parent=None) -> None: ...
    recording: RecordingInfo | None
    timeline: Timeline | None
    levels: tuple[float, float] | None
    def set_recording(self, info: RecordingInfo) -> None: ...
    def set_levels(self, levels: tuple[float, float] | None) -> None: ...
    def set_loop(self, loop: Loop) -> None: ...
    def show_time(self, t: float, hold_at_end: bool) -> None: ...
    def show_frame(self, frame: np.ndarray) -> None: ...
    def current_frame_index(self) -> int: ...
    def clear(self) -> None: ...
    def set_active(self, active: bool) -> None: ...

class PrefetchPool(QObject):
    loop_ready = Signal(object, object)   # RecordingInfo, Loop
    loop_failed = Signal(object, str)
    def __init__(self, parent=None, max_workers: int = 4) -> None: ...
    def request(self, info: RecordingInfo) -> None: ...
    def cancel(self, info: RecordingInfo) -> None: ...
```

- [ ] **Step 1: Write the failing viewport test**

Create `tests/test_viewport.py`:

```python
import os

import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from viewer.frames import FrameCache, PrefetchPool, decode_loop  # noqa: E402
from viewer.session import scan_session  # noqa: E402
from viewer.viewport import RecordingViewport  # noqa: E402


def test_viewport_shows_recording_and_clamps_hold(write_dicom):
    app = QApplication.instance() or QApplication([])
    path, _ = write_dicom("rec.dcm", frames=3, fps=25.0, color=True)
    info = scan_session(path.parent).recordings[0]
    viewport = RecordingViewport(FrameCache(budget_bytes=10_000_000))
    viewport.set_recording(info)
    assert viewport.timeline.frame_count == 3
    assert viewport.current_frame_index() == 0
    viewport.show_time(0.05, hold_at_end=False)
    assert viewport.current_frame_index() == 1
    viewport.show_time(10.0, hold_at_end=True)
    assert viewport.current_frame_index() == 2
    viewport.close()
    app.processEvents()


def test_viewport_clear_resets_state(write_dicom):
    app = QApplication.instance() or QApplication([])
    path, _ = write_dicom("rec.dcm", frames=2, color=False)
    info = scan_session(path.parent).recordings[0]
    viewport = RecordingViewport(FrameCache(budget_bytes=10_000_000))
    viewport.set_recording(info)
    viewport.clear()
    assert viewport.recording is None
    assert viewport.timeline is None
    viewport.close()
    app.processEvents()


def test_monochrome_viewport_computes_levels(write_dicom):
    app = QApplication.instance() or QApplication([])
    path, _ = write_dicom("mono.dcm", frames=2, color=False)
    info = scan_session(path.parent).recordings[0]
    viewport = RecordingViewport(FrameCache(budget_bytes=10_000_000))
    viewport.set_recording(info)
    low, high = viewport.levels
    assert low < high
    viewport.close()
    app.processEvents()


def test_levels_stay_fixed_when_loop_arrives(write_dicom):
    app = QApplication.instance() or QApplication([])
    path, _ = write_dicom("mono.dcm", frames=4, color=False)
    info = scan_session(path.parent).recordings[0]
    viewport = RecordingViewport(FrameCache(budget_bytes=10_000_000))
    viewport.set_recording(info)
    before = viewport.levels
    loop = decode_loop(info)
    assert loop.levels != before  # percentiles over all frames differ
    viewport.set_loop(loop)
    assert viewport.levels == before
    viewport.close()
    app.processEvents()


def _wait(app, predicate, timeout=5.0):
    end = time.monotonic() + timeout
    while not predicate() and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


def test_prefetch_ignores_duplicate_request_while_in_flight(write_dicom):
    app = QApplication.instance() or QApplication([])
    path, _ = write_dicom("rec.dcm", frames=3, color=True)
    info = scan_session(path.parent).recordings[0]
    pool = PrefetchPool()
    ready = []
    pool.loop_ready.connect(lambda i, loop: ready.append(i.path))
    pool.request(info)
    pool.request(info)
    _wait(app, lambda: ready)
    _wait(app, lambda: False, timeout=0.3)  # let any stray second result arrive
    assert ready == [info.path]


def test_prefetch_cancel_drops_in_flight_result(write_dicom):
    app = QApplication.instance() or QApplication([])
    path, _ = write_dicom("rec.dcm", frames=3, color=True)
    info = scan_session(path.parent).recordings[0]
    pool = PrefetchPool()
    ready = []
    pool.loop_ready.connect(lambda i, loop: ready.append(i.path))
    pool.request(info)
    pool.cancel(info)
    _wait(app, lambda: False, timeout=0.5)
    assert ready == []
    pool.request(info)  # a fresh request after cancel works again
    _wait(app, lambda: ready)
    assert ready == [info.path]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_viewport.py -v`

Expected: fails with `ModuleNotFoundError: No module named 'viewer.viewport'`.

- [ ] **Step 3: Implement `RecordingViewport`**

- `QFrame` with a `QVBoxLayout`: `pg.PlotWidget` (stretch 1) and a bottom row
  with `QSlider(Qt.Horizontal)`, a frame label, and a `×` close button.
- Plot setup: `setAspectLocked(True)`, `invertY(True)`,
  `setMouseEnabled(False, False)`, `setMenuEnabled(False)`, hide both axes,
  no histogram. `ImageItem` displays `display_array(frame, info.is_color)`.
- Overlay labels parented to the plot, transparent for mouse events:
  top-left patient/study (`patient_name`, `patient_id`, `study_date`),
  top-right recording details (`REC` number is not known here, so instance,
  acquisition time, frames, fps, heart rate), bottom-left frame counter,
  playback state, and `STILL`. Reposition them in `resizeEvent`. When empty,
  hide the image and show a centered `No recording` label; `clear()` restores
  that state.
- `set_recording`: store info and
  `Timeline(frame_count=info.frames, fps=info.fps)`; configure slider
  `0..frames-1`; fill labels; set active frame 0 by calling
  `show_time(0.0, hold_at_end=False)`; hide the slider and show `STILL` for
  single-frame recordings. For monochrome recordings, fix `self.levels` once
  here from `mono_levels(decode_frame(info, info.frames // 2))`; color sets
  `levels = None`. Levels are never changed afterwards for that recording.
- `show_time`: stills use frame 0; when `hold_at_end` and
  `t >= timeline.loop_duration_s` use `timeline.loop_end`; otherwise
  `timeline.frame_at(t)`. Then `_show_index(index)`.
- `_show_index`: read the loop from the cache; on a miss decode
  `decode_frame(info, index)` synchronously (5–13 ms). Use the fixed
  `self.levels`; never recompute per frame, so brightness does not flicker
  between on-demand frames and the prefetched loop. Update the image, slider (block signals), and counter label. On decode failure
  set a per-recording failure flag (so the tile stops advancing), emit
  `error(str(exc))`, and show the message in the bottom label; the flag
  resets in `set_recording`.
- `set_loop`: store the loop, keep the existing `self.levels` (do not adopt
  `loop.levels`), display the current index.
- `show_frame`: `ImageItem.setImage(display_array(frame, info.is_color),
  autoLevels=False, levels=...)`; for color pass `levels=None`.
- `set_active`: set a dynamic property `active` and repolish the stylesheet
  `RecordingViewport[active="true"] { border: 2px solid #5aa9e6; }`.
- Mouse press on the plot or overlay emits `activated(self)`; `×` emits
  `closed(self)`; slider `sliderMoved` emits `scrub_requested(self, value)`.
  A programmatic `setValue` must not emit.

- [ ] **Step 4: Add `PrefetchPool` to `viewer/frames.py`**

Use `QThreadPool` with `max_workers`, a generation counter per path, and a set
of in-flight paths. `request` does nothing when the path is already in flight;
otherwise it adds the path and starts a runnable that decodes the loop with its
captured generation. On completion the runnable emits only if its generation is
still current, and the path leaves the in-flight set. `cancel(info)` increments
the generation and removes the path from the in-flight set, so any running
result is ignored and a later `request` starts fresh. Emit
`loop_ready(info, loop)` or `loop_failed(info, message)`. Because delivery is by
path, the window (not the pool) decides when a cancel is safe.

- [ ] **Step 5: Wire viewports and assignment in `viewer/main_window.py`**

- In `__init__`: `self.cache = FrameCache()`, `self.prefetch = PrefetchPool(self)`,
  connect `loop_ready`/`loop_failed`, create four `RecordingViewport` objects,
  add them to `gridLayout` at `(0,0)`, `(0,1)`, `(1,0)`, `(1,1)`, and keep
  `self.viewports` and `self.active_viewport` (first one).
- Connect each viewport's `activated` to `_set_active`, `closed` to
  `_on_viewport_closed`, and `error` to a status-bar message.
- Connect `thumbnailList.itemClicked` to `_on_thumbnail_clicked`:
  look up the index from `Qt.UserRole`, take the recording, and assign it to
  the active viewport when that viewport is empty; otherwise use the first
  empty viewport; when all are occupied, replace the active viewport. Make
  the assigned viewport active.
- `_release(viewport)`: if the viewport has a recording and no other viewport
  shows the same path, `prefetch.cancel(recording)`. Never cancel a path another
  tile still shows, so two tiles on one recording both receive the loop.
- In `load_session`, before repopulating, call `_reset_tiles()`: cancel
  prefetch for each viewport's recording, `viewport.clear()`, and `cache.clear()`.
- `_assign(viewport, info)`: call `_release(viewport)` for the previous recording, call
  `viewport.set_recording(info)`, and place a cached loop if
  `cache.get(info.path)` exists; only otherwise call `prefetch.request(info)`.
  Set active and title/status.
- `_on_loop_ready(info, loop)`: `cache.put(info.path, loop)`; for every
  viewport showing that path call `set_loop(loop)`.
- `_on_loop_failed(info, message)`: status-bar message; leave the tile's
  on-demand display active.
- `_on_viewport_closed(viewport)`: `_release(viewport)`, then `viewport.clear()`.
- `_set_active(viewport)`: update `active_viewport` and call `set_active` on
  all viewports.

- [ ] **Step 6: Run tests and manual check**

Run: `.venv/bin/python -m pytest tests/test_viewport.py tests/test_frames.py -v`

Expected: 13 passed (7 frames, 6 viewport/prefetch).

Launch `.venv/bin/python -m viewer`, open `data/series-00000`, click four
thumbnails. Expect each to appear in a tile, first frame shown immediately,
the full loop prefetched within about a second, and the `×` button to clear a
tile. Click a tile, then another thumbnail, and confirm the replacement.

- [ ] **Step 7: Commit**

```bash
git add viewer/viewport.py tests/test_viewport.py viewer/frames.py viewer/main_window.py
git commit -m "feat: add recording tiles and loop prefetch"
```

---

### Task 8: Playback wiring, layout switching, and acceptance

**Files:**
- Modify: `viewer/main_window.py`
- Modify: `viewer/playback.py` (only if the controller needs a fix found by manual checks)
- Modify: `README.md`

**Interfaces:**
- Consumes: `PlaybackController`, `Timeline`, viewport contract from Task 7
- Produces: working toolbar transport, sync/loop toggles, 1×1/2×2 layout
  switching, and a documented run command.

- [ ] **Step 1: Wire the controller**

In `ViewerWindow.__init__`:

- Create `self.controller = PlaybackController(self)` and
  `add_viewport` for all four viewports.
- Call `_apply_layout()` once after the viewports exist so the initial
  `layoutCombo` selection is authoritative.
- `playButton.clicked` → `self.controller.play()` if paused, else
  `self.controller.pause()`.
- `stopButton.clicked` → `self.controller.restart()`.
- `self.controller.state_changed` → `_on_playback_state(playing)`: set
  `playButton` text to `"Pause"` when playing, else `"Play"`.
- `syncCheckBox.toggled` → `self.controller.set_synced(checked)` and show
  `Synced` or `Independent` in the status bar.
- `loopCheckBox.toggled` → `self.controller.set_loop(checked)`.
- Connect each viewport's `scrub_requested` to `self.controller.scrub`.
- After `_assign` and `_on_viewport_closed`, call
  `self.controller.show_current()` so a newly loaded tile appears at the
  shared time.

- [ ] **Step 2: Implement layout switching**

- `layoutCombo.currentIndexChanged` → `_apply_layout`.
- Mapping: index 0 = 1×1, index 1 = 2×2.
- Remove all viewports from `gridLayout`, then hide all of them.
- 2×2: show all four and place them at `(0,0)`, `(0,1)`, `(1,0)`, `(1,1)`.
- 1×1: show only `active_viewport` at `(0,0)`.
- `_set_active` in 1×1 must re-apply the layout so the newly active viewport
  is the one shown.
- Hidden viewports are skipped by the playback controller, so the sync
  period follows the visible tiles.

- [ ] **Step 3: Update `README.md`**

Add a `## Viewer` section: run `python -m viewer` from the repo root, open a
session folder, click thumbnails to fill tiles, use Play/Stop/Sync/Loop and
the 1×1/2×2 layout selector. Note that `viewer/viewer_window.ui` is edited in
Designer and regenerated with
`pyside6-uic viewer/viewer_window.ui -o viewer/ui_viewer_window.py`.

- [ ] **Step 4: Run the full automated suite**

Run:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m py_compile dicom_io.py main.py viewer/*.py
```

Expected: all tests pass and no compile errors. The suite must not touch
`data/`.

- [ ] **Step 5: Manual acceptance**

Launch `.venv/bin/python -m viewer` and check:

- Open `data/series-00000`: 48 recordings, thumbnails, stills marked, window
  responsive during thumbnail generation.
- Load four recordings, including at least two with different fps if
  available: each tile shows its loop; `×` empties a tile.
- Synced (default): Play advances all tiles on one clock, each at its own
  fps; Pause stops; Sync off/on restarts all aligned; Loop off stops at the
  end of the longest recording and Play restarts from the beginning.
- Independent: each tile loops at its own rate; pausing stops all.
- Scrub: moving one tile's slider updates that tile; in synced mode the other
  tiles move to the same wall-clock time.
- Layout 1×1 shows the active recording full-size; switching back to 2×2
  restores all four.
- Open an empty folder: previous session remains, message shown.
- Load four 93-frame loops: no memory blow-up or UI freeze; check process RSS
  stays roughly under 2 GB (`ps -o rss= -p <pid>`), and no decode error
  appears in the status bar.
- Monochrome rendering is covered by `tests/test_viewport.py`; if a real
  monochrome study is available, open it and confirm stable brightness and
  geometry.

- [ ] **Step 6: Echo regression**

Run `.venv/bin/python main.py`, open
`data/series-00000/image-00000.dcm`, and confirm the image, 93-frame
timeline, playback, and the existing segmentation/overlay controls behave as
before. Close Echo.

- [ ] **Step 7: Commit**

```bash
git add viewer/main_window.py viewer/playback.py README.md
git commit -m "feat: wire synchronized playback and viewer layouts"
```
