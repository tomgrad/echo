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


def test_thumbnails_button_toggles_left_panel():
    app = QApplication.instance() or QApplication([])
    window = ViewerWindow()
    window.show()
    assert window.thumbnailsButton.isChecked()
    assert window.leftPanel.isVisible()
    window.thumbnailsButton.click()
    assert not window.leftPanel.isVisible()
    window.thumbnailsButton.click()
    assert window.leftPanel.isVisible()
    window.close()
    app.processEvents()
