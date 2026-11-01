# Echocardiography DICOM Viewer — Design

Date: 2026-11-01
Status: approved 2026-11-01

## Intent

Echo currently opens one DICOM recording at a time inside a MedSAM2 analysis
GUI. Reviewing an echo session means seeing many recordings, recognizing them
quickly, and comparing several heart cycles side by side at real playback
speed. This subproject builds that review viewer as its own GUI, inside the
Echo repository, with no dependency on torch or MedSAM.

Success: open a session folder, recognize its recordings from thumbnails,
place up to four in a 2×2 grid, and watch them play together in real time,
each at its own recorded frame rate. Later phases add ECG-based alignment and
custom loops without redesigning the playback core.

## Goals and non-goals

### Goals (MVP)

- Import a session folder from disk.
- Scan it recursively for DICOM recordings and show a thumbnail rail with
  identifying metadata.
- Display selected recordings in a 2×2 main grid; any number of tiles may be
  empty.
- Show each recording as a cine loop at its recorded fps, with play/pause,
  per-tile frame scrubbing, and a global sync toggle.
- Display both RGB (color) and monochrome recordings, with stable display
  levels per recording and no window/level UI in the MVP.
- Overlay patient/study/series/recording metadata on each tile.
- Keep memory bounded and the UI responsive while decoding.
- Leave the existing Echo GUI unchanged in behavior.

### Non-goals (MVP)

- ECG-based alignment (future).
- Custom in/out loops (future), independent or synced.
- Measurements, calipers, annotations, window/level, export.
- Saving/restoring session state, key frames, and comments (future; the
  model is fixed below so it stays additive).
- M-Mode/Doppler/3D/strain-specific views; every recording is displayed as
  frames.
- DICOMweb, network studies, multi-study navigation.
- Layout persistence, multi-monitor, fullscreen presentation mode.

### Anti-goals

- Coupling viewer startup to torch, checkpoints, or `medseg2`.
- Making per-frame decoding the primary playback path (stutters at 4 tiles).
- Turning the viewer into a general DICOM framework; scope is ultrasound.
- Changing Echo's GUI or analysis behavior while sharing loading code.

## Constraints and evidence from the data

- Python 3.14 venv; PySide6 6.12, pydicom 3.0.2, pyqtgraph 0.14, numpy.
- GUI authored as `.ui` files and generated with `pyside6-uic`; generated
  `ui_*.py` files are never hand-edited (repo rule).
- `data/series-00000` contains 48 separate recordings, one `.dcm` each:
  - 34 multi-frame loops, 13–119 frames, 14–111 fps (mostly 30 fps);
  - 14 single-frame stills (`UltrasoundImageStorage`);
  - all 708×1016, 3 samples/pixel, `YBR_FULL_422`, JPEG lossy, ~32 MB/file
  (the viewer also accepts monochrome, 8- or 16-bit, including
  uncompressed transfer syntaxes);
  - one session ≈ 1.2 GB on disk; a decoded 93-frame loop is ≈ 200 MB.
- Measured on this machine: single-frame decode 5–13 ms; full 93-frame loop
  decode ≈ 0.6 s.
- `CineRate` equals `RecommendedDisplayFrameRate` where present; 14 stills
  have neither. Fallback order: `CineRate` → `RecommendedDisplayFrameRate` →
  `1000 / FrameTime` → 30 fps.
- `RWaveTimeVector` exists in 28/48 files; no `WaveformSequence`. ECG-aligned
  playback is therefore feasible later for most loops, with burned-in ECG
  detection as a separate future problem.
- One session folder currently maps to one study and one series; scanning is
  still recursive and groups by folder, with one flat recording list.

## Approaches considered

**A — Standalone viewer package with a shared decode core (chosen).**
`viewer/` package, its own `.ui`, its own entry point, plus a small root
`dicom_io.py` extracted from `main.py`. Echo's `open_dicom_file` calls the
shared module; its GUI and behavior stay the same. Chosen because ECG
alignment, custom loops, and an eventual merge all fit the playback/timeline
model, and DICOM decoding is written once.

Tradeoff: a small refactor of working Echo code that needs a manual
verification that Echo still opens the same file.

**B — Fully self-contained viewer.** Same viewer design but a private loader;
no Echo change. Lower immediate risk, duplicated DICOM handling, and the
merge later has to reconcile two loaders. Rejected: the duplication buys
little.

**C — Extend Echo's `MainWindow`.** Reuse widgets, but it imports torch and
loads checkpoints, its panel layout is analysis-oriented, and the viewer's
"own GUI" boundary would disappear. Rejected.

Frame pipeline alternatives inside A:

- Eager whole-loop decode: smooth playback, 200 MB per loop.
- Per-frame decode only: ~5–13 ms per frame per tile; at 4 tiles and 30–111
  fps this risks stutter and makes high-fps loops impossible.
- **Hybrid (chosen):** stills decode one frame; a tile prefetches its whole
  loop in a worker, plays smoothly, and falls back to on-demand single-frame
  decode on cache misses. Memory is bounded by an LRU budget.

## Architecture

### Repository layout

```
dicom_io.py                  # shared DICOM reading (Echo + viewer)
main.py                      # Echo: open_dicom_file uses dicom_io
viewer/
  __init__.py
  __main__.py                # python -m viewer
  main_window.py             # ViewerWindow: wiring, session import, grid
  viewer_window.ui           # Qt Designer source
  ui_viewer_window.py        # generated by pyside6-uic
  session.py                 # Session, RecordingInfo, scan_session()
  frames.py                  # decode, prefetch, LRU frame cache
  playback.py                # Timeline, PlaybackClock, PlaybackController
  viewport.py                # RecordingViewport tile widget
  thumbnails.py              # thumbnail worker + list model
```

Run from the repo root with `python -m viewer`; `viewer` imports `dicom_io`
and `PySide6`/`pyqtgraph` only. `pyside6-uic viewer/viewer_window.ui -o
viewer/ui_viewer_window.py` is the generation command (add it to the existing
VS Code/Zed tasks).

### Data model

`session.RecordingInfo` (frozen dataclass), from a header read with
`stop_before_pixels=True`:

- `path`, `instance_number`, `sop_instance_uid`
- `frames`, `rows`, `cols`, `fps`, `duration_s`
- `is_still` (`frames == 1`), `is_color`
- `study_uid`, `series_uid`, `study_description`, `series_description`
- `patient_name`, `patient_id`, `study_date`, `acquisition_datetime`
- `error: str | None` for unreadable files

`Session` holds `folder`, `study_label`, and `recordings` sorted by
`instance_number`, then acquisition time, then filename. Scanning skips
non-DICOM files and empty folders; a file that fails `dcmread` is kept as an
error entry so it is visible rather than silently missing.

### Frame pipeline (`frames.py`)

- `read_frame(path_or_ds, index)` uses
  `pydicom.pixels.pixel_array(ds, index=index)`, which decodes a single frame
  of an encapsulated multi-frame object without decoding the rest.
- `FrameCache`: thread-safe LRU keyed by path, holding a fully decoded loop.
  An entry is `(frames, rows, cols) uint8/uint16` for monochrome or
  `(frames, rows, cols, 3) uint8` for RGB; accounting uses `nbytes`. Budget
  constant `1.2 GB` (≈ 5–6 color loops, more monochrome loops), configurable
  at module level. Eviction skips nothing special; a playing tile that loses
  its loop continues through on-demand decoding.
- For monochrome, prefetch also computes fixed display levels from up to 16
  evenly spaced frames (1st/99th percentile) and stores them with the entry,
  so brightness stays stable during playback. RGB is shown with
  `autoLevels=False`. No user-adjustable window/level in the MVP.
- Prefetch runs on a `QThreadPool` (max 4 workers), ordered by visible tiles,
  with a per-tile generation token so a replaced/closed tile cancels its work.
  When a loop finishes decoding, the dataset's 32 MB `PixelData` is released;
  only the frame array is retained.
- Thumbnails decode the middle frame (avoids black first frames), apply the
  same monochrome normalization, scale to ~180 px wide, and are delivered as
  `QPixmap` on the GUI thread. Missing or broken recordings show a
  placeholder tile and an error label.
- All decoded arrays are treated as immutable. GUI code only reads them; no
  lock is needed for array contents, only for cache mutation.

### Playback (`playback.py`)

The core abstraction, designed for the four eventual modes:

- `Timeline`: `frame_count`, `fps`, `loop_start`, `loop_end` (frame indices,
  defaults `0..frame_count-1`), `offset_s` (default 0).
  `frame_at(t)` maps clock seconds to a frame: subtract `offset_s`, wrap over
  the loop duration, convert to a frame index, clamp to the loop range.
  `duration_s` of the loop range is known.
- `PlaybackClock`: one `QTimer` at 60 Hz, advancing a monotonic position in
  seconds only while playing. It never counts frames, so timer jitter cannot
  accumulate. A 111 fps loop still maps to correct wall-clock frames; display
  simply skips frames at 60 Hz.
- `PlaybackController`: owns clocks and decides which clock drives which
  tiles.
  - **Independent mode:** each viewport has its own clock.
  - **Synced mode:** all viewports attach to one shared clock, each with its
    own `Timeline` (own fps, own loop range).
  - **Future custom loop:** set `loop_start`/`loop_end` on a tile's timeline;
    same code path.
  - **Future ECG alignment:** set `offset_s` per tile from
    `RWaveTimeVector`; same code path.
- MVP transport behavior:
  - Play/pause affects the controller; with sync on, all tiles start/stop
    together; with sync off, each tile starts/stops at its own position.
  - Sync toggling re-bases the shared clock to 0 and restarts all tiles at the
    beginning of their loops (playing state preserved). This is predictable
    and keeps alignment across cycles.
  - Synchronized looping uses a common period equal to the longest visible
    recording. Tiles whose recording is shorter hold their last frame until
    the common period resets, then all restart together. This preserves
    alignment; a "Loop" toolbar toggle disables wrapping so playback stops at
    the period end. Independent playback loops each recording at its own
    duration.
  - Stills have no clock; they show their single frame and are unaffected.
  - Scrub on a tile sets its clock position (in synced mode, this re-bases
    the shared clock so all tiles show the same time).

### Viewport (`viewport.py`)

`RecordingViewport(QWidget)`, created by code, not promoted in Designer:

- `pg.PlotWidget`/`ImageItem` for the image, aspect locked, `invertY`, no
  histogram, no axes. RGB frames are shown as `np.swapaxes(frame, 1, 0)` and
  monochrome frames as `np.swapaxes(frame, 0, 1)`, so x=column, y=row (the
  same convention as Echo's `ImageView`). Monochrome levels come from the
  recording, not from each frame.
- Fit-to-view only in the MVP: pyqtgraph mouse interaction (pan/zoom) is
  disabled so a click unambiguously activates the tile; image fits the tile
  and rescales with it.
- Overlay `QLabel`s above the plot: top-left patient name/ID + study date;
  top-right recording number, instance number, acquisition time, frames,
  fps, and heart rate when present; bottom-left current frame / total and
  playback state; a `QSlider` at the bottom for scrubbing; a small close (×)
  button. The rail label uses `REC n · instance · frames · fps · duration ·
  time`, with `STILL` for single-frame recordings. (The sample data has empty
  study/series descriptions, so folder name is the session label and
  acquisition time/instance number are the per-recording discriminators.)
- Active tile is outlined; clicking anywhere in it makes it active.
- Empty tile shows a centered "No recording" hint.
- `set_recording(info)`, `set_frame(np.ndarray)`, `clear()`, `set_active()`.
- Stills hide the slider and show "STILL".

### UI and interaction (`viewer_window.ui`, `main_window.py`)

MedDream-style layout:

```
┌──────────────────────────────────────────────────────────────────────┐
│ [Open session] [Layout: 1×1 | 2×2]  [▶ Play] [■ Stop] [Sync] [Loop] │
├────────────────┬─────────────────────────────────────────────────────┤
│ Session        │ ┌─────────────────┐ ┌─────────────────┐             │
│ study/series   │ │ REC 01          │ │ REC 02          │             │
│ ┌────────────┐ │ │  overlay text   │ │  overlay text   │             │
│ │ [thumb]    │ │ │                 │ │                 │             │
│ │ REC 01 ... │ │ │ [====slider===] │ │ [====slider===] │             │
│ ├────────────┤ │ └─────────────────┘ └─────────────────┘             │
│ │ [thumb]    │ │ ┌─────────────────┐ ┌─────────────────┐             │
│ │ REC 02 ... │ │ │ REC 03          │ │ REC 04          │             │
│ └────────────┘ │ └─────────────────┘ └─────────────────┘             │
├────────────────┴─────────────────────────────────────────────────────┤
│ Status bar                                                           │
└──────────────────────────────────────────────────────────────────────┘
```

- `.ui` contains the window, toolbar, left panel (`sessionLabel`,
  `thumbnailList`), and a central `gridContainer` widget with a `QGridLayout`
  whose cells are filled with viewports at runtime.
- Left rail: `QListWidget` in icon mode, two columns, each item a thumbnail
  plus text: `REC n · frames · fps · duration`, and `STILL` for stills.
- Loading: clicking a thumbnail loads it into the active viewport. If the
  active viewport is occupied and empty cells exist, the next empty cell
  becomes active. Selecting a recording highlights it in the rail. There is
  no drag-and-drop in MVP.
- Layouts: 1×1 and 2×2 in the MVP (combo box); switching preserves loaded
  recordings and re-flows them. 1×1 shows the active recording full-size,
  not a separate zoom mode. The grid code takes rows/columns, so more layouts
  are a UI-only addition.
- Import: folder dialog; the session scan and thumbnail generation run off
  the GUI thread with a busy status message. A failed or empty folder leaves
  the previous session untouched and reports the reason.
- Status bar shows decode/scan progress, load errors, and current mode.
- MVP follows the reference's layout and interaction conventions
  (image-first, small toolbar, thumbnail rail, per-tile overlays), not its
  pixel-exact skin: stock Qt chrome and standard icons, no QSS theme or icon
  asset pass. Styling can come later without touching this architecture.

### Shared DICOM module (`dicom_io.py`)

Small, explicit functions used by both applications:

- `read_dataset(path)` → `Dataset` (full, including pixel data)
- `read_header(path)` → `Dataset` (`stop_before_pixels=True`)
- `frame_count(ds)`, `fps(ds)`, `is_color(ds)`, `is_still(ds)`
- `pixel_frames(ds)` → full decoded array (2D monochrome or RGB `[:, :, 3]`,
  any bit depth pydicom supports)
- `pixel_frame(ds, index)` → one decoded frame
- `display_array(frame)` → `np.swapaxes(frame, 0, 1)` (x=column, y=row for
  both monochrome and RGB)
- `mono_levels(loop_or_frames)` → fixed `(low, high)` percentiles for
  monochrome display

`main.py::open_dicom_file` is refactored to call `read_dataset`,
`frame_count`, `fps`, `pixel_frames`, and `display_array`; RGB/gray handling
stays as it is. No Echo GUI change.

### Error handling and resource bounds

- Unreadable file: listed with an error state, tile shows the message; never
  crashes the scan.
- Decode failure during playback: pause that tile, show status, keep the rest
  running.
- No DICOM in folder: status message, no session switch.
- Missing fps: fallback chain above; duration computed from frames/fps.
- Closing a tile cancels its prefetch and releases its cache reference;
  cache eviction keeps total decoded memory near the budget.
- Session with hundreds of recordings: thumbnails generate progressively, and
  only visible/opened recordings are ever fully decoded.

## Testing

- Pure unit tests (`pytest`) for `dicom_io` metadata fallbacks and monochrome
  level computation, `session` scanning/ordering/error entries, and
  `Timeline.frame_at` (wrap, fps, offsets, loop ranges, stills) using
  synthetic small DICOMs (RGB and monochrome) written to `tmp_path`; tests
  must not depend on the 1.2 GB `data/` symlink.
- GUI acceptance is manual because `pytest-qt` is not installed:
  `python -m viewer`, open `data/series-00000`, verify 48 thumbnails, fill
  2×2, synced playback, independent playback, scrub, stills. Open one
  synthetic monochrome study and confirm stable levels.
- Echo regression: after the `dicom_io` refactor, open the same DICOM in Echo
  and verify image, frame count, playback, and segmentation controls behave
  exactly as before.

## MVP acceptance criteria

- `python -m viewer` starts without importing torch.
- Opening `data/series-00000` lists all 48 recordings with thumbnails and
  labels; stills are marked.
- Four recordings can be placed in the 2×2 grid and display correctly.
- Synced playback advances all tiles on one wall clock, each at its own fps;
  pause and scrub work; toggling sync restarts them aligned.
- Independent playback loops each tile at its own rate.
- Loading four 93-frame loops does not exhaust memory or freeze the UI; the
  window stays responsive during scans and prefetch.
- A monochrome recording opens with stable brightness and correct geometry.
- Echo's GUI and analysis behavior are unchanged after the shared-loader
  refactor.

## Session state (deferred, model fixed now)

Saving/restoring a session will use JSON (stdlib `json`; XML adds no value
here). The document will hold:

- `schema_version` and the session folder path;
- layout `(rows, columns)` and the ordered tile assignments, each a recording
  reference of `sop_instance_uid` + path relative to the session folder;
- playback state: mode (`independent` / `synced`), loop flag, and per-tile
  `Timeline` fields (`offset_s`, `loop_start`, `loop_end`);
- future: key frames (recording UID, frame index, label) and comments
  (recording UID, frame or time, text).

The MVP neither writes nor reads this file. It already keeps every field the
document needs (`RecordingInfo.sop_instance_uid` and paths, `Timeline`
offset/range, layout state), so persistence later is a serialization layer,
not a refactor.

## Future work (explicitly deferred)

- Session state persistence (JSON) with key frames and comments, as above.
- ECG-based alignment: compute per-tile `offset_s` from `RWaveTimeVector`
  (and later burned-in ECG detection for files without it), including a
  cardiac-phase alignment mode.
- Custom in/out loops per tile, individually and synced (timeline range plus
  a shared period).
- More layouts, fullscreen, drag-and-drop assignment.
- Measurements, annotations, window/level, export, metadata panel.
- Merge into Echo: share `RecordingViewport`/timeline with the analysis GUI.

## Open decisions (calls made here, easy to change)

- Package `viewer/`, shared `dicom_io.py` at repo root, entry `python -m viewer`.
- Default layout 2×2; layouts 1×1 and 2×2 only.
- Default playback mode: synced.
- Synced loop period = longest visible recording; shorter tiles hold their
  last frame; "Loop" toggle default on.
- Thumbnail frame = middle frame.
- Display tick 60 Hz, wall-clock based.
- Frame cache budget 1.2 GB LRU.
- Click-to-assign thumbnails; active-tile model; no drag-and-drop in MVP.
- Monochrome supported with fixed per-recording levels; session state saved
  as JSON when that phase arrives.
