from pathlib import Path

from PySide6.QtCore import QEvent, QThread, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QInputDialog,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
)

from echo_viewer.descriptions import Descriptions
from echo_viewer.frames import FrameCache, PrefetchPool
from echo_viewer.playback import PlaybackController
from echo_viewer.session import RecordingInfo, Session, recording_label, scan_session
from echo_viewer.thumbnails import ThumbnailProvider
from echo_viewer.ui.ui_viewer_window import Ui_ViewerWindow
from echo_viewer.viewport import RecordingViewport

_GRID_POSITIONS = ((0, 0), (0, 1), (1, 0), (1, 1))


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
        self.descriptions: Descriptions | None = None
        self._items_by_path: dict[Path, QListWidgetItem] = {}
        self._scan_worker: ScanWorker | None = None
        self._thumbnails = ThumbnailProvider(self)
        self._thumbnails.thumbnail_ready.connect(self._on_thumbnail_ready)
        self._thumbnails.thumbnail_failed.connect(self._on_thumbnail_failed)
        self.openSessionButton.clicked.connect(self.open_session)
        self.cache = FrameCache()
        self.prefetch = PrefetchPool(self)
        self.prefetch.loop_ready.connect(self._on_loop_ready)
        self.prefetch.loop_failed.connect(self._on_loop_failed)
        self.viewports: list[RecordingViewport] = []
        self.controller = PlaybackController(self)
        for row, col in _GRID_POSITIONS:
            viewport = RecordingViewport(self.cache)
            viewport.activated.connect(self._set_active)
            viewport.closed.connect(self._on_viewport_closed)
            viewport.edit_requested.connect(self._on_viewport_edit_requested)
            viewport.error.connect(self._on_viewport_error)
            self.gridLayout.addWidget(viewport, row, col)
            self.viewports.append(viewport)
            # add_viewport also connects viewport.scrub_requested to controller.scrub
            self.controller.add_viewport(viewport)
        self.active_viewport = self.viewports[0]
        self._set_active(self.active_viewport)
        self._apply_layout()
        self.thumbnailList.itemClicked.connect(self._on_thumbnail_clicked)
        self.thumbnailList.itemDoubleClicked.connect(self._on_thumbnail_double_clicked)
        self.thumbnailList.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.thumbnailList.customContextMenuRequested.connect(self._on_thumbnail_menu)
        self.descriptionsCheckBox.toggled.connect(self._refresh_descriptions)
        self.descriptionFilterEdit.textChanged.connect(self._apply_filter)
        self.descriptionFilterEdit.installEventFilter(self)
        self.layoutCombo.currentIndexChanged.connect(self._apply_layout)
        self.thumbnailsButton.toggled.connect(self.leftPanel.setVisible)
        self.filterCombo.currentIndexChanged.connect(self._apply_filter)
        self.playButton.clicked.connect(self._on_play_clicked)
        self.stopButton.clicked.connect(self.controller.restart)
        self.controller.state_changed.connect(self._on_playback_state)
        self.syncCheckBox.toggled.connect(self._on_sync_toggled)
        self.loopCheckBox.toggled.connect(self.controller.set_loop)

    def eventFilter(self, obj, event):
        if (
            obj is self.descriptionFilterEdit
            and event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Escape
        ):
            self.descriptionFilterEdit.clear()
            return True
        return super().eventFilter(obj, event)

    def closeEvent(self, event):
        self.controller.pause()
        for viewport in self.viewports:
            viewport.shutdown()
        worker = self._scan_worker
        if worker is not None and worker.isRunning():
            worker.requestInterruption()
            worker.wait()
        self._thumbnails.shutdown()
        self.prefetch.shutdown()
        super().closeEvent(event)

    def _on_play_clicked(self) -> None:
        if self.controller.is_playing:
            self.controller.pause()
        else:
            self.controller.play()

    def _on_playback_state(self, playing: bool) -> None:
        self.playButton.setText("Pause" if playing else "Play")

    def _on_sync_toggled(self, checked: bool) -> None:
        self.controller.set_synced(checked)
        self.statusbar.showMessage("Synced" if checked else "Independent")

    def _apply_layout(self, *_) -> None:
        for viewport in self.viewports:
            self.gridLayout.removeWidget(viewport)
            viewport.hide()
        if self.layoutCombo.currentIndex() == 0:
            self.gridLayout.addWidget(self.active_viewport, 0, 0)
            self.active_viewport.show()
            return
        for viewport, (row, col) in zip(self.viewports, _GRID_POSITIONS):
            self.gridLayout.addWidget(viewport, row, col)
            viewport.show()

    def _on_scan_thread_finished(self) -> None:
        worker = self.sender()
        if worker is None:
            return
        if worker is self._scan_worker:
            self._scan_worker = None
        worker.deleteLater()

    def open_session(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Open session")
        if not folder:
            return
        self.openSessionButton.setEnabled(False)
        self.statusbar.showMessage("Scanning …")
        worker = ScanWorker(Path(folder), self)
        worker.succeeded.connect(self._on_scan_succeeded)
        worker.failed.connect(self._on_scan_failed)
        worker.finished.connect(self._on_scan_thread_finished)
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
            QMessageBox.information(self, "Open session", "No DICOM or video recordings found")
            return
        self.load_session(session)
        self.statusbar.showMessage(f"Loaded {len(session.recordings)} recordings")

    def load_session(self, session: Session) -> None:
        self.session = session
        self.descriptions = Descriptions.load(session.folder)
        if self.descriptions.warning:
            self.statusbar.showMessage(self.descriptions.warning)
        self._reset_tiles()
        self._thumbnails.cancel_all()
        self.thumbnailList.clear()
        self._items_by_path.clear()
        self.sessionLabel.setText(
            f"{session.folder.name} · {len(session.recordings)} recordings"
        )
        for i, info in enumerate(session.recordings):
            item = QListWidgetItem(self._item_text(info, i))
            item.setData(Qt.ItemDataRole.UserRole, i)
            # The icon arrives later; without a hint the item is sized from its text alone and clips the thumbnail.
            item.setSizeHint(self.thumbnailList.gridSize())
            self.thumbnailList.addItem(item)
            self._items_by_path[info.path] = item
            self._thumbnails.request(info)
        self._apply_filter()

    def _item_text(self, info: RecordingInfo, index: int) -> str:
        text = recording_label(info, index + 1)
        description = self.descriptions.get(info) if self.descriptions else ""
        if description and self.descriptionsCheckBox.isChecked():
            text = description + "\n" + text
        return text

    def _refresh_descriptions(self, *_) -> None:
        if self.session is None:
            return
        for i, info in enumerate(self.session.recordings):
            item = self._items_by_path[info.path]
            warn = item.text().endswith(" ⚠")
            item.setText(self._item_text(info, i) + (" ⚠" if warn else ""))
        for viewport in self.viewports:
            self._push_description(viewport)

    def _push_description(self, viewport: RecordingViewport) -> None:
        info = viewport.recording
        text = self.descriptions.get(info) if info and self.descriptions else ""
        viewport.set_description(text, self.descriptionsCheckBox.isChecked())

    def set_description(self, index: int, text: str) -> None:
        if self.session is None or self.descriptions is None:
            return
        info = self.session.recordings[index]
        try:
            self.descriptions.set(info, text)
        except OSError as exc:
            self.statusbar.showMessage(f"Cannot save descriptions: {exc}")
            return
        self._refresh_descriptions()
        self._apply_filter()

    def _edit_description(self, item) -> None:
        if self.session is None or self.descriptions is None:
            return
        index = item.data(Qt.ItemDataRole.UserRole)
        info = self.session.recordings[index]
        text, ok = QInputDialog.getText(
            self, "Description", info.path.name, text=self.descriptions.get(info)
        )
        if ok:
            self.set_description(index, text)

    def _on_viewport_edit_requested(self, viewport: RecordingViewport) -> None:
        info = viewport.recording
        if info is None or self.session is None:
            return
        item = self._items_by_path.get(info.path)
        if item is not None:
            self._edit_description(item)

    def _on_thumbnail_double_clicked(self, item) -> None:
        self._edit_description(item)

    def _on_thumbnail_menu(self, pos) -> None:
        item = self.thumbnailList.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self)
        menu.addAction("Edit description…", lambda: self._edit_description(item))
        menu.exec(self.thumbnailList.viewport().mapToGlobal(pos))

    def _apply_filter(self, *_) -> None:
        """Show all rail items, only loops (index 1) or only stills (index 2); errors only under All.

        A non-empty description pattern additionally requires a case-insensitive substring match.
        """
        mode = self.filterCombo.currentIndex()
        pattern = self.descriptionFilterEdit.text().strip().casefold()
        recordings = self.session.recordings if self.session else ()
        for i, info in enumerate(recordings):
            item = self._items_by_path[info.path]
            if mode == 0:
                hidden = False
            elif info.error:
                hidden = True
            else:
                hidden = info.is_still == (mode == 1)
            if pattern and not hidden:
                description = self.descriptions.get(info) if self.descriptions else ""
                hidden = pattern not in description.casefold()
            item.setHidden(hidden)

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

    def _reset_tiles(self) -> None:
        for viewport in self.viewports:
            if viewport.recording is not None:
                self.prefetch.cancel(viewport.recording)
            viewport.clear()
        self.cache.clear()

    def _release(self, viewport: RecordingViewport) -> None:
        info = viewport.recording
        if info is None:
            return
        for other in self.viewports:
            if (
                other is not viewport
                and other.recording is not None
                and other.recording.path == info.path
            ):
                return
        self.prefetch.cancel(info)

    def _assign(self, viewport: RecordingViewport, info: RecordingInfo) -> None:
        self._release(viewport)
        viewport.set_recording(info)
        loop = self.cache.get(info.path)
        if loop is not None:
            viewport.set_loop(loop)
        else:
            self.prefetch.request(info)
        self._push_description(viewport)
        self._set_active(viewport)
        self.controller.show_current()
        self.statusbar.showMessage(f"Showing {info.path.name}")

    def _on_thumbnail_clicked(self, item) -> None:
        if self.session is None:
            return
        info = self.session.recordings[item.data(Qt.ItemDataRole.UserRole)]
        if info.error is not None:
            self.statusbar.showMessage(f"Cannot show {info.path.name}: {info.error}")
            return
        target = self.active_viewport
        if target.recording is not None:
            target = next(
                (v for v in self.viewports if v.recording is None),
                self.active_viewport,
            )
        self._assign(target, info)

    def _on_loop_ready(self, info: RecordingInfo, loop) -> None:
        self.cache.put(info.path, loop)
        for viewport in self.viewports:
            if viewport.recording is not None and viewport.recording.path == info.path:
                viewport.set_loop(loop)

    def _on_loop_failed(self, info: RecordingInfo, message: str) -> None:
        for viewport in self.viewports:
            if viewport.recording is not None and viewport.recording.path == info.path:
                viewport.mark_prefetch_failed()
        self.statusbar.showMessage(f"Prefetch failed for {info.path.name}: {message}")

    def _on_viewport_error(self, message: str) -> None:
        self.statusbar.showMessage(f"Decode error: {message}")

    def _on_viewport_closed(self, viewport: RecordingViewport) -> None:
        self._release(viewport)
        viewport.clear()
        self.controller.show_current()

    def _set_active(self, viewport: RecordingViewport) -> None:
        self.active_viewport = viewport
        for other in self.viewports:
            other.set_active(other is viewport)
        if self.layoutCombo.currentIndex() == 0:
            self._apply_layout()
