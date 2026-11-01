import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from echo_viewer.frames import decode_loop  # noqa: E402
from echo_viewer.window import ViewerWindow  # noqa: E402
from echo_viewer.session import Session, scan_session  # noqa: E402


def _app():
    return QApplication.instance() or QApplication([])


def _write_session(tmp_path, write_dicom, n, bad=False):
    for i in range(n):
        write_dicom(f"rec{i}.dcm", frames=3, instance=i + 1, color=True)
    if bad:
        (tmp_path / "bad.dcm").write_bytes(b"not dicom")
    return scan_session(tmp_path)


def _click(window, index):
    window.thumbnailList.itemClicked.emit(window.thumbnailList.item(index))


def _wait(app, predicate, timeout=5.0):
    end = time.monotonic() + timeout
    while not predicate() and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


def _shown(window):
    return [v.recording for v in window.viewports]


def test_click_placement_fills_then_replaces_active(tmp_path, write_dicom):
    app = _app()
    session = _write_session(tmp_path, write_dicom, 5)
    rec = session.recordings
    w = ViewerWindow()
    w.load_session(session)
    v = w.viewports

    _click(w, 0)  # empty active tile gets it
    assert v[0].recording == rec[0] and w.active_viewport is v[0]

    _click(w, 1)  # active occupied -> first empty tile
    assert v[1].recording == rec[1] and w.active_viewport is v[1]

    _click(w, 2)
    assert v[2].recording == rec[2] and w.active_viewport is v[2]

    _click(w, 3)
    assert v[3].recording == rec[3] and w.active_viewport is v[3]

    _click(w, 4)  # all occupied -> replace the active tile (v[3])
    assert v[3].recording == rec[4] and w.active_viewport is v[3]
    assert v[0].recording == rec[0] and v[1].recording == rec[1] and v[2].recording == rec[2]

    w._set_active(v[1])
    _click(w, 0)  # all occupied -> replace the newly active tile (v[1])
    assert v[1].recording == rec[0] and w.active_viewport is v[1]
    assert v[3].recording == rec[4]
    assert [t.property("active") for t in v] == ["false", "true", "false", "false"]
    w.close()
    app.processEvents()


def test_shared_path_survives_closing_or_replacing_one_tile(tmp_path, write_dicom, monkeypatch):
    app = _app()
    session = _write_session(tmp_path, write_dicom, 2)
    rec = session.recordings
    w = ViewerWindow()
    w.load_session(session)
    v = w.viewports

    cancelled = []
    real_cancel = w.prefetch.cancel
    monkeypatch.setattr(
        w.prefetch, "cancel", lambda info: (cancelled.append(info.path), real_cancel(info))
    )

    _click(w, 0)
    _click(w, 0)  # same recording lands in tile 1 too
    assert v[0].recording == rec[0] and v[1].recording == rec[0]

    v[1].closed.emit(v[1])  # close one of two tiles on the same recording
    assert v[1].recording is None
    assert cancelled == []

    w._set_active(v[1])
    _click(w, 1)  # replace tile 1 with another recording while tile 0 still shows rec[0]
    assert v[1].recording == rec[1]
    assert cancelled == []

    _wait(app, lambda: w.cache.get(rec[0].path) is not None)
    assert w.cache.get(rec[0].path) is not None  # surviving tile still reads its loop

    v[0].closed.emit(v[0])  # last tile on rec[0] -> its prefetch is cancelled
    assert cancelled == [rec[0].path]
    w.close()
    app.processEvents()


def test_loop_ready_fans_out_to_every_tile_showing_path(tmp_path, write_dicom):
    app = _app()
    session = _write_session(tmp_path, write_dicom, 2)
    rec = session.recordings
    w = ViewerWindow()
    w.load_session(session)
    v = w.viewports
    _click(w, 0)
    _click(w, 0)
    _click(w, 1)
    assert _shown(w)[:3] == [rec[0], rec[0], rec[1]]

    loop = decode_loop(rec[0])
    w._on_loop_ready(rec[0], loop)  # called directly; no event processing in between
    assert w.cache.get(rec[0].path) is loop
    assert v[0]._state() == "LOOP" and v[1]._state() == "LOOP"
    assert v[2]._state() != "LOOP"
    w.close()
    app.processEvents()


def test_load_session_clears_tiles_and_cache(tmp_path, write_dicom):
    app = _app()
    session = _write_session(tmp_path, write_dicom, 2)
    w = ViewerWindow()
    w.load_session(session)
    _click(w, 0)
    _click(w, 1)
    _wait(app, lambda: len(w.cache) == 2)
    assert len(w.cache) == 2

    w.load_session(Session(folder=tmp_path, study_label="", recordings=()))
    assert _shown(w) == [None, None, None, None]
    assert all(t.timeline is None for t in w.viewports)
    assert len(w.cache) == 0
    w.close()
    app.processEvents()


def test_error_recording_is_not_assigned_on_click(tmp_path, write_dicom):
    app = _app()
    write_dicom("ok.dcm", frames=2, color=True)
    session = _write_session(tmp_path, write_dicom, 0, bad=True)
    error_index = next(i for i, r in enumerate(session.recordings) if r.error is not None)
    w = ViewerWindow()
    w.load_session(session)
    _click(w, error_index)
    assert _shown(w) == [None, None, None, None]
    assert w.active_viewport is w.viewports[0]
    assert "Cannot show" in w.statusbar.currentMessage()
    w.close()
    app.processEvents()
