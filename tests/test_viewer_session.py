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
