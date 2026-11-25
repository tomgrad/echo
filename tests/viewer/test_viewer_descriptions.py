import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from echo_viewer.descriptions import FILE_NAME  # noqa: E402
from echo_viewer.session import scan_session  # noqa: E402
from echo_viewer.window import ViewerWindow  # noqa: E402


def _app():
    return QApplication.instance() or QApplication([])


def _window(tmp_path, write_dicom):
    _app()
    for i in range(2):
        write_dicom(f"rec{i}.dcm", frames=3, instance=i + 1, color=True)
    w = ViewerWindow()
    w.load_session(scan_session(tmp_path))
    return w


def test_set_description_updates_item_and_persists(tmp_path, write_dicom):
    w = _window(tmp_path, write_dicom)
    item = w.thumbnailList.item(0)
    w.set_description(0, "PLAX")
    assert item.text().splitlines()[0] == "PLAX"
    assert (tmp_path / FILE_NAME).exists()
    w.set_description(0, "")
    assert "PLAX" not in item.text()


def test_checkbox_toggles_item_text(tmp_path, write_dicom):
    w = _window(tmp_path, write_dicom)
    w.set_description(0, "A2C")
    w.descriptionsCheckBox.setChecked(False)
    assert "A2C" not in w.thumbnailList.item(0).text()
    w.descriptionsCheckBox.setChecked(True)
    assert "A2C" in w.thumbnailList.item(0).text()


def test_viewport_overlay_follows_checkbox(tmp_path, write_dicom):
    w = _window(tmp_path, write_dicom)
    w.set_description(0, "subcostal")
    w.thumbnailList.itemClicked.emit(w.thumbnailList.item(0))
    v = w.viewports[0]
    assert v._description.text() == "subcostal"
    assert not v._description.isHidden()
    w.descriptionsCheckBox.setChecked(False)
    assert v._description.isHidden()
    w.descriptionsCheckBox.setChecked(True)
    assert not v._description.isHidden()
    w.set_description(0, "")
    assert v._description.isHidden()


def test_descriptions_loaded_with_session(tmp_path, write_dicom):
    w = _window(tmp_path, write_dicom)
    w.set_description(1, "A4C")
    w2 = ViewerWindow()
    w2.load_session(scan_session(tmp_path))
    assert w2.thumbnailList.item(1).text().splitlines()[0] == "A4C"


def test_viewport_edit_request_opens_editor_for_its_recording(tmp_path, write_dicom, monkeypatch):
    w = _window(tmp_path, write_dicom)
    w.thumbnailList.itemClicked.emit(w.thumbnailList.item(1))
    seen = []
    monkeypatch.setattr(
        "echo_viewer.window.QInputDialog.getText",
        lambda *a, **k: (seen.append(k.get("text")) or "PLAX", True),
    )
    w.viewports[0].edit_requested.emit(w.viewports[0])
    assert w.thumbnailList.item(1).text().splitlines()[0] == "PLAX"
    assert w.viewports[0]._description.text() == "PLAX"
    assert seen == [""]


def test_viewport_double_click_emits_edit_requested(tmp_path, write_dicom, monkeypatch):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    w = _window(tmp_path, write_dicom)
    monkeypatch.setattr(
        "echo_viewer.window.QInputDialog.getText", lambda *a, **k: ("", False)
    )
    w.thumbnailList.itemClicked.emit(w.thumbnailList.item(0))
    v = w.viewports[0]
    got = []
    v.edit_requested.connect(got.append)
    pos = QPointF(5, 5)
    ev = QMouseEvent(
        QEvent.Type.MouseButtonDblClick, pos, pos, Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    v.eventFilter(v._plot.viewport(), ev)
    assert got == [v]
    v.clear()
    v.eventFilter(v._plot.viewport(), ev)
    assert got == [v]


def _visible(w):
    return [
        i for i in range(w.thumbnailList.count()) if not w.thumbnailList.item(i).isHidden()
    ]


def test_description_filter_substring_case_insensitive(tmp_path, write_dicom):
    w = _window(tmp_path, write_dicom)
    w.set_description(0, "Parasternal PLAX")
    w.set_description(1, "A2C")
    assert _visible(w) == [0, 1]
    w.descriptionFilterEdit.setText("plax")
    assert _visible(w) == [0]
    w.descriptionFilterEdit.setText("zzz")
    assert _visible(w) == []


def test_description_filter_clear_restores(tmp_path, write_dicom):
    w = _window(tmp_path, write_dicom)
    w.set_description(0, "PLAX")
    w.descriptionFilterEdit.setText("PLAX")
    assert _visible(w) == [0]
    w.descriptionFilterEdit.clear()
    assert _visible(w) == [0, 1]


def test_description_filter_works_with_checkbox_off(tmp_path, write_dicom):
    w = _window(tmp_path, write_dicom)
    w.set_description(0, "PLAX")
    w.descriptionsCheckBox.setChecked(False)
    w.descriptionFilterEdit.setText("plax")
    assert _visible(w) == [0]


def test_description_filter_refreshes_after_edit(tmp_path, write_dicom):
    w = _window(tmp_path, write_dicom)
    w.descriptionFilterEdit.setText("a4c")
    assert _visible(w) == []
    w.set_description(1, "A4C")
    assert _visible(w) == [1]
    w.set_description(1, "")
    assert _visible(w) == []


def test_description_filter_ands_with_type_combo(tmp_path, write_dicom):
    w = _window(tmp_path, write_dicom)
    w.set_description(0, "PLAX")
    w.descriptionFilterEdit.setText("plax")
    w.filterCombo.setCurrentIndex(2)  # stills only; recordings are loops
    assert _visible(w) == []
    w.filterCombo.setCurrentIndex(1)
    assert _visible(w) == [0]


def test_escape_clears_description_filter(tmp_path, write_dicom):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    w = _window(tmp_path, write_dicom)
    w.descriptionFilterEdit.setText("x")
    ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(w.descriptionFilterEdit, ev)
    assert w.descriptionFilterEdit.text() == ""
