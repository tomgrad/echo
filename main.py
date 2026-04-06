import sys
import xml.etree.ElementTree as ET
import importlib
import traceback
import re
from pathlib import Path
from contextlib import redirect_stderr, redirect_stdout
import io
import numpy as np
import pydicom
import cv2
from scipy import ndimage
from PySide6.QtCore import QStringListModel, QTimer
from PySide6.QtWidgets import QApplication, QMainWindow, QFileDialog, QMessageBox, QProgressBar

from medseg2 import MedSam2Segmenter, Sam2Segmenter
from ui_mainwindow import Ui_MainWindow

FRAMES_LIMIT = 100  # Max frames to load from a DICOM (for testing)


class MainWindow(QMainWindow, Ui_MainWindow):

    def __init__(self):
        super().__init__()
        self.setupUi(self)
        self.checkpoints_root_dir = Path(__file__).resolve().parent / "checkpoints"
        self.medsam2_checkpoints_dir = self.checkpoints_root_dir / "MedSAM2"
        self.sam2_checkpoints_dir = self.checkpoints_root_dir / "SAM2"
        self.engine_names = {
            "medsam2": "MedSAM2",
            "sam2": "SAM2",
        }

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
        self.deleteAllKFButton.clicked.connect(self.delete_all_key_frames)
        self.keyFramesListView.clicked.connect(self.show_selected_key_frame)
        self.keyFramesListView.activated.connect(self.show_selected_key_frame)
        self.imageView.frameChanged.connect(self.refresh_point_overlay)
        self.imageView.pointClicked.connect(self.on_point_clicked)
        self.saveKeyFramesButton.clicked.connect(self.save_key_frames)
        self.loadKeyFramesButton.clicked.connect(self.load_key_frames)
        self.exportMasksButton.clicked.connect(self.save_masks)
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
        self._setup_engine_selector()
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

    def _setup_engine_selector(self):
        self.engineComboBox.addItem(self.engine_names["medsam2"], "medsam2")
        self.engineComboBox.addItem(self.engine_names["sam2"], "sam2")
        self.engineComboBox.currentIndexChanged.connect(self._on_engine_changed)

    def _selected_engine_key(self):
        key = self.engineComboBox.currentData()
        return key if key in self.engine_names else "medsam2"

    def _current_engine_name(self):
        return self.engine_names[self._selected_engine_key()]

    def _checkpoint_candidates_for_engine(self, engine_key):
        if engine_key == "sam2":
            # SAM2 folder may include shell scripts; only keep checkpoint files.
            matches = list(self.sam2_checkpoints_dir.glob("sam2*.pt"))
            matches += list(self.sam2_checkpoints_dir.glob("SAM2*.pt"))
            return sorted(set(matches), key=lambda path: path.name.lower())
        return sorted(self.medsam2_checkpoints_dir.glob("MedSAM2*.pt"), key=lambda path: path.name.lower())

    @staticmethod
    def _default_checkpoint_name_for_engine(engine_key):
        if engine_key == "sam2":
            return "sam2.1_hiera_tiny.pt"
        return "MedSAM2_latest.pt"

    def _is_checkpoint_compatible(self, engine_key, checkpoint_path):
        checkpoint_name = checkpoint_path.name
        if engine_key == "sam2":
            return checkpoint_path.parent == self.sam2_checkpoints_dir and checkpoint_name.lower().startswith("sam2")
        return checkpoint_path.parent == self.medsam2_checkpoints_dir and checkpoint_name.startswith("MedSAM2")

    def _checkpoint_hint_for_engine(self, engine_key):
        if engine_key == "sam2":
            return "sam2*.pt files in checkpoints/SAM2/."
        return "MedSAM2*.pt files in checkpoints/MedSAM2/."

    @staticmethod
    def _sam2_package_dir():
        try:
            sam2_mod = importlib.import_module("sam2")
            return Path(sam2_mod.__file__).resolve().parent
        except Exception:
            return None

    @staticmethod
    def _hiera_variant_from_checkpoint(checkpoint_path):
        name = checkpoint_path.name.lower()
        # MedSAM2-specific checkpoint names.
        if "efficienttam_s" in name:
            return "s"
        if "efficienttam_ti" in name:
            return "t"

        # Common SAM2 family naming patterns.
        if "hiera_tiny" in name or name.endswith("_ti.pt"):
            return "t"
        if "hiera_large" in name:
            return "l"
        if "hiera_base_plus" in name:
            return "b+"
        if "hiera_small" in name:
            return "s"
        return "t"

    @staticmethod
    def _sam2_config_candidate_for_variant(variant):
        # Requested SAM2 config family: sam2.1_hiera_{t|s|b+}.yaml
        if variant == "s":
            suffix = "s"
        elif variant == "b+":
            suffix = "b+"
        else:
            suffix = "t"
        return f"configs/sam2.1_hiera_{suffix}.yaml"

    @classmethod
    def _sam2_config_exists(cls, config_rel_path):
        package_dir = cls._sam2_package_dir()
        if package_dir is None:
            return False
        return (package_dir / config_rel_path).exists()

    @classmethod
    def _available_sam2_configs(cls):
        package_dir = cls._sam2_package_dir()
        if package_dir is None:
            return []
        return sorted(str(path.relative_to(package_dir)) for path in package_dir.rglob("*.yaml"))

    @classmethod
    def _model_cfg_for_selection(cls, engine_key, checkpoint_path):
        variant = cls._hiera_variant_from_checkpoint(checkpoint_path)

        if engine_key == "medsam2":
            candidate = "configs/sam2.1_hiera_t512.yaml"
            if cls._sam2_config_exists(candidate):
                return candidate

            package_dir = cls._sam2_package_dir()
            available = cls._available_sam2_configs()
            raise RuntimeError(
                "Selected MedSAM2 checkpoint requires configs/sam2.1_hiera_t512.yaml in the "
                "installed sam2 package, but it was not found. "
                f"Imported sam2 package path: {package_dir}. "
                f"Available configs in installed package: {available}"
            )

        # For SAM2 engine: prefer the standard sam2.1 layout.
        candidate = cls._sam2_config_candidate_for_variant(variant)

        if cls._sam2_config_exists(candidate):
            return candidate

        package_dir = cls._sam2_package_dir()
        available = cls._available_sam2_configs()
        raise RuntimeError(
            "Selected SAM2 checkpoint requires SAM2 configs (configs/sam2.1/*.yaml) "
            "inside the installed sam2 package, but they were not found. "
            "If you are using the MedSAM2 fork only, copy the SAM2 config files into that package. "
            f"Imported sam2 package path: {package_dir}. "
            f"Available configs in installed package: {available}"
        )

    @classmethod
    def _image_size_for_model_cfg(cls, model_cfg):
        # Prefer explicit image_size declared in YAML when available.
        package_dir = cls._sam2_package_dir()
        if package_dir is not None:
            cfg_path = package_dir / model_cfg
            if cfg_path.exists():
                try:
                    text = cfg_path.read_text(encoding="utf-8", errors="ignore")
                    match = re.search(r"^\s*image_size\s*:\s*(\d+)\s*$", text, flags=re.MULTILINE)
                    if match:
                        return int(match.group(1))
                except Exception:
                    pass

        # Fallback heuristic from file naming.
        if "512" in model_cfg:
            return 512
        return 1024

    def _create_segmenter_for_selection(self, engine_key, checkpoint_path):
        model_cfg = self._model_cfg_for_selection(engine_key, checkpoint_path)
        if engine_key == "sam2":
            image_size = self._image_size_for_model_cfg(model_cfg)
            return Sam2Segmenter(
                checkpoint_path=str(checkpoint_path),
                model_cfg=model_cfg,
                image_size=image_size,
            )
        # Keep MedSAM2 preprocessing at 512 to preserve historical behavior.
        image_size = 512
        return MedSam2Segmenter(
            checkpoint_path=str(checkpoint_path),
            model_cfg=model_cfg,
            image_size=image_size,
        )

    def _on_engine_changed(self, _index=None):
        self.segmenter = None
        self._populate_checkpoints_combo()
        self.show_status(f"Selected engine: {self._current_engine_name()}", 4000)

    def _populate_checkpoints_combo(self):
        engine_key = self._selected_engine_key()
        checkpoint_paths = self._checkpoint_candidates_for_engine(engine_key)
        default_name = self._default_checkpoint_name_for_engine(engine_key)
        checkpoints_dir = self.sam2_checkpoints_dir if engine_key == "sam2" else self.medsam2_checkpoints_dir

        self.checkpointsComboBox.blockSignals(True)
        self.checkpointsComboBox.clear()

        if not checkpoint_paths:
            self.checkpointsComboBox.setEnabled(False)
            self.checkpointsComboBox.blockSignals(False)
            self.show_status(
                f"No {self._current_engine_name()} checkpoints found in {checkpoints_dir.as_posix()}/.",
                6000,
            )
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
            self.show_status(
                f"Selected {self._current_engine_name()} checkpoint: {checkpoint_path.name}",
                4000,
            )

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

    def delete_all_key_frames(self):
        if not self.key_frames:
            self.show_status("No key frames to delete.")
            return

        count = len(self.key_frames)
        self.key_frames.clear()
        self.key_frame_points.clear()
        self.keyFramesListView.clearSelection()
        self.refresh_key_frames_list()
        self.refresh_point_overlay()
        self.show_status(f"Deleted all key frames ({count}).")

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
            if frame_idx not in self.key_frames:
                self.key_frames.append(frame_idx)
            pts = []
            for pt_el in kf_el.findall("point"):
                pts.append([
                    int(pt_el.get("x")),
                    int(pt_el.get("y")),
                    pt_el.get("positive") == "true",
                ])
            if pts:
                self.key_frame_points.setdefault(frame_idx, []).extend(pts)
        self.key_frames.sort()
        self.refresh_key_frames_list()
        self.refresh_point_overlay()
        self.show_status(f"Loaded {len(self.key_frames)} key frame(s) from {path}", 6000)

    def save_masks(self):
        if self.segmentation_mask is None:
            self.show_status("No segmentation mask available. Run segmentation first.")
            return

        if self.dicom_file_path:
            dicom_stem = Path(self.dicom_file_path).stem
        else:
            dicom_stem = "dicom"

        output_dir = Path(__file__).resolve().parent / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{dicom_stem}_mask.npy"

        np.save(output_path, self.segmentation_mask.astype(np.uint8))
        self.show_status(f"Saved masks to {output_path}", 6000)

    def _ensure_segmenter(self):
        engine_key = self._selected_engine_key()
        checkpoint_path = self._selected_checkpoint_path()
        if checkpoint_path is None:
            raise RuntimeError(
                f"No {self._current_engine_name()} checkpoint selected. Add {self._checkpoint_hint_for_engine(engine_key)}"
            )

        if not checkpoint_path.exists():
            raise RuntimeError(f"Selected checkpoint does not exist: {checkpoint_path}")

        if not self._is_checkpoint_compatible(engine_key, checkpoint_path):
            raise RuntimeError(
                f"Selected checkpoint is not compatible with {self._current_engine_name()}. "
                f"Use {self._checkpoint_hint_for_engine(engine_key)}"
            )

        if self.segmenter is None:
            self.segmenter = self._create_segmenter_for_selection(engine_key, checkpoint_path)

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

    @staticmethod
    def _format_segmentation_error(exc, stdout_text="", stderr_text="", traceback_text=""):
        base_message = str(exc).strip()
        if not base_message:
            base_message = f"{exc.__class__.__name__} (no message)"

        details = stderr_text.strip() or stdout_text.strip() or traceback_text.strip()
        if not details:
            return base_message

        # Keep dialog readable and bounded for large backend traces.
        details_tail = details[-4000:]
        return f"{base_message}\n\nBackend details:\n{details_tail}"

    def _run_segmentation(self, start_message, finish_message, segment_fn):
        try:
            self._ensure_segmenter()
            self._start_segmentation_progress(start_message)
            out_buf = io.StringIO()
            err_buf = io.StringIO()
            with redirect_stdout(out_buf), redirect_stderr(err_buf):
                mask = segment_fn()
            self._finish_segmentation_progress(finish_message)
            return mask
        except Exception as exc:
            self.seg_progress_bar.setVisible(False)
            out_text = out_buf.getvalue() if "out_buf" in locals() else ""
            err_text = err_buf.getvalue() if "err_buf" in locals() else ""
            trace_text = traceback.format_exc()
            QMessageBox.critical(
                self,
                "Segmentation error",
                self._format_segmentation_error(
                    exc,
                    stdout_text=out_text,
                    stderr_text=err_text,
                    traceback_text=trace_text,
                ),
            )
            return None

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

        mask = self._run_segmentation(
            "Running single-frame segmentation...",
            "Single-frame segmentation done. Mask overlay updated.",
            lambda: self.segmenter.segment_single_keyframe(
                pixel_array=self.pixel_array,
                dicom_ds=self.dicom_dataset,
                frame_idx=frame_idx,
                frame_points=points,
                progress_callback=self._update_segmentation_progress,
            )
        )
        if mask is None:
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

        sorted_kf = sorted(set(self.key_frames))
        start_pos = sorted_kf.index(frame_idx)
        end_frame = (
            sorted_kf[start_pos + 1]
            if start_pos + 1 < len(sorted_kf)
            else self._frame_count() - 1
        )

        mask = self._run_segmentation(
            "Running forward range segmentation...",
            f"Forward segmentation done ({frame_idx}->{end_frame}). Mask overlay updated.",
            lambda: self.segmenter.segment_forward_range(
                pixel_array=self.pixel_array,
                dicom_ds=self.dicom_dataset,
                start_frame_idx=frame_idx,
                end_frame_idx=end_frame,
                start_frame_points=points,
                progress_callback=self._update_segmentation_progress,
            )
        )
        if mask is None:
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

        sorted_kf = sorted(set(self.key_frames))
        start_pos = sorted_kf.index(frame_idx)
        end_frame = (
            sorted_kf[start_pos - 1]
            if start_pos > 0
            else 0
        )

        mask = self._run_segmentation(
            "Running backward range segmentation...",
            f"Backward segmentation done ({frame_idx}->{end_frame}). Mask overlay updated.",
            lambda: self.segmenter.segment_backward_range(
                pixel_array=self.pixel_array,
                dicom_ds=self.dicom_dataset,
                start_frame_idx=frame_idx,
                end_frame_idx=end_frame,
                start_frame_points=points,
                progress_callback=self._update_segmentation_progress,
            )
        )
        if mask is None:
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

        mask = self._run_segmentation(
            "Running all-frames segmentation...",
            "All-frame segmentation done. Mask overlay updated.",
            lambda: self.segmenter.segment_all_with_keyframes(
                pixel_array=self.pixel_array,
                dicom_ds=self.dicom_dataset,
                key_frames=self.key_frames,
                key_frame_points=self.key_frame_points,
                progress_callback=self._update_segmentation_progress,
            )
        )
        if mask is None:
            return

        self.segmentation_mask = mask
        self.segmentation_contours = None
        self.refresh_point_overlay()

    def fix_masks(self):
        if self.segmentation_mask is None:
            self.show_status("No segmentation mask available. Run segmentation first.")
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