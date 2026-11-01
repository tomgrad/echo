import gc
import os
import threading
import time
import weakref

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from echo_core.display import mono_levels  # noqa: E402
from echo_viewer.frames import FrameCache, PrefetchPool, decode_frame, decode_loop  # noqa: E402
from echo_viewer.session import scan_session  # noqa: E402
from echo_viewer.viewport import RecordingViewport  # noqa: E402


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


def test_levels_use_middle_frame_until_loop_arrives_then_loop_levels(write_dicom):
    app = QApplication.instance() or QApplication([])
    path, _ = write_dicom("mono.dcm", frames=4, color=False)
    info = scan_session(path.parent).recordings[0]
    viewport = RecordingViewport(FrameCache(budget_bytes=10_000_000))
    viewport.set_recording(info)
    mid_levels = mono_levels(decode_frame(info, 2))
    assert viewport.levels == mid_levels  # pre-prefetch fallback
    loop = decode_loop(info)
    assert loop.levels != mid_levels  # the two level pairs must differ
    viewport.set_loop(loop)
    assert viewport.levels == loop.levels
    viewport.show_time(0.05, hold_at_end=False)
    viewport.show_time(0.10, hold_at_end=False)
    _wait(app, lambda: not viewport._decode_busy)
    assert viewport.levels == loop.levels  # stays fixed across later frames
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


def test_overlays_stay_inside_plot_after_show_and_resize(write_dicom):
    app = QApplication.instance() or QApplication([])
    path, _ = write_dicom("rec.dcm", frames=3, color=True)
    write_dicom("still.dcm", frames=1, color=True)
    info = scan_session(path.parent).recordings[0]
    still = next(r for r in scan_session(path.parent).recordings if r.is_still)
    viewport = RecordingViewport(FrameCache(budget_bytes=10_000_000))
    viewport.resize(600, 400)
    viewport.show()
    app.processEvents()
    viewport.set_recording(info)
    app.processEvents()
    labels = (viewport._top_left, viewport._top_right, viewport._bottom_left)
    for label in labels:
        geo = label.geometry()
        assert geo.width() > 0 and geo.height() > 0
        assert viewport._plot.rect().contains(geo)
    # Still recording hides the slider, which grows the plot; overlays must follow.
    viewport.set_recording(still)
    app.processEvents()
    for label in labels:
        geo = label.geometry()
        assert geo.width() > 0 and geo.height() > 0
        assert viewport._plot.rect().contains(geo)
    viewport.close()
    app.processEvents()


def test_bottom_label_shows_counter_and_state(write_dicom):
    app = QApplication.instance() or QApplication([])
    path, _ = write_dicom("rec.dcm", frames=3, color=True)
    info = scan_session(path.parent).recordings[0]
    cache = FrameCache(budget_bytes=10_000_000)
    viewport = RecordingViewport(cache)
    viewport.set_recording(info)
    assert viewport._bottom_left.text() == "1/3 · LOADING"
    viewport.show_time(0.05, hold_at_end=False)
    assert viewport._bottom_left.text() == "2/3 · LOADING"
    viewport.mark_prefetch_failed()
    assert viewport._bottom_left.text() == "2/3 · ON DEMAND"
    cache.put(info.path, decode_loop(info))
    viewport.set_loop(cache.get(info.path))
    assert viewport._bottom_left.text() == "2/3 · LOOP"
    viewport.close()
    app.processEvents()


def test_mono_setup_failure_clears_previous_image_and_levels(write_dicom, monkeypatch):
    app = QApplication.instance() or QApplication([])
    color_path, _ = write_dicom("color.dcm", frames=2, color=True)
    mono_path, _ = write_dicom("mono.dcm", frames=2, color=False)
    recordings = {r.path.name: r for r in scan_session(color_path.parent).recordings}
    viewport = RecordingViewport(FrameCache(budget_bytes=10_000_000))
    viewport.set_recording(recordings["color.dcm"])
    assert viewport._image.isVisible()

    import echo_viewer.viewport as viewport_module

    def boom(info, index):
        raise RuntimeError("boom")

    monkeypatch.setattr(viewport_module, "decode_frame", boom)
    errors = []
    viewport.error.connect(errors.append)
    viewport.set_recording(recordings["mono.dcm"])
    app.processEvents()
    assert errors == ["boom"]
    assert not viewport._image.isVisible()
    assert viewport.levels is None
    assert "error: boom" in viewport._bottom_left.text()
    viewport.close()
    app.processEvents()


def _record_shown(monkeypatch):
    shown = []
    original = RecordingViewport.show_frame

    def spy(self, frame):
        shown.append(np.array(frame))
        return original(self, frame)

    monkeypatch.setattr(RecordingViewport, "show_frame", spy)
    return shown


def test_evicted_loop_is_not_retained_by_viewport(write_dicom, monkeypatch):
    app = QApplication.instance() or QApplication([])
    path_a, arr_a = write_dicom("a.dcm", frames=4, color=False)
    path_b, _ = write_dicom("b.dcm", frames=4, color=False)
    recs = {r.path.name: r for r in scan_session(path_a.parent).recordings}
    a, b = recs["a.dcm"], recs["b.dcm"]
    loop_a_bytes = decode_loop(a).frames.nbytes
    cache = FrameCache(budget_bytes=loop_a_bytes + 10)  # holds one loop only
    viewport = RecordingViewport(cache)
    shown = _record_shown(monkeypatch)
    viewport.set_recording(a)
    loop_a = decode_loop(a)
    cache.put(a.path, loop_a)
    viewport.set_loop(loop_a)
    loop_ref = weakref.ref(loop_a)
    frames_ref = weakref.ref(loop_a.frames)
    del loop_a
    cache.put(b.path, decode_loop(b))  # evicts a
    assert cache.get(a.path) is None
    gc.collect()
    assert loop_ref() is None and frames_ref() is None
    # The tile still shows its recording, decoding on demand from the file.
    viewport.show_time(0.05, hold_at_end=False)
    _wait(app, lambda: shown and np.array_equal(shown[-1], arr_a[1]))
    assert np.array_equal(shown[-1], arr_a[1])
    assert viewport.current_frame_index() == 1
    viewport.close()
    app.processEvents()


def test_rapid_requests_keep_one_decode_in_flight_and_show_last(write_dicom, monkeypatch):
    app = QApplication.instance() or QApplication([])
    path, arr = write_dicom("mono.dcm", frames=8, color=False)
    info = scan_session(path.parent).recordings[0]
    shown = _record_shown(monkeypatch)
    import echo_viewer.viewport as viewport_module

    lock = threading.Lock()
    stats = {"active": 0, "max_active": 0, "calls": 0}
    real_decode = viewport_module.decode_frame

    def slow_decode(info, index):
        with lock:
            stats["active"] += 1
            stats["max_active"] = max(stats["max_active"], stats["active"])
            stats["calls"] += 1
        try:
            time.sleep(0.01)
            return real_decode(info, index)
        finally:
            with lock:
                stats["active"] -= 1

    monkeypatch.setattr(viewport_module, "decode_frame", slow_decode)
    viewport = RecordingViewport(FrameCache(budget_bytes=10_000_000))
    viewport.set_recording(info)  # first frame is decoded synchronously
    for i in range(1, 8):  # rapid requests on a cache-miss tile
        viewport.show_time(i / 25, hold_at_end=False)
    assert viewport.current_frame_index() == 7
    _wait(app, lambda: shown and np.array_equal(shown[-1], arr[7]) and not viewport._decode_busy)
    assert np.array_equal(shown[-1], arr[7])
    assert stats["max_active"] == 1
    assert stats["calls"] < 8  # not one decode per request
    viewport.close()
    app.processEvents()


def test_slider_user_move_scrubs_once_programmatic_updates_do_not(write_dicom):
    app = QApplication.instance() or QApplication([])
    path, _ = write_dicom("rec.dcm", frames=4, color=True)
    info = scan_session(path.parent).recordings[0]
    cache = FrameCache(budget_bytes=10_000_000)
    viewport = RecordingViewport(cache)
    got = []
    viewport.scrub_requested.connect(lambda v, i: got.append((v, i)))
    viewport.set_recording(info)  # range reset and first frame: no scrub
    viewport.clear()
    viewport.set_recording(info)
    assert got == []
    viewport._slider.setValue(2)  # keyboard/mouse-like move from outside
    assert got == [(viewport, 2)]
    viewport.show_time(0.05, hold_at_end=False)  # internal display update
    _wait(app, lambda: not viewport._decode_busy)
    assert viewport.current_frame_index() == 1
    assert got == [(viewport, 2)]
    cache.put(info.path, decode_loop(info))
    viewport.show_time(0.10, hold_at_end=False)  # cache-hit path, still silent
    assert got == [(viewport, 2)]
    viewport.close()
    app.processEvents()
