import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox  # noqa: E402

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


def _app():
    return QApplication.instance() or QApplication([])


def test_two_recordings_populate_label_rail_and_roles(write_dicom, tmp_path):
    app = _app()
    write_dicom("a.dcm", instance=1)
    write_dicom("b.dcm", instance=2)
    session = scan_session(tmp_path)
    window = ViewerWindow()
    window.load_session(session)
    assert window.sessionLabel.text() == f"{session.folder.name} · 2 recordings"
    assert window.thumbnailList.count() == 2
    roles = [window.thumbnailList.item(i).data(Qt.ItemDataRole.UserRole) for i in range(2)]
    assert roles == [0, 1]
    assert set(window._items_by_path) == {r.path for r in session.recordings}
    window.close()
    app.processEvents()


def test_thumbnail_failed_appends_marker_once_and_sets_tooltip(write_dicom, tmp_path):
    app = _app()
    write_dicom("rec.dcm")
    session = scan_session(tmp_path)
    window = ViewerWindow()
    window.load_session(session)
    path = session.recordings[0].path
    window._on_thumbnail_failed(path, "bad frame")
    window._on_thumbnail_failed(path, "bad frame")
    item = window._items_by_path[path]
    assert item.text().count(" ⚠") == 1
    assert item.toolTip() == "bad frame"
    window.close()
    app.processEvents()


def test_thumbnail_ready_sets_icon(write_dicom, tmp_path):
    app = _app()
    write_dicom("rec.dcm")
    session = scan_session(tmp_path)
    window = ViewerWindow()
    window.load_session(session)
    path = session.recordings[0].path
    window._on_thumbnail_ready(path, QImage(8, 8, QImage.Format_RGB888))
    assert not window._items_by_path[path].icon().isNull()
    window.close()
    app.processEvents()


def test_close_with_pending_thumbnails_is_clean(write_dicom, tmp_path):
    app = _app()
    write_dicom("a.dcm", instance=1)
    write_dicom("b.dcm", instance=2)
    session = scan_session(tmp_path)
    window = ViewerWindow()
    window.load_session(session)
    window.close()
    app.processEvents()
    provider = window._thumbnails
    got = []
    provider.thumbnail_ready.connect(lambda path, image: got.append(path))
    provider.request(session.recordings[0])
    provider._pool.waitForDone()
    app.processEvents()
    assert got == []


def test_close_while_scanning_waits_and_releases_worker(
    write_dicom, tmp_path, monkeypatch
):
    app = _app()
    write_dicom("rec.dcm")
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *a, **k: str(tmp_path)
    )
    window = ViewerWindow()
    window.open_session()
    window.close()
    app.processEvents()
    assert window._scan_worker is None


def test_rail_items_reserve_room_for_thumbnail(write_dicom, tmp_path):
    app = QApplication.instance() or QApplication([])
    write_dicom("rec.dcm")
    window = ViewerWindow()
    window.show()
    window.load_session(scan_session(tmp_path))
    app.processEvents()
    rail = window.thumbnailList
    assert rail.visualItemRect(rail.item(0)).height() >= rail.iconSize().height()
    window.close()
    app.processEvents()


def test_filter_combo_shows_all_video_or_image(write_dicom, tmp_path):
    app = QApplication.instance() or QApplication([])
    write_dicom("loop.dcm", frames=3, instance=1)
    write_dicom("still.dcm", frames=1, instance=2)
    (tmp_path / "bad.dcm").write_text("not a dicom")
    window = ViewerWindow()
    window.show()
    window.load_session(scan_session(tmp_path))
    rail = window.thumbnailList

    def visible():
        return sorted(
            rail.item(i).text().split(" · ")[1]
            for i in range(rail.count())
            if not rail.item(i).isHidden()
        )

    assert len(visible()) == 3
    window.filterCombo.setCurrentIndex(1)
    assert visible() == ["inst 1"]
    window.filterCombo.setCurrentIndex(2)
    assert visible() == ["inst 2"]
    window.filterCombo.setCurrentIndex(0)
    assert len(visible()) == 3
    window.close()
    app.processEvents()
