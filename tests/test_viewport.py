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
