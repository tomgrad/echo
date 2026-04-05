import sys
import xml.etree.ElementTree as ET
import importlib
from pathlib import Path
from contextlib import redirect_stderr, redirect_stdout
import io
import numpy as np
import pydicom
from PySide6.QtCore import QStringListModel, QTimer
from PySide6.QtWidgets import QApplication, QMainWindow, QFileDialog, QMessageBox, QProgressBar

from medseg2 import MedSeg2Segmenter
from ui_mainwindow import Ui_MainWindow

FRAMES_LIMIT = 100 # Max frames to load from a DICOM (for testing)


class MainWindow(QMainWindow, Ui_MainWindow):

    def __init__(self):
        super().__init__()
        self.setupUi(self)
        self.checkpoints_root_dir = Path(__file__).resolve().parent / "checkpoints"
        self.medsam2_checkpoints_dir = self.checkpoints_root_dir / "MedSAM2"
        self.sam2_checkpoints_dir = self.checkpoints_root_dir / "SAM2"

        self.pixel_array = None
        self.dicom_dataset = None
        self.dicom_file_path = None
        self.key_frames = []
        # key_frame_points: frame_index -> list of [x, y, positive(bool)]
        self.key_frame_points = {}
        self.segmentation_mask = None
        self.segmentation_contours = None
        self.segmenter = None
        self.key_frames_model = QStringListModel(self)
        self.keyFramesListView.setModel(self.key_frames_model)
        self.play_timer = QTimer(self)
        self.play_timer.timeout.connect(self._advance_frame)
        self.is_playing = False
        self.seg_progress_bar = QProgressBar(self)
        self.seg_progress_bar.setMinimum(0)
        self.seg_progress_bar.setMaximum(100)
        self.seg_progress_bar.setValue(0)
        self.seg_progress_bar.setTextVisible(True)
        self.seg_progress_bar.setVisible(False)
        self.statusbar.addPermanentWidget(self.seg_progress_bar)

        self.openDicomButton.clicked.connect(self.open_dicom_file)
        self.addKeyFrameButton.clicked.connect(self.add_key_frame)
        self.deleteKeyFrameButton.clicked.connect(self.delete_key_frame)
        self.keyFramesListView.clicked.connect(self.show_selected_key_frame)
        self.keyFramesListView.activated.connect(self.show_selected_key_frame)
        self.imageView.frameChanged.connect(self.refresh_point_overlay)
        self.imageView.pointClicked.connect(self.on_point_clicked)
        self.saveKeyFramesButton.clicked.connect(self.save_key_frames)
        self.loadKeyFramesButton.clicked.connect(self.load_key_frames)
        self.playButton.clicked.connect(self.toggle_playback)
        self.segSingleButton.clicked.connect(self.segment_selected_keyframe)
        self.segRangeButton.clicked.connect(self.segment_keyframe_forward)
        self.segBackRangeButton.clicked.connect(self.segment_keyframe_backward)
        self.segAllButton.clicked.connect(self.segment_all_frames)
        self.fixMasksButton.clicked.connect(self.fix_masks)
        self.contoursButton.clicked.connect(self.find_external_contours)
        self.hidePointsCheckBox.stateChanged.connect(self._update_overlay_visibility)
        self.hideMasksCheckBox.stateChanged.connect(self._update_overlay_visibility)
        self.hideContoursCheckBox.stateChanged.connect(self._update_overlay_visibility)
        self.hideframesCheckBox.stateChanged.connect(self._update_overlay_visibility)
        self.hideHistogramCheckBox.stateChanged.connect(self._update_overlay_visibility)
        self.fpsSpinBox.valueChanged.connect(self._update_play_timer_interval)
        self.lineWidthSpinBox.valueChanged.connect(self._update_contour_width)
        self.checkpointsComboBox.currentIndexChanged.connect(self._on_checkpoint_changed)
        self._populate_checkpoints_combo()
        self._update_play_timer_interval(self.fpsSpinBox.value())
        self._update_contour_width(self.lineWidthSpinBox.value())
        self._update_overlay_visibility()
        self.show_status("Ready", 3000)

    def show_status(self, message, timeout_ms=4000):
        self.statusbar.showMessage(message, timeout_ms)

    def _start_segmentation_progress(self, message):
        self.seg_progress_bar.setRange(0, 100)
        self.seg_progress_bar.setValue(0)
        self.seg_progress_bar.setFormat("0%")
        self.seg_progress_bar.setVisible(True)
        self.statusbar.showMessage(message, 0)
        QApplication.processEvents()

    def _update_segmentation_progress(self, done, total, stage):
        total = max(1, int(total))
        done = max(0, min(int(done), total))
        percent = int((done * 100) / total)
        self.seg_progress_bar.setValue(percent)
        self.seg_progress_bar.setFormat(f"{percent}%")
        self.statusbar.showMessage(f"{stage}: {done}/{total}", 0)
        QApplication.processEvents()

    def _finish_segmentation_progress(self, message):
        self.seg_progress_bar.setValue(100)
        self.seg_progress_bar.setFormat("100%")
        self.statusbar.showMessage(message, 4000)
        QApplication.processEvents()
        self.seg_progress_bar.setVisible(False)

    def _populate_checkpoints_combo(self):
        checkpoint_paths = sorted(
            self.medsam2_checkpoints_dir.glob("MedSAM2*.pt"),
            key=lambda path: path.name.lower(),
        )
        default_name = "MedSAM2_latest.pt"

        self.checkpointsComboBox.blockSignals(True)
        self.checkpointsComboBox.clear()

        if not checkpoint_paths:
            self.checkpointsComboBox.setEnabled(False)
            self.checkpointsComboBox.blockSignals(False)
            self.show_status("No MedSAM2 checkpoints found in checkpoints/MedSAM2/.", 6000)
            return

        for checkpoint_path in checkpoint_paths:
            self.checkpointsComboBox.addItem(checkpoint_path.name, str(checkpoint_path))

        default_index = next(
            (index for index, path in enumerate(checkpoint_paths) if path.name == default_name),
            0,
        )
        self.checkpointsComboBox.setCurrentIndex(default_index)
        self.checkpointsComboBox.setEnabled(True)
        self.checkpointsComboBox.blockSignals(False)
        self._on_checkpoint_changed(emit_status=False)

    def _selected_checkpoint_path(self):
        checkpoint_path = self.checkpointsComboBox.currentData()
        if not checkpoint_path:
            return None
        return Path(checkpoint_path)

    def _on_checkpoint_changed(self, _index=None, emit_status=True):
        checkpoint_path = self._selected_checkpoint_path()
        self.segmenter = None
        if emit_status and checkpoint_path is not None:
            self.show_status(f"Selected checkpoint: {checkpoint_path.name}", 4000)

  

    def add_key_frame(self):
        if self.pixel_array is None:
            self.show_status("Open a DICOM file first.")
            return

        current_frame = self.imageView.currentIndex
        if current_frame not in self.key_frames:
            self.key_frames.append(current_frame)
            self.key_frames.sort()
            self.refresh_key_frames_list()
            self.show_status(f"Added key frame: {current_frame}")
        else:
            self.show_status(f"Key frame {current_frame} already exists.")

    def delete_key_frame(self):
        selected_indexes = self.keyFramesListView.selectedIndexes()
        if not selected_indexes:
            self.show_status("Select a key frame to delete.")
            return

        selected_frame = self._frame_from_list_index(selected_indexes[0])
        if selected_frame is None:
            self.show_status("Could not parse selected key frame.")
            return
        self.key_frames.remove(selected_frame)
        self.key_frame_points.pop(selected_frame, None)
        self.refresh_key_frames_list()
        self.refresh_point_overlay()
        self.show_status(f"Deleted key frame: {selected_frame}")

    def on_point_clicked(self, x, y, action):
        frame = self.imageView.currentIndex
        if frame not in self.key_frames:
            self.show_status("Current frame is not a key frame.")
            return

        if action == "delete":
            self._remove_nearest_point(frame, x, y)
        else:
            positive = (action == "positive")
            self.key_frame_points.setdefault(frame, []).append([x, y, positive])
            point_type = "positive" if positive else "negative"
            self.show_status(f"Added {point_type} point at ({x}, {y}) on frame {frame}")

        self.refresh_key_frames_list()
        self.refresh_point_overlay()

    def _remove_nearest_point(self, frame, x, y):
        points = self.key_frame_points.get(frame, [])
        if not points:
            self.show_status("No points to remove on this key frame.")
            return
        closest = min(points, key=lambda p: (p[0] - x) ** 2 + (p[1] - y) ** 2)
        points.remove(closest)
        self.show_status(f"Removed point at ({closest[0]}, {closest[1]}) from frame {frame}")

    def refresh_point_overlay(self, frame=None):
        if frame is None:
            frame = self.imageView.currentIndex
        points = self.key_frame_points.get(frame, [])
        pos_pts = [(p[0], p[1]) for p in points if p[2]]
        neg_pts = [(p[0], p[1]) for p in points if not p[2]]
        self.imageView.set_points(pos_pts, neg_pts)
        frame_mask = None
        if self.segmentation_mask is not None and 0 <= frame < self.segmentation_mask.shape[0]:
            frame_mask = self.segmentation_mask[frame]
        self.imageView.set_mask(frame_mask)
        frame_contours = []
        if self.segmentation_contours is not None:
            frame_contours = self.segmentation_contours.get(frame, [])
        self.imageView.set_contours(frame_contours)

    def _update_overlay_visibility(self):
        show_points = not self.hidePointsCheckBox.isChecked()
        show_masks = not self.hideMasksCheckBox.isChecked()
        show_contours = not self.hideContoursCheckBox.isChecked()
        show_frames = not self.hideframesCheckBox.isChecked()
        show_histogram = not self.hideHistogramCheckBox.isChecked()
        self.imageView.set_points_visible(show_points)
        self.imageView.set_mask_visible(show_masks)
        self.imageView.set_contours_visible(show_contours)
        self.imageView.set_frame_visible(show_frames)
        self.imageView.set_histogram_visible(show_histogram)

    def _frame_count(self):
        if self.pixel_array is None:
            return 0
        return self.pixel_array.shape[0] if self.pixel_array.ndim > 2 else 1

    def _update_play_timer_interval(self, fps):
        interval_ms = max(1, int(1000 / max(1, fps)))
        self.play_timer.setInterval(interval_ms)

    def _update_contour_width(self, width):
        self.imageView.set_contour_width(int(width))

    def toggle_playback(self):
        if self.is_playing:
            self.stop_playback()
            return
        if self._frame_count() <= 1:
            self.show_status("Load a multi-frame DICOM to play.")
            return
        self.play_timer.start()
        self.is_playing = True
        self.playButton.setText("Pause")
        self.show_status(f"Playback started ({self.fpsSpinBox.value()} FPS)")

    def stop_playback(self):
        was_playing = self.is_playing
        self.play_timer.stop()
        self.is_playing = False
        self.playButton.setText("Play")
        if was_playing:
            self.show_status("Playback paused")

    def _advance_frame(self):
        frame_count = self._frame_count()
        if frame_count <= 1:
            self.stop_playback()
            return
        next_frame = (self.imageView.currentIndex + 1) % frame_count
        self.imageView.setCurrentIndex(next_frame)

    def show_selected_key_frame(self, model_index):
        frame_index = self._frame_from_list_index(model_index)
        if frame_index is None:
            self.show_status("Could not parse selected key frame.")
            return

        if self.pixel_array is None:
            return

        frame_count = self._frame_count()
        if not 0 <= frame_index < frame_count:
            self.show_status(f"Frame index out of range: {frame_index}")
            return

        self.imageView.setCurrentIndex(frame_index)
        self.show_status(f"Showing key frame: {frame_index}")

    def refresh_key_frames_list(self):
        labels = []
        for frame in self.key_frames:
            points = self.key_frame_points.get(frame, [])
            positives = sum(1 for p in points if p[2])
            negatives = sum(1 for p in points if not p[2])
            labels.append(f"{frame} ({positives} / {negatives})")
        self.key_frames_model.setStringList(labels)

    def _frame_from_list_index(self, model_index):
        text = str(model_index.data())
        try:
            return int(text.split(" ", 1)[0])
        except (ValueError, IndexError):
            return None

    def save_key_frames(self):
        if not self.key_frames:
            QMessageBox.information(self, "Save key frames", "No key frames to save.")
            return
        suggested = (
            str(Path(self.dicom_file_path).with_suffix(".xml"))
            if self.dicom_file_path else ""
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "Save key frames", suggested, "XML files (*.xml)"
        )
        if not path:
            return
        root = ET.Element("keyframes")
        for frame_idx in self.key_frames:
            kf_el = ET.SubElement(root, "keyframe", index=str(frame_idx))
            for pt in self.key_frame_points.get(frame_idx, []):
                ET.SubElement(
                    kf_el, "point",
                    x=str(pt[0]), y=str(pt[1]),
                    positive=("true" if pt[2] else "false"),
                )
        tree = ET.ElementTree(root)
        ET.indent(tree, space="  ")
        tree.write(path, encoding="unicode", xml_declaration=True)
        self.show_status(f"Saved key frames to {path}", 6000)

    def load_key_frames(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load key frames", "", "XML files (*.xml)"
        )
        if not path:
            return
        try:
            tree = ET.parse(path)
        except ET.ParseError as exc:
            QMessageBox.critical(self, "Load error", f"Could not parse file:\n{exc}")
            return
        root = tree.getroot()
        if root.tag != "keyframes":
            QMessageBox.critical(self, "Load error", "Not a valid key frames file.")
            return
        self.key_frames.clear()
        self.key_frame_points.clear()
        for kf_el in root.findall("keyframe"):
            frame_idx = int(kf_el.get("index"))
            self.key_frames.append(frame_idx)
            pts = []
            for pt_el in kf_el.findall("point"):
                pts.append([
                    int(pt_el.get("x")),
                    int(pt_el.get("y")),
                    pt_el.get("positive") == "true",
                ])
            if pts:
                self.key_frame_points[frame_idx] = pts
        self.key_frames.sort()
        self.refresh_key_frames_list()
        self.refresh_point_overlay()
        self.show_status(f"Loaded {len(self.key_frames)} key frame(s) from {path}", 6000)

    def _ensure_segmenter(self):
        checkpoint_path = self._selected_checkpoint_path()
        if checkpoint_path is None:
            raise RuntimeError(
                "No MedSAM2 checkpoint selected. Add MedSAM2*.pt files to checkpoints/MedSAM2/."
            )
        if self.segmenter is None:
            self.segmenter = MedSeg2Segmenter(checkpoint_path=str(checkpoint_path))

    def _ensure_ready_for_segmentation(self):
        if self.pixel_array is None or self.dicom_dataset is None:
            self.show_status("Load a DICOM file before segmentation.")
            return False
        if not self.key_frames:
            self.show_status("Add key frames before segmentation.")
            return False
        return True

    def _validate_points_for_frame(self, frame_idx):
        points = self.key_frame_points.get(frame_idx, [])
        if not points:
            self.show_status(f"Key frame {frame_idx} has no prompt points.")
            return None
        return points

    def _selected_key_frame(self):
        selected_indexes = self.keyFramesListView.selectedIndexes()
        if not selected_indexes:
            return None
        return self._frame_from_list_index(selected_indexes[0])

    def _merge_mask(self, new_mask, start_frame, end_frame):
        """Copy frames [start_frame, end_frame] from new_mask into the existing mask."""
        if self.segmentation_mask is None or self.segmentation_mask.shape != new_mask.shape:
            self.segmentation_mask = np.zeros_like(new_mask)
        self.segmentation_mask[start_frame:end_frame + 1] = new_mask[start_frame:end_frame + 1]

    def segment_selected_keyframe(self):
        if not self._ensure_ready_for_segmentation():
            return

        frame_idx = self._selected_key_frame()
        if frame_idx is None:
            self.show_status("Select a key frame for single-frame segmentation.")
            return
        points = self._validate_points_for_frame(frame_idx)
        if points is None:
            return

        try:
            self._ensure_segmenter()
            self._start_segmentation_progress("Running single-frame segmentation...")
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                mask = self.segmenter.segment_single_keyframe(
                    pixel_array=self.pixel_array,
                    dicom_ds=self.dicom_dataset,
                    frame_idx=frame_idx,
                    frame_points=points,
                    progress_callback=self._update_segmentation_progress,
                )
            self._finish_segmentation_progress("Single-frame segmentation done. Mask overlay updated.")
        except Exception as exc:
            self.seg_progress_bar.setVisible(False)
            QMessageBox.critical(self, "Segmentation error", str(exc))
            return

        self._merge_mask(mask, frame_idx, frame_idx)
        self.segmentation_contours = None
        self.refresh_point_overlay()

    def segment_keyframe_forward(self):
        if not self._ensure_ready_for_segmentation():
            return

        frame_idx = self._selected_key_frame()
        if frame_idx is None:
            self.show_status("Select a start key frame for forward segmentation.")
            return
        points = self._validate_points_for_frame(frame_idx)
        if points is None:
            return

        sorted_kf = sorted(self.key_frames)
        start_pos = sorted_kf.index(frame_idx)
        end_frame = (
            sorted_kf[start_pos + 1]
            if start_pos + 1 < len(sorted_kf)
            else self._frame_count() - 1
        )

        try:
            self._ensure_segmenter()
            self._start_segmentation_progress("Running forward range segmentation...")
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                mask = self.segmenter.segment_forward_range(
                    pixel_array=self.pixel_array,
                    dicom_ds=self.dicom_dataset,
                    start_frame_idx=frame_idx,
                    end_frame_idx=end_frame,
                    start_frame_points=points,
                    progress_callback=self._update_segmentation_progress,
                )
            self._finish_segmentation_progress(
                f"Forward segmentation done ({frame_idx}->{end_frame}). Mask overlay updated."
            )
        except Exception as exc:
            self.seg_progress_bar.setVisible(False)
            QMessageBox.critical(self, "Segmentation error", str(exc))
            return

        self._merge_mask(mask, frame_idx, end_frame)
        self.segmentation_contours = None
        self.refresh_point_overlay()

    def segment_keyframe_backward(self):
        if not self._ensure_ready_for_segmentation():
            return

        frame_idx = self._selected_key_frame()
        if frame_idx is None:
            self.show_status("Select a start key frame for backward segmentation.")
            return
        points = self._validate_points_for_frame(frame_idx)
        if points is None:
            return

        sorted_kf = sorted(self.key_frames)
        start_pos = sorted_kf.index(frame_idx)
        end_frame = (
            sorted_kf[start_pos - 1]
            if start_pos > 0
            else 0
        )

        try:
            self._ensure_segmenter()
            self._start_segmentation_progress("Running backward range segmentation...")
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                mask = self.segmenter.segment_backward_range(
                    pixel_array=self.pixel_array,
                    dicom_ds=self.dicom_dataset,
                    start_frame_idx=frame_idx,
                    end_frame_idx=end_frame,
                    start_frame_points=points,
                    progress_callback=self._update_segmentation_progress,
                )
            self._finish_segmentation_progress(
                f"Backward segmentation done ({frame_idx}->{end_frame}). Mask overlay updated."
            )
        except Exception as exc:
            self.seg_progress_bar.setVisible(False)
            QMessageBox.critical(self, "Segmentation error", str(exc))
            return

        self._merge_mask(mask, end_frame, frame_idx)
        self.segmentation_contours = None
        self.refresh_point_overlay()

    def segment_all_frames(self):
        if not self._ensure_ready_for_segmentation():
            return

        missing_points = [f for f in sorted(self.key_frames) if not self.key_frame_points.get(f)]
        if missing_points:
            self.show_status(f"These key frames have no points: {missing_points}")
            return

        try:
            self._ensure_segmenter()
            self._start_segmentation_progress("Running all-frames segmentation...")
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                mask = self.segmenter.segment_all_with_keyframes(
                    pixel_array=self.pixel_array,
                    dicom_ds=self.dicom_dataset,
                    key_frames=self.key_frames,
                    key_frame_points=self.key_frame_points,
                    progress_callback=self._update_segmentation_progress,
                )
            self._finish_segmentation_progress("All-frame segmentation done. Mask overlay updated.")
        except Exception as exc:
            self.seg_progress_bar.setVisible(False)
            QMessageBox.critical(self, "Segmentation error", str(exc))
            return

        self.segmentation_mask = mask
        self.segmentation_contours = None
        self.refresh_point_overlay()

    def fix_masks(self):
        if self.segmentation_mask is None:
            self.show_status("No segmentation mask available. Run segmentation first.")
            return

        try:
            ndimage = importlib.import_module("scipy.ndimage")
        except Exception:
            QMessageBox.critical(
                self,
                "Missing dependency",
                "scipy is required for mask fixing. Install dependencies from requirements.txt.",
            )
            return

        iterations = int(self.smoothSpinBox.value())
        self._start_segmentation_progress("Fixing masks...")

        def _fix_single_mask(mask_2d):
            # 1) fill holes, 2) erode, 3) dilate
            fixed = ndimage.binary_fill_holes(mask_2d)
            fixed = ndimage.binary_erosion(fixed, iterations=iterations)
            fixed = ndimage.binary_dilation(fixed, iterations=iterations)
            return fixed.astype(np.uint8)

        mask = self.segmentation_mask.astype(bool)
        if mask.ndim == 2:
            self._update_segmentation_progress(0, 1, "Fixing masks")
            fixed_mask = _fix_single_mask(mask)
            self._update_segmentation_progress(1, 1, "Fixing masks")
        elif mask.ndim == 3:
            fixed_mask = np.zeros_like(self.segmentation_mask, dtype=np.uint8)
            total = mask.shape[0]
            for frame_idx in range(mask.shape[0]):
                fixed_mask[frame_idx] = _fix_single_mask(mask[frame_idx])
                self._update_segmentation_progress(frame_idx + 1, total, "Fixing masks")
        else:
            self.seg_progress_bar.setVisible(False)
            self.show_status(f"Unsupported mask shape: {self.segmentation_mask.shape}")
            return

        self.segmentation_mask = fixed_mask
        self.segmentation_contours = None
        self.refresh_point_overlay()
        self._finish_segmentation_progress(f"Mask fixing complete (smooth level: {iterations}).")

    def find_external_contours(self):
        if self.segmentation_mask is None:
            self.show_status("No segmentation mask available. Run segmentation first.")
            return

        try:
            cv2 = importlib.import_module("cv2")
        except Exception:
            QMessageBox.critical(
                self,
                "Missing dependency",
                "opencv-python is required for contours. Install dependencies from requirements.txt.",
            )
            return

        mask = self.segmentation_mask.astype(np.uint8)
        contour_map = {}
        epsilon = float(self.epsilonSpinBox.value())
        use_approx = epsilon > 0.0

        def _extract_from_frame(mask_2d):
            frame_mask = (mask_2d > 0).astype(np.uint8)
            found = cv2.findContours(frame_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
            contours = found[0] if len(found) == 2 else found[1]
            out = []
            for contour in contours:
                if use_approx:
                    contour = cv2.approxPolyDP(contour, epsilon, True)
                pts = contour.reshape(-1, 2)
                if pts.shape[0] > 1:
                    out.append(pts)
            return out

        if mask.ndim == 2:
            contour_map[0] = _extract_from_frame(mask)
        elif mask.ndim == 3:
            for frame_idx in range(mask.shape[0]):
                contour_map[frame_idx] = _extract_from_frame(mask[frame_idx])
        else:
            self.show_status(f"Unsupported mask shape: {self.segmentation_mask.shape}")
            return

        self.segmentation_contours = contour_map
        color = (255, 255, 0, 255)
        self.imageView.set_contour_color(color)
        self.refresh_point_overlay()
        if use_approx:
            self.show_status(f"External contours extracted (approxPolyDP, epsilon={epsilon:g}).", 5000)
        else:
            self.show_status("External contours extracted (no approximation).", 5000)

    def open_dicom_file(self):
        file_dialog = QFileDialog(self)
        file_dialog.setNameFilter("DICOM files (*)")
        if file_dialog.exec():
            selected_files = file_dialog.selectedFiles()
            if selected_files:
                dicom_file_path = selected_files[0]
                self.dicom_file_path = dicom_file_path
                dicom = pydicom.dcmread(dicom_file_path)
                self.dicom_dataset = dicom
                pixel_array = dicom.pixel_array
                if pixel_array.ndim > 2 and pixel_array.shape[0] > FRAMES_LIMIT:
                    pixel_array = pixel_array[:FRAMES_LIMIT]
                self.pixel_array = pixel_array
                self.segmentation_mask = None
                self.segmentation_contours = None
                self.stop_playback()
                self.imageView.setImage(self.pixel_array)
                self.imageView.set_mask(None)
                self.imageView.set_contours([])
                self.key_frames.clear()
                self.key_frame_points.clear()
                self.refresh_key_frames_list()
                self.refresh_point_overlay()
                self.show_status(f"Loaded DICOM: {dicom_file_path}", 6000)


app = QApplication(sys.argv)
window = MainWindow()
window.show()
app.exec()