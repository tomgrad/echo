import sys
import xml.etree.ElementTree as ET
import importlib
import traceback
import re
import pickle
from pathlib import Path
from contextlib import redirect_stderr, redirect_stdout
import io
from typing import Any
import numpy as np
import pydicom
from PySide6.QtCore import QStringListModel, QTimer
from PySide6.QtWidgets import QApplication, QMainWindow, QFileDialog, QMessageBox, QProgressBar

from medseg2 import MedSam2Segmenter, Sam2Segmenter
from mask_processing import fix_labeled_mask, find_external_contours, fit_spline_contours
from ui_mainwindow import Ui_MainWindow

FRAMES_LIMIT = -1  # Max frames to load from a DICOM (for testing), -1 for no limit.
# For long studies, SAM2 at 1024 can exceed VRAM because preprocessing moves all
# frames to CUDA at once. Keeping SAM2 at 512 is a practical high-frame workaround.
SAM2_MAX_IMAGE_SIZE = 512


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
        # key_frame_points: obj_id -> frame_index -> list of [x, y, positive(bool)]
        self.key_frame_points = {}
        self.segmentation_mask = None
        self.segmentation_contours = None
        self.segmentation_splines = None
        self.segmentation_spline_nodes = None
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
        self.imageView.frameChanged.connect(self._update_longitudinal_frame_marker)
        self.imageView.pointClicked.connect(self.on_point_clicked)
        self.saveKeyFramesButton.clicked.connect(self.save_key_frames)
        self.loadKeyFramesButton.clicked.connect(self.load_key_frames)
        self.exportMasksButton.clicked.connect(self.save_masks)
        self.exportContoursButton.clicked.connect(self.save_contours)
        self.playButton.clicked.connect(self.toggle_playback)
        self.segSingleButton.clicked.connect(self.segment_selected_keyframe)
        self.segRangeButton.clicked.connect(self.segment_keyframe_forward)
        self.segBackRangeButton.clicked.connect(self.segment_keyframe_backward)
        self.segAllButton.clicked.connect(self.segment_all_frames)
        self.fixMasksButton.clicked.connect(self.fix_masks)
        self.contoursButton.clicked.connect(self.find_external_contours)
        self.splinesButton.clicked.connect(self.fit_contour_splines)
        self.objIdSpinBox.valueChanged.connect(self._on_object_id_changed)
        self.hidePointsCheckBox.stateChanged.connect(self._update_overlay_visibility)
        self.hideMasksCheckBox.stateChanged.connect(self._update_overlay_visibility)
        self.hideContoursCheckBox.stateChanged.connect(self._update_overlay_visibility)
        self.hideSplinesCheckBox.stateChanged.connect(self._update_overlay_visibility)
        self.hideNodesCheckBox.stateChanged.connect(self._update_overlay_visibility)
        self.hideframesCheckBox.stateChanged.connect(self._update_overlay_visibility)
        self.hideHistogramCheckBox.stateChanged.connect(self._update_overlay_visibility)
        self.fpsSpinBox.valueChanged.connect(self._update_play_timer_interval)
        self.lineWidthSpinBox.valueChanged.connect(self._update_contour_width)
        self.imageView.getHistogramWidget().item.sigLevelsChanged.connect(
            self._sync_longitudinal_histogram
        )
        self._setup_longitudinal_selector()
        self.longitudinalComboBox.currentIndexChanged.connect(self._on_longitudinal_mode_changed)
        self.angleSlider.valueChanged.connect(self._on_longitudinal_angle_changed)
        self._setup_engine_selector()
        self.checkpointsComboBox.currentIndexChanged.connect(self._on_checkpoint_changed)
        self._populate_checkpoints_combo()
        self._update_play_timer_interval(self.fpsSpinBox.value())
        self._update_contour_width(self.lineWidthSpinBox.value())
        self._update_overlay_visibility()
        self.show_status("Ready", 3000)

    def show_status(self, message, timeout_ms=4000):
        self.statusbar.showMessage(message, timeout_ms)

    def _active_obj_id(self):
        return int(self.objIdSpinBox.value())

    def _on_object_id_changed(self, _value):
        self.refresh_key_frames_list()
        self.refresh_point_overlay()
        self.update_longitudinal_view()
        self.show_status(f"Active object set to {self._active_obj_id()}", 3000)

    def _setup_longitudinal_selector(self):
        self.longitudinalComboBox.clear()
        self.longitudinalComboBox.addItem("y = height / 2", "x")
        self.longitudinalComboBox.addItem("x = width / 2", "y")
        self.longitudinalComboBox.addItem("free (center + angle)", "free")
        self.angleSlider.setEnabled(False)

    def _selected_longitudinal_axis(self):
        axis = self.longitudinalComboBox.currentData()
        return axis if axis in {"x", "y", "free"} else "x"

    def _on_longitudinal_mode_changed(self, _index=None):
        is_free = self._selected_longitudinal_axis() == "free"
        self.angleSlider.setEnabled(is_free)
        self.update_longitudinal_view()

    def _on_longitudinal_angle_changed(self, _value):
        if self._selected_longitudinal_axis() == "free":
            self.update_longitudinal_view()

    @staticmethod
    def _contour_intersections_with_slice(contour, axis, slice_index):
        pts = np.asarray(contour, dtype=float)
        if pts.ndim != 2 or pts.shape[1] != 2 or pts.shape[0] < 2:
            return []

        c = float(slice_index)
        intersections = []
        count = pts.shape[0]

        for i in range(count):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % count]

            if axis == "x":
                # Slice line: x == c; result coordinate is y.
                if x1 == x2 == c:
                    intersections.extend([float(y1), float(y2)])
                    continue
                if x1 == x2:
                    continue
                t = (c - x1) / (x2 - x1)
                if 0.0 <= t <= 1.0:
                    intersections.append(float(y1 + t * (y2 - y1)))
            else:
                # Slice line: y == c; result coordinate is x.
                if y1 == y2 == c:
                    intersections.extend([float(x1), float(x2)])
                    continue
                if y1 == y2:
                    continue
                t = (c - y1) / (y2 - y1)
                if 0.0 <= t <= 1.0:
                    intersections.append(float(x1 + t * (x2 - x1)))

        if not intersections:
            return []

        # Deduplicate near-identical points from shared vertices.
        rounded = np.round(np.asarray(intersections, dtype=float), 3)
        return np.unique(rounded).astype(float).tolist()

    @staticmethod
    def _cross2d(a, b):
        return float(a[0] * b[1] - a[1] * b[0])

    @classmethod
    def _contour_intersections_with_line_segment(cls, contour, start_xy, end_xy):
        pts = np.asarray(contour, dtype=float)
        if pts.ndim != 2 or pts.shape[1] != 2 or pts.shape[0] < 2:
            return []

        p0 = np.asarray(start_xy, dtype=float)
        p1 = np.asarray(end_xy, dtype=float)
        r = p1 - p0
        r_norm = float(np.linalg.norm(r))
        if r_norm < 1e-6:
            return []

        intersections = []
        count = pts.shape[0]
        eps = 1e-6

        for i in range(count):
            q = pts[i]
            q2 = pts[(i + 1) % count]
            s = q2 - q
            q_minus_p = q - p0
            r_cross_s = cls._cross2d(r, s)

            if abs(r_cross_s) <= eps:
                # Collinear edge: include edge endpoints that fall on the sampling line segment.
                if abs(cls._cross2d(q_minus_p, r)) > 1e-3:
                    continue
                for candidate in (q, q2):
                    t = float(np.dot(candidate - p0, r) / np.dot(r, r))
                    if 0.0 <= t <= 1.0:
                        intersections.append(t * r_norm)
                continue

            t = cls._cross2d(q_minus_p, s) / r_cross_s
            u = cls._cross2d(q_minus_p, r) / r_cross_s
            if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
                intersections.append(t * r_norm)

        if not intersections:
            return []

        rounded = np.round(np.asarray(intersections, dtype=float), 3)
        return np.unique(rounded).astype(float).tolist()

    @staticmethod
    def _line_segment_through_center(height, width, angle_degrees):
        cx = 0.5 * (float(width) - 1.0)
        cy = 0.5 * (float(height) - 1.0)
        theta = np.deg2rad(float(angle_degrees) % 360.0)
        direction = np.asarray([np.cos(theta), np.sin(theta)], dtype=float)

        tx_min, tx_max = -np.inf, np.inf
        ty_min, ty_max = -np.inf, np.inf

        if abs(direction[0]) > 1e-8:
            tx1 = (0.0 - cx) / direction[0]
            tx2 = (float(width) - 1.0 - cx) / direction[0]
            tx_min, tx_max = min(tx1, tx2), max(tx1, tx2)

        if abs(direction[1]) > 1e-8:
            ty1 = (0.0 - cy) / direction[1]
            ty2 = (float(height) - 1.0 - cy) / direction[1]
            ty_min, ty_max = min(ty1, ty2), max(ty1, ty2)

        t_min = max(tx_min, ty_min)
        t_max = min(tx_max, ty_max)

        p0 = np.asarray([cx, cy], dtype=float) + t_min * direction
        p1 = np.asarray([cx, cy], dtype=float) + t_max * direction
        return p0, p1

    @classmethod
    def _sample_volume_along_segment(
        cls,
        volume: np.ndarray,
        start_xy: np.ndarray,
        end_xy: np.ndarray,
        samples_count: int,
    ) -> np.ndarray:
        samples_count = max(2, int(samples_count))
        x = np.linspace(float(start_xy[0]), float(end_xy[0]), samples_count, dtype=float)
        y = np.linspace(float(start_xy[1]), float(end_xy[1]), samples_count, dtype=float)

        x0 = np.floor(x).astype(np.int32)
        y0 = np.floor(y).astype(np.int32)
        x1 = np.clip(x0 + 1, 0, volume.shape[2] - 1)
        y1 = np.clip(y0 + 1, 0, volume.shape[1] - 1)
        x0 = np.clip(x0, 0, volume.shape[2] - 1)
        y0 = np.clip(y0, 0, volume.shape[1] - 1)

        wx = x - x0
        wy = y - y0

        v00 = volume[:, y0, x0]
        v10 = volume[:, y0, x1]
        v01 = volume[:, y1, x0]
        v11 = volume[:, y1, x1]

        top = v00 * (1.0 - wx) + v10 * wx
        bottom = v01 * (1.0 - wx) + v11 * wx
        return (top * (1.0 - wy) + bottom * wy).T

    def _longitudinal_contour_points(
        self,
        axis,
        slice_index,
        image_size,
        line_start=None,
        line_end=None,
        line_length=None,
        free_full_size=None,
        free_clip_offset=0.0,
    ):
        if self.segmentation_contours is None:
            return []

        frame_count = self._frame_count()
        points = []
        max_y = float(max(1, image_size))

        for frame_idx in range(frame_count):
            contours = self.segmentation_contours.get(frame_idx, [])
            for contour in contours:
                if axis == "free":
                    values = self._contour_intersections_with_line_segment(contour, line_start, line_end)
                else:
                    values = self._contour_intersections_with_slice(contour, axis, slice_index)
                for value in values:
                    if axis == "free" and line_length is not None and line_length > 1e-6:
                        full_size = max(2, int(free_full_size if free_full_size is not None else image_size))
                        # Project arc-length along free line into full sampled row coordinates.
                        value = float(value) * float(full_size - 1) / float(line_length)
                        # Clip into displayed row coordinates when we crop to frame width.
                        value = float(value) - float(free_clip_offset)
                    y = float(np.clip(max_y - value, 0.0, max_y))
                    points.append((float(frame_idx), y))
        return points

    def _build_axis_longitudinal_slice(self, base_volume: np.ndarray, axis: str) -> dict[str, Any]:
        _, height, width = base_volume.shape
        if axis == "y":
            slice_index = height // 2
            longitudinal = base_volume[:, slice_index, :].T
            image_size = width
        else:
            slice_index = width // 2
            longitudinal = base_volume[:, :, slice_index].T
            image_size = height

        return {
            "slice_index": slice_index,
            "longitudinal": longitudinal,
            "image_size": image_size,
            "line_start": None,
            "line_end": None,
            "line_length": None,
            "free_full_size": None,
            "free_clip_offset": 0.0,
        }

    def _build_free_longitudinal_slice(self, base_volume: np.ndarray) -> dict[str, Any]:
        _, height, width = base_volume.shape
        angle_degrees = float(self.angleSlider.value())
        line_start, line_end = self._line_segment_through_center(height, width, angle_degrees)
        line_length = float(np.linalg.norm(line_end - line_start))
        full_samples = max(2, int(np.ceil(line_length)) + 1)
        full_longitudinal = self._sample_volume_along_segment(base_volume, line_start, line_end, full_samples)

        target_size = max(2, int(width))
        if full_samples > target_size:
            start = int((full_samples - target_size) // 2)
            end = start + target_size
            longitudinal = full_longitudinal[start:end, :]
            image_size = target_size
            free_clip_offset = float(start)
        else:
            longitudinal = full_longitudinal
            image_size = full_samples
            free_clip_offset = 0.0

        return {
            "slice_index": None,
            "longitudinal": longitudinal,
            "image_size": image_size,
            "line_start": line_start,
            "line_end": line_end,
            "line_length": line_length,
            "free_full_size": full_samples,
            "free_clip_offset": free_clip_offset,
        }

    def _build_longitudinal_slice_context(self, base_volume: np.ndarray, axis: str) -> dict[str, Any]:
        if axis in {"x", "y"}:
            return self._build_axis_longitudinal_slice(base_volume, axis)
        return self._build_free_longitudinal_slice(base_volume)

    def update_longitudinal_view(self):
        base_volume = self.pixel_array
        if base_volume is None or base_volume.ndim != 3:
            self.longitudinalView.clear()
            self.longitudinalView.set_contour_cross_sections([])
            return

        axis = self._selected_longitudinal_axis()
        ctx = self._build_longitudinal_slice_context(base_volume, axis)

        self.longitudinalView.set_cross_section(ctx["longitudinal"])
        if self.hideContoursCheckBox.isChecked():
            contour_points = []
        else:
            contour_points = self._longitudinal_contour_points(
                axis,
                ctx["slice_index"],
                ctx["image_size"],
                line_start=ctx["line_start"],
                line_end=ctx["line_end"],
                line_length=ctx["line_length"],
                free_full_size=ctx["free_full_size"],
                free_clip_offset=ctx["free_clip_offset"],
            )
        self.longitudinalView.set_contour_cross_sections(contour_points)
        self._update_longitudinal_frame_marker(self.imageView.currentIndex)

    def _update_longitudinal_frame_marker(self, frame_idx=None):
        if frame_idx is None:
            frame_idx = self.imageView.currentIndex
        self.longitudinalView.set_current_frame(int(frame_idx))

    def _sync_longitudinal_histogram(self, *_args):
        levels = self.imageView.getLevels()
        self.longitudinalView.set_histogram_levels(levels)

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
        # Official SAM2 configs live under configs/sam2.1/.
        variant_to_suffix = {
            "t": "t",
            "s": "s",
            "b+": "b+",
            "l": "l",
        }
        suffix = variant_to_suffix.get(variant, "t")
        return f"configs/sam2.1/sam2.1_hiera_{suffix}.yaml"

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
            image_size = min(self._image_size_for_model_cfg(model_cfg), SAM2_MAX_IMAGE_SIZE)
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

    def _release_segmenter(self):
        if self.segmenter is None:
            return
        self.segmenter = None

    def _on_engine_changed(self, _index=None):
        self._release_segmenter()
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
        self._release_segmenter()
        if emit_status and checkpoint_path is not None:
            self.show_status(
                f"Selected {self._current_engine_name()} checkpoint: {checkpoint_path.name}",
                4000,
            )

    def closeEvent(self, event):
        self.stop_playback()
        self._release_segmenter()
        super().closeEvent(event)

    def add_key_frame(self):
        if self.pixel_array is None:
            self.show_status("Open a DICOM file first.")
            return

        current_frame = self.imageView.currentIndex
        if current_frame not in self.key_frames:
            self.key_frames.append(current_frame)
            self.key_frames.sort()
            self._invalidate_segmentation()
            self.refresh_key_frames_list()
            self.refresh_point_overlay()
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
        for frame_map in self.key_frame_points.values():
            frame_map.pop(selected_frame, None)
        self._invalidate_segmentation()
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
        self._invalidate_segmentation()
        self.keyFramesListView.clearSelection()
        self.refresh_key_frames_list()
        self.refresh_point_overlay()
        self.show_status(f"Deleted all key frames ({count}).")

    def on_point_clicked(self, x, y, action):
        frame = self.imageView.currentIndex
        obj_id = self._active_obj_id()
        if frame not in self.key_frames:
            self.show_status("Current frame is not a key frame.")
            return

        changed = False
        if action == "delete":
            changed = self._remove_nearest_point(frame, obj_id, x, y)
        else:
            positive = (action == "positive")
            self.key_frame_points.setdefault(obj_id, {}).setdefault(frame, []).append([x, y, positive])
            point_type = "positive" if positive else "negative"
            self.show_status(f"Added {point_type} point for object {obj_id} at ({x}, {y}) on frame {frame}")
            changed = True

        if changed:
            self._invalidate_segmentation()
        self.refresh_key_frames_list()
        self.refresh_point_overlay()

    def _remove_nearest_point(self, frame, obj_id, x, y):
        points = self.key_frame_points.get(obj_id, {}).get(frame, [])
        if not points:
            self.show_status(f"No points to remove for object {obj_id} on this key frame.")
            return False
        closest = min(points, key=lambda p: (p[0] - x) ** 2 + (p[1] - y) ** 2)
        points.remove(closest)
        self.show_status(
            f"Removed object {obj_id} point at ({closest[0]}, {closest[1]}) from frame {frame}"
        )
        return True

    def refresh_point_overlay(self, frame=None):
        if frame is None:
            frame = self.imageView.currentIndex
        points_by_object = {}
        for obj_id, frame_map in self.key_frame_points.items():
            points = frame_map.get(frame, [])
            if not points:
                continue
            points_by_object[obj_id] = {
                "positive": [(p[0], p[1]) for p in points if p[2]],
                "negative": [(p[0], p[1]) for p in points if not p[2]],
            }
        self.imageView.set_points_by_object(points_by_object)
        frame_mask = None
        if self.segmentation_mask is not None and 0 <= frame < self.segmentation_mask.shape[0]:
            frame_mask = self.segmentation_mask[frame]
        self.imageView.set_mask(frame_mask)
        frame_contours = []
        if self.segmentation_contours is not None:
            frame_contours = self.segmentation_contours.get(frame, [])
        self.imageView.set_contours(frame_contours)
        frame_splines = []
        if self.segmentation_splines is not None:
            frame_splines = self.segmentation_splines.get(frame, [])
        self.imageView.set_splines(frame_splines)
        frame_nodes = []
        if self.segmentation_spline_nodes is not None:
            frame_nodes = self.segmentation_spline_nodes.get(frame, [])
        self.imageView.set_spline_nodes(frame_nodes)

    def _update_overlay_visibility(self):
        show_points = not self.hidePointsCheckBox.isChecked()
        show_masks = not self.hideMasksCheckBox.isChecked()
        show_contours = not self.hideContoursCheckBox.isChecked()
        show_splines = not self.hideSplinesCheckBox.isChecked()
        show_nodes = not self.hideNodesCheckBox.isChecked()
        show_frames = not self.hideframesCheckBox.isChecked()
        show_histogram = not self.hideHistogramCheckBox.isChecked()
        self.imageView.set_points_visible(show_points)
        self.imageView.set_mask_visible(show_masks)
        self.imageView.set_contours_visible(show_contours)
        self.longitudinalView.set_contours_visible(show_contours)
        self.imageView.set_splines_visible(show_splines)
        self.imageView.set_spline_nodes_visible(show_nodes)
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
        self.imageView.set_spline_width(int(width))

    def _percentile_clip_from_ui(self):
        lo = float(self.loClipSpinBox.value())
        hi = float(self.hiClipSpinBox.value())
        return lo, hi

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
        active_obj = self._active_obj_id()
        labels = []
        for frame in self.key_frames:
            all_points = []
            for frame_map in self.key_frame_points.values():
                all_points.extend(frame_map.get(frame, []))
            active_points = self.key_frame_points.get(active_obj, {}).get(frame, [])

            pos_all = sum(1 for p in all_points if p[2])
            neg_all = sum(1 for p in all_points if not p[2])
            pos_active = sum(1 for p in active_points if p[2])
            neg_active = sum(1 for p in active_points if not p[2])
            labels.append(
                f"{frame} (obj {active_obj}: {pos_active}/{neg_active}, all: {pos_all}/{neg_all})"
            )
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
            for obj_id, frame_map in self.key_frame_points.items():
                for pt in frame_map.get(frame_idx, []):
                    ET.SubElement(
                        kf_el, "point",
                        x=str(pt[0]), y=str(pt[1]),
                        positive=("true" if pt[2] else "false"),
                        obj_id=str(obj_id),
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
        try:
            root = tree.getroot()
            if root.tag != "keyframes":
                raise ValueError("Not a valid key frames file.")
            self.key_frames.clear()
            self.key_frame_points.clear()
            for kf_el in root.findall("keyframe"):
                frame_idx = int(kf_el.get("index"))
                if frame_idx not in self.key_frames:
                    self.key_frames.append(frame_idx)
                for pt_el in kf_el.findall("point"):
                    x = pt_el.get("x")
                    y = pt_el.get("y")
                    positive = pt_el.get("positive")
                    obj_id = pt_el.get("obj_id")
                    if x is None or y is None or positive is None or obj_id is None:
                        raise ValueError(
                            "Invalid keyframe file: each point must include x, y, positive, and obj_id"
                        )
                    self.key_frame_points.setdefault(int(obj_id), {}).setdefault(frame_idx, []).append([
                        int(x),
                        int(y),
                        positive == "true",
                    ])
        except (TypeError, ValueError) as exc:
            QMessageBox.critical(self, "Load error", f"Could not load key frames:\n{exc}")
            return
        self._invalidate_segmentation()
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

        np.save(output_path, self.segmentation_mask.astype(np.uint16))
        self.show_status(f"Saved masks to {output_path}", 6000)

    def save_contours(self):
        if self.segmentation_contours is None:
            self.show_status("No contours available. Extract contours first.")
            return

        if self.dicom_file_path:
            dicom_stem = Path(self.dicom_file_path).stem
        else:
            dicom_stem = "dicom"

        output_dir = Path(__file__).resolve().parent / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{dicom_stem}_contours.pkl"

        with output_path.open("wb") as handle:
            pickle.dump(self.segmentation_contours, handle)

        self.show_status(f"Saved contours to {output_path}", 6000)

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

    def _invalidate_segmentation(self):
        self.segmentation_mask = None
        self.segmentation_contours = None
        self.segmentation_splines = None
        self.segmentation_spline_nodes = None
        self.update_longitudinal_view()

    def _points_by_object_for_frame(self, frame_idx):
        return {
            int(obj_id): points
            for obj_id, frame_map in self.key_frame_points.items()
            for points in [frame_map.get(frame_idx, [])]
            if points
        }

    def _selected_key_frame(self):
        selected_indexes = self.keyFramesListView.selectedIndexes()
        if not selected_indexes:
            return None
        return self._frame_from_list_index(selected_indexes[0])

    def _require_selected_keyframe_with_points(self, missing_selection_message):
        frame_idx = self._selected_key_frame()
        if frame_idx is None:
            self.show_status(missing_selection_message)
            return None, None

        points_by_object = self._points_by_object_for_frame(frame_idx)
        if not points_by_object:
            self.show_status(f"Key frame {frame_idx} has no prompt points for any object.")
            return None, None

        return frame_idx, points_by_object

    def _finalize_segmentation_result(self, mask, start_frame, end_frame, obj_ids):
        if mask is None:
            return False

        self._merge_multi_object_mask(mask, start_frame, end_frame, obj_ids)
        self.segmentation_contours = None
        self.segmentation_splines = None
        self.segmentation_spline_nodes = None
        self.update_longitudinal_view()
        self.refresh_point_overlay()
        return True

    def _collect_all_object_keyframe_points(self):
        obj_points = {
            int(obj_id): frame_map
            for obj_id, frame_map in self.key_frame_points.items()
            if any(frame_map.get(frame_idx) for frame_idx in self.key_frames)
        }
        missing_points = [
            frame_idx
            for frame_idx in sorted(self.key_frames)
            if not any(frame_map.get(frame_idx) for frame_map in obj_points.values())
        ]
        return obj_points, missing_points

    def _merge_multi_object_mask(self, new_mask, start_frame, end_frame, obj_ids):
        obj_ids = sorted(int(obj_id) for obj_id in obj_ids)
        if self.segmentation_mask is None or self.segmentation_mask.shape != new_mask.shape:
            self.segmentation_mask = np.zeros_like(new_mask, dtype=np.uint16)

        frame_slice = slice(start_frame, end_frame + 1)
        existing = self.segmentation_mask[frame_slice].copy()

        for obj_id in obj_ids:
            existing[existing == obj_id] = 0

        for obj_id in obj_ids:
            incoming = new_mask[frame_slice] == obj_id
            take_incoming = incoming & ((existing == 0) | (obj_id < existing))
            existing[take_incoming] = obj_id

        self.segmentation_mask[frame_slice] = existing

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

        frame_idx, points_by_object = self._require_selected_keyframe_with_points(
            "Select a key frame for single-frame segmentation."
        )
        if frame_idx is None:
            return

        percentile_clip = self._percentile_clip_from_ui()

        mask = self._run_segmentation(
            "Running multi-object single-frame segmentation...",
            "Single-frame segmentation done for all prompted objects. Mask overlay updated.",
            lambda: self.segmenter.segment_single_keyframe_multi_object(
                pixel_array=self.pixel_array,
                dicom_ds=self.dicom_dataset,
                frame_idx=frame_idx,
                frame_points_by_obj=points_by_object,
                percentile_clip=percentile_clip,
                progress_callback=self._update_segmentation_progress,
            )
        )
        self._finalize_segmentation_result(mask, frame_idx, frame_idx, points_by_object.keys())

    def segment_keyframe_forward(self):
        if not self._ensure_ready_for_segmentation():
            return

        frame_idx, points_by_object = self._require_selected_keyframe_with_points(
            "Select a start key frame for forward segmentation."
        )
        if frame_idx is None:
            return

        sorted_kf = sorted(set(self.key_frames))
        start_pos = sorted_kf.index(frame_idx)
        end_frame = (
            sorted_kf[start_pos + 1]
            if start_pos + 1 < len(sorted_kf)
            else self._frame_count() - 1
        )

        percentile_clip = self._percentile_clip_from_ui()

        mask = self._run_segmentation(
            "Running multi-object forward range segmentation...",
            f"Forward segmentation done for all prompted objects ({frame_idx}->{end_frame}). Mask overlay updated.",
            lambda: self.segmenter.segment_forward_range_multi_object(
                pixel_array=self.pixel_array,
                dicom_ds=self.dicom_dataset,
                start_frame_idx=frame_idx,
                end_frame_idx=end_frame,
                start_frame_points_by_obj=points_by_object,
                percentile_clip=percentile_clip,
                progress_callback=self._update_segmentation_progress,
            )
        )
        self._finalize_segmentation_result(mask, frame_idx, end_frame, points_by_object.keys())

    def segment_keyframe_backward(self):
        if not self._ensure_ready_for_segmentation():
            return

        frame_idx, points_by_object = self._require_selected_keyframe_with_points(
            "Select a start key frame for backward segmentation."
        )
        if frame_idx is None:
            return

        sorted_kf = sorted(set(self.key_frames))
        start_pos = sorted_kf.index(frame_idx)
        end_frame = (
            sorted_kf[start_pos - 1]
            if start_pos > 0
            else 0
        )

        percentile_clip = self._percentile_clip_from_ui()

        mask = self._run_segmentation(
            "Running multi-object backward range segmentation...",
            f"Backward segmentation done for all prompted objects ({frame_idx}->{end_frame}). Mask overlay updated.",
            lambda: self.segmenter.segment_backward_range_multi_object(
                pixel_array=self.pixel_array,
                dicom_ds=self.dicom_dataset,
                start_frame_idx=frame_idx,
                end_frame_idx=end_frame,
                start_frame_points_by_obj=points_by_object,
                percentile_clip=percentile_clip,
                progress_callback=self._update_segmentation_progress,
            )
        )
        self._finalize_segmentation_result(mask, end_frame, frame_idx, points_by_object.keys())

    def segment_all_frames(self):
        if not self._ensure_ready_for_segmentation():
            return

        obj_points, missing_points = self._collect_all_object_keyframe_points()
        if not obj_points:
            self.show_status("Add prompt points for at least one object before all-frames segmentation.")
            return
        if missing_points:
            self.show_status(f"These key frames have no points for any object: {missing_points}")
            return

        percentile_clip = self._percentile_clip_from_ui()

        mask = self._run_segmentation(
            "Running all-object segmentation...",
            "All-object segmentation done. Mask overlay updated.",
            lambda: self.segmenter.segment_all_with_keyframes(
                pixel_array=self.pixel_array,
                dicom_ds=self.dicom_dataset,
                key_frames=self.key_frames,
                key_frame_points=obj_points,
                percentile_clip=percentile_clip,
                progress_callback=self._update_segmentation_progress,
            )
        )
        self._finalize_segmentation_result(mask, 0, self._frame_count() - 1, obj_points.keys())

    def fix_masks(self):
        if self.segmentation_mask is None:
            self.show_status("No segmentation mask available. Run segmentation first.")
            return

        iterations = int(self.smoothSpinBox.value())
        self._start_segmentation_progress("Fixing masks...")

        try:
            fixed_mask = fix_labeled_mask(
                self.segmentation_mask,
                iterations,
                progress_callback=lambda done, total: self._update_segmentation_progress(done, total, "Fixing masks"),
            )
        except ValueError:
            self.seg_progress_bar.setVisible(False)
            self.show_status(f"Unsupported mask shape: {self.segmentation_mask.shape}")
            return

        self.segmentation_mask = fixed_mask
        self.segmentation_contours = None
        self.segmentation_splines = None
        self.segmentation_spline_nodes = None
        self.update_longitudinal_view()
        self.refresh_point_overlay()
        self._finish_segmentation_progress(f"Mask fixing complete (smooth level: {iterations}).")

    def find_external_contours(self):
        if self.segmentation_mask is None:
            self.show_status("No segmentation mask available. Run segmentation first.")
            return

        epsilon = float(self.epsilonSpinBox.value())
        use_approx = epsilon > 0.0

        try:
            contour_map = find_external_contours(self.segmentation_mask, epsilon=epsilon)
        except ValueError:
            self.show_status(f"Unsupported mask shape: {self.segmentation_mask.shape}")
            return

        self.segmentation_contours = contour_map
        self.segmentation_splines = None
        self.segmentation_spline_nodes = None
        color = (255, 255, 0, 255)
        self.imageView.set_contour_color(color)
        self.refresh_point_overlay()
        self.update_longitudinal_view()
        if use_approx:
            self.show_status(f"External contours extracted (approxPolyDP, epsilon={epsilon:g}).", 5000)
        else:
            self.show_status("External contours extracted (no approximation).", 5000)

    def fit_contour_splines(self):
        if self.segmentation_mask is None and self.segmentation_contours is None:
            self.show_status("No segmentation mask available. Run segmentation first.")
            return

        if self.segmentation_contours is None:
            try:
                epsilon = float(self.epsilonSpinBox.value())
                self.segmentation_contours = find_external_contours(self.segmentation_mask, epsilon=epsilon)
            except ValueError:
                self.show_status(f"Unsupported mask shape: {self.segmentation_mask.shape}")
                return

        num_control_points = int(self.splineNodesSpinBox.value())
        try:
            self.segmentation_splines, self.segmentation_spline_nodes = fit_spline_contours(
                self.segmentation_contours,
                num_control_points=num_control_points,
                num_samples=num_control_points * 10,
                return_nodes=True,
            )
        except ValueError as exc:
            self.show_status(str(exc))
            return

        self.imageView.set_spline_color((0, 255, 255, 255))
        self.imageView.set_spline_nodes_color((255, 80, 80, 255))
        self.refresh_point_overlay()
        self.show_status(f"Spline fitting complete (control points: {num_control_points}).", 5000)

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
                self.segmentation_splines = None
                self.segmentation_spline_nodes = None
                self.stop_playback()
                self.imageView.setImage(self.pixel_array)
                self.imageView.set_mask(None)
                self.imageView.set_contours([])
                self.imageView.set_splines([])
                self.imageView.set_spline_nodes([])
                self.key_frames.clear()
                self.key_frame_points.clear()
                self.refresh_key_frames_list()
                self.refresh_point_overlay()
                self.update_longitudinal_view()
                self._sync_longitudinal_histogram()
                self.show_status(f"Loaded DICOM: {dicom_file_path}", 6000)


app = QApplication(sys.argv)
window = MainWindow()
window.show()
app.exec()
