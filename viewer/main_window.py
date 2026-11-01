from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
)

from viewer.session import Session, recording_label, scan_session
from viewer.thumbnails import ThumbnailProvider
from viewer.ui_viewer_window import Ui_ViewerWindow


class ScanWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, folder: Path, parent=None):
        super().__init__(parent)
        self._folder = folder

    def run(self):
        try:
            session = scan_session(self._folder)
        except Exception as exc:
            self.failed.emit(str(exc) or type(exc).__name__)
            return
        self.succeeded.emit(session)


class ViewerWindow(QMainWindow, Ui_ViewerWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.session: Session | None = None
        self._items_by_path: dict[Path, QListWidgetItem] = {}
        self._scan_worker: ScanWorker | None = None
        self._thumbnails = ThumbnailProvider(self)
        self._thumbnails.thumbnail_ready.connect(self._on_thumbnail_ready)
        self._thumbnails.thumbnail_failed.connect(self._on_thumbnail_failed)
        self.openSessionButton.clicked.connect(self.open_session)

    def open_session(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Open session")
        if not folder:
            return
        self.openSessionButton.setEnabled(False)
        self.statusbar.showMessage("Scanning …")
        worker = ScanWorker(Path(folder), self)
        worker.succeeded.connect(self._on_scan_succeeded)
        worker.failed.connect(self._on_scan_failed)
        self._scan_worker = worker
        worker.start()

    def _on_scan_failed(self, message: str) -> None:
        self.openSessionButton.setEnabled(True)
        self.statusbar.clearMessage()
        QMessageBox.warning(self, "Open session", message)

    def _on_scan_succeeded(self, session: Session) -> None:
        self.openSessionButton.setEnabled(True)
        if not session.recordings:
            self.statusbar.clearMessage()
            QMessageBox.information(self, "Open session", "No DICOM recordings found")
            return
        self.load_session(session)
        self.statusbar.showMessage(f"Loaded {len(session.recordings)} recordings")

    def load_session(self, session: Session) -> None:
        self.session = session
        self.thumbnailList.clear()
        self._items_by_path.clear()
        self.sessionLabel.setText(
            f"{session.folder.name} · {len(session.recordings)} recordings"
        )
        for i, info in enumerate(session.recordings):
            item = QListWidgetItem(recording_label(info, i + 1))
            item.setData(Qt.ItemDataRole.UserRole, i)
            self.thumbnailList.addItem(item)
            self._items_by_path[info.path] = item
            self._thumbnails.request(info)

    def _on_thumbnail_ready(self, path: Path, image) -> None:
        item = self._items_by_path.get(path)
        if item is None:
            return
        item.setIcon(QIcon(QPixmap.fromImage(image)))

    def _on_thumbnail_failed(self, path: Path, message: str) -> None:
        item = self._items_by_path.get(path)
        if item is None:
            return
        if not item.text().endswith(" ⚠"):
            item.setText(item.text() + " ⚠")
        item.setToolTip(message)
