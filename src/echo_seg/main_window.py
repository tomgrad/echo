import xml.etree.ElementTree as ET
import json
from pathlib import Path
from typing import Any
import numpy as np
from echo_core import dicom_io, video_io
from echo_core.display import display_array
from PySide6.QtCore import QStringListModel, QTimer
from PySide6.QtWidgets import QMainWindow, QFileDialog, QMessageBox, QProgressBar

from echo_seg.cross_section import cross_section_contour_points, sample_volume_along_segment
from echo_seg.keyframes_io import read_keyframes, write_keyframes
from echo_seg.workers import SegmentationWorker
from echo_seg.segmenter import MedSam2Segmenter
from echo_core.masks import (
    build_custom_mask,
    contours_to_jsonable,
    fix_labeled_mask,
    find_external_contours,
    fit_spline_contours,
    point_segment_distance_sq,
    sample_outline_curve,
)
from echo_seg.ui.ui_mainwindow import Ui_MainWindow

FRAMES_LIMIT = -1  # Max frames to load from a DICOM (for testing), -1 for no limit.
MEDSAM2_MODEL_CFG = "configs/sam2.1_hiera_t512.yaml"


class MainWindow(QMainWindow, Ui_MainWindow):

    def __init__(self):
        super().__init__()
        self.setupUi(self)
        self.checkpoints_root_dir = Path(__file__).resolve().parents[2] / "checkpoints"
        self.medsam2_checkpoints_dir = self.checkpoints_root_dir / "MedSAM2"

        self.pixel_array = None
        self.is_color = False
        self._worker = None
        # Grayscale (frames, rows, cols) volume used by the cross-section view.
        self.cross_section_volume = None
        self.dicom_dataset = None
        self.dicom_file_path = None
        self.key_frames = []
        # key_frame_points: obj_id -> frame_index -> list of [x, y, positive(bool)]
        self.key_frame_points = {}
        # key_frame_outlines: obj_id -> frame_index -> list of [x, y] custom mask vertices
        self.key_frame_outlines = {}
        # Outline vertices in the order drawn by the image view: (obj_id, vertex_index).
        self._outline_refs = []
        # Active vertex drag: (obj_id, vertex_index, frame_index).
        self._outline_drag = None
        self.segmentation_mask = None
        self.segmentation_contours = None
        self.segmentation_splines = None
        self.segmentation_spline_nodes = None
        self.segmenter = None
        self.key_frames_model = QStringListModel(self)
        self.keyFramesListView.setModel(self.key_frames_model)
        self.play_timer = QTimer(self)
        self.play_timer.timeout.connect(self._advance_frame)
        # Custom line drags fire on every mouse move; recompute the cross-section once they settle.
        self._cross_section_timer = QTimer(self)
        self._cross_section_timer.setSingleShot(True)
        self._cross_section_timer.setInterval(40)
        self._cross_section_timer.timeout.connect(self.update_cross_section_view)
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
        self.imageView.frameChanged.connect(self._update_cross_section_frame_marker)
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
        self.trackMaskButton.clicked.connect(self.track_custom_mask)
        self.clearOutlineButton.clicked.connect(self.clear_outline)
        self.customMaskCheckBox.toggled.connect(self.imageView.set_outline_edit_enabled)
        self.imageView.outlineHandlePressed.connect(self._on_outline_handle_pressed)
        self.imageView.outlineHandleMoved.connect(self._on_outline_handle_moved)
        self.imageView.outlineHandleReleased.connect(self._on_outline_handle_released)
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
            self._sync_cross_section_histogram
        )
        self._setup_cross_section_selector()
        self.crossSectionComboBox.currentIndexChanged.connect(self._on_cross_section_mode_changed)
        self.imageView.lineChanged.connect(self._on_custom_line_changed)
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
        self.update_cross_section_view()
        self.show_status(f"Active object set to {self._active_obj_id()}", 3000)

    def _setup_cross_section_selector(self):
        self.crossSectionComboBox.clear()
        self.crossSectionComboBox.addItem("vertical", "vertical")
        self.crossSectionComboBox.addItem("custom", "custom")

    def _selected_cross_section_axis(self):
        axis = self.crossSectionComboBox.currentData()
        return axis if axis in {"vertical", "custom"} else "vertical"

    def _on_cross_section_mode_changed(self, _index=None):
        axis = self._selected_cross_section_axis()
        self.imageView.set_line_visible(axis == "custom")
        if axis == "custom" and self.imageView.line_endpoints() is None:
            self._reset_custom_line()
        self.update_cross_section_view()

    def _on_custom_line_changed(self):
        if self._selected_cross_section_axis() == "custom":
            self._cross_section_timer.start()

    def _reset_custom_line(self):
        """Place the custom line vertically across the middle of the frame, return its endpoints."""
        if self.cross_section_volume is None or self.cross_section_volume.ndim != 3:
            return None
        _, height, width = self.cross_section_volume.shape
        p0 = (0.5 * (width - 1), 0.95 * (height - 1))
        p1 = (0.5 * (width - 1), 0.05 * (height - 1))
        self.imageView.set_line_endpoints(p0, p1)
        self.imageView.set_line_visible(self._selected_cross_section_axis() == "custom")
        return self.imageView.line_endpoints()

    def _build_vertical_cross_section_slice(self, base_volume: np.ndarray) -> dict[str, Any]:
        _, height, width = base_volume.shape
        slice_index = width // 2
        # Flip rows so the cross-section is shown upside down.
        cross_section = base_volume[:, :, slice_index].T[::-1]

        return {
            "slice_index": slice_index,
            "cross_section": cross_section,
            "image_size": height,
            "line_start": None,
            "line_end": None,
            "line_length": None,
            "free_full_size": None,
            "free_clip_offset": 0.0,
        }

    def _build_custom_cross_section_slice(self, base_volume: np.ndarray) -> dict[str, Any]:
        endpoints = self.imageView.line_endpoints() or self._reset_custom_line()
        line_start, line_end = endpoints
        line_start = np.asarray(line_start, dtype=float)
        line_end = np.asarray(line_end, dtype=float)
        line_length = float(np.linalg.norm(line_end - line_start))
        full_samples = max(2, int(np.ceil(line_length)) + 1)
        # Keep the whole line: no cropping to the frame width.
        cross_section = sample_volume_along_segment(base_volume, line_start, line_end, full_samples)

        return {
            "slice_index": None,
            "cross_section": cross_section,
            "image_size": full_samples,
            "line_start": line_start,
            "line_end": line_end,
            "line_length": line_length,
            "free_full_size": full_samples,
            "free_clip_offset": 0.0,
        }

    def _build_cross_section_slice_context(self, base_volume: np.ndarray, axis: str) -> dict[str, Any]:
        if axis == "custom":
            return self._build_custom_cross_section_slice(base_volume)
        return self._build_vertical_cross_section_slice(base_volume)

    def update_cross_section_view(self):
        base_volume = self.cross_section_volume
        if base_volume is None or base_volume.ndim != 3:
            self.crossSectionView.clear()
            self.crossSectionView.set_contour_cross_sections([])
            return

        axis = self._selected_cross_section_axis()
        ctx = self._build_cross_section_slice_context(base_volume, axis)

        self.crossSectionView.set_cross_section(ctx["cross_section"])
        if self.hideContoursCheckBox.isChecked():
            contour_points = []
        else:
            contour_points = cross_section_contour_points(
                self.segmentation_contours,
                self._frame_count(),
                axis,
                ctx["slice_index"],
                ctx["image_size"],
                line_start=ctx["line_start"],
                line_end=ctx["line_end"],
                line_length=ctx["line_length"],
                free_full_size=ctx["free_full_size"],
                free_clip_offset=ctx["free_clip_offset"],
            )
        self.crossSectionView.set_contour_cross_sections(contour_points)
        self._update_cross_section_frame_marker(self.imageView.currentIndex)

    def _update_cross_section_frame_marker(self, frame_idx=None):
        if frame_idx is None:
            frame_idx = self.imageView.currentIndex
        self.crossSectionView.set_current_frame(int(frame_idx))

    def _sync_cross_section_histogram(self, *_args):
        levels = self.imageView.getLevels()
        self.crossSectionView.set_histogram_levels(levels)

    def _start_segmentation_progress(self, message, indeterminate=False):
        if indeterminate:
            # No progress callbacks for this task: show a busy bar instead of a stuck 0%.
            self.seg_progress_bar.setRange(0, 0)
        else:
            self.seg_progress_bar.setRange(0, 100)
            self.seg_progress_bar.setValue(0)
            self.seg_progress_bar.setFormat("0%")
        self.seg_progress_bar.setVisible(True)
        self.statusbar.showMessage(message, 0)

    def _update_segmentation_progress(self, done, total, stage):
        total = max(1, int(total))
        done = max(0, min(int(done), total))
        percent = int((done * 100) / total)
        self.seg_progress_bar.setValue(percent)
        self.seg_progress_bar.setFormat(f"{percent}%")
        self.statusbar.showMessage(f"{stage}: {done}/{total}", 0)

    def _finish_segmentation_progress(self, message):
        self.seg_progress_bar.setValue(100)
        self.seg_progress_bar.setFormat("100%")
        self.statusbar.showMessage(message, 4000)
        self.seg_progress_bar.setVisible(False)

    def _create_segmenter_for_selection(self, checkpoint_path):
        # Keep MedSAM2 preprocessing at 512 to preserve historical behavior.
        return MedSam2Segmenter(
            checkpoint_path=str(checkpoint_path),
            model_cfg=MEDSAM2_MODEL_CFG,
            image_size=512,
        )

    def _release_segmenter(self):
        if self.segmenter is None:
            return
        self.segmenter.release()
        self.segmenter = None

    def _populate_checkpoints_combo(self):
        checkpoint_paths = sorted(
            self.medsam2_checkpoints_dir.glob("MedSAM2*.pt"), key=lambda path: path.name.lower()
        )

        self.checkpointsComboBox.blockSignals(True)
        self.checkpointsComboBox.clear()

        if not checkpoint_paths:
            self.checkpointsComboBox.setEnabled(False)
            self.checkpointsComboBox.blockSignals(False)
            self.show_status(
                f"No MedSAM2 checkpoints found in {self.medsam2_checkpoints_dir.as_posix()}/.",
                6000,
            )
            return

        for checkpoint_path in checkpoint_paths:
            self.checkpointsComboBox.addItem(checkpoint_path.name, str(checkpoint_path))

        default_index = next(
            (index for index, path in enumerate(checkpoint_paths) if path.name == "MedSAM2_latest.pt"),
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
            self.show_status(f"Selected MedSAM2 checkpoint: {checkpoint_path.name}", 4000)

    def closeEvent(self, event):
        self.stop_playback()
        if self._worker is not None:
            # Let the running segmentation finish instead of killing the thread.
            self._worker.wait()
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
        for frame_map in self.key_frame_outlines.values():
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
        self.key_frame_outlines.clear()
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

        if self.customMaskCheckBox.isChecked():
            self._on_outline_clicked(frame, obj_id, x, y, action)
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
            self._invalidate_object(obj_id)
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

    def _on_outline_clicked(self, frame, obj_id, x, y, action):
        if action == "delete":
            changed = self._remove_nearest_outline_vertex(frame, obj_id, x, y)
        elif action == "negative":
            changed = self._insert_outline_vertex(frame, x, y)
        else:
            vertices = self.key_frame_outlines.setdefault(obj_id, {}).setdefault(frame, [])
            vertices.append([x, y])
            self.show_status(
                f"Added outline vertex {len(vertices)} for object {obj_id} at ({x}, {y}) on frame {frame}"
            )
            changed = True
        if changed:
            self._invalidate_object(obj_id)
        self.refresh_point_overlay()

    def _insert_outline_vertex(self, frame, x, y):
        """Insert a vertex between the two outline vertices of the nearest edge."""
        best = None  # (distance_sq, obj_id, edge_start_index)
        for obj_id, frame_map in self.key_frame_outlines.items():
            vertices = frame_map.get(frame, [])
            count = len(vertices)
            if count < 2:
                continue
            for index in range(count):
                start = vertices[index]
                end = vertices[(index + 1) % count]
                dist_sq = point_segment_distance_sq((x, y), start, end)
                if best is None or dist_sq < best[0]:
                    best = (dist_sq, obj_id, index)
        if best is None:
            self.show_status("Need at least two outline vertices on this frame to insert a vertex.")
            return False
        _, obj_id, index = best
        self.key_frame_outlines[obj_id][frame].insert(index + 1, [x, y])
        self.show_status(f"Inserted outline vertex at ({x}, {y}) for object {obj_id} on frame {frame}")
        return True

    def _on_outline_handle_pressed(self, handle_index):
        self._outline_drag = (*self._outline_refs[handle_index], self.imageView.currentIndex)

    def _on_outline_handle_moved(self, x, y):
        if self._outline_drag is None:
            return
        obj_id, vertex_index, frame = self._outline_drag
        height, width = self.cross_section_volume.shape[-2:]
        x = min(max(x, 0), width - 1)
        y = min(max(y, 0), height - 1)
        self.key_frame_outlines[obj_id][frame][vertex_index] = [x, y]
        self.refresh_point_overlay(frame)

    def _on_outline_handle_released(self):
        if self._outline_drag is None:
            return
        obj_id = self._outline_drag[0]
        self._outline_drag = None
        self._invalidate_object(obj_id)
        self.refresh_point_overlay()
        self.show_status("Outline vertex moved")

    def _remove_nearest_outline_vertex(self, frame, obj_id, x, y):
        vertices = self.key_frame_outlines.get(obj_id, {}).get(frame, [])
        if not vertices:
            self.show_status(f"No outline vertices to remove for object {obj_id} on this key frame.")
            return False
        closest = min(vertices, key=lambda v: (v[0] - x) ** 2 + (v[1] - y) ** 2)
        vertices.remove(closest)
        self.show_status(f"Removed outline vertex at ({closest[0]}, {closest[1]}) from frame {frame}")
        return True

    def clear_outline(self):
        frame = self.imageView.currentIndex
        obj_id = self._active_obj_id()
        if self.key_frame_outlines.get(obj_id, {}).pop(frame, None) is None:
            self.show_status(f"No outline for object {obj_id} on this frame.")
            return
        self._invalidate_object(obj_id)
        self.refresh_point_overlay()
        self.show_status(f"Cleared outline for object {obj_id} on frame {frame}")

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
        outline_curves = []
        outline_vertices = []
        self._outline_refs = []
        for obj_id, frame_map in self.key_frame_outlines.items():
            vertices = frame_map.get(frame, [])
            if len(vertices) >= 4:
                outline_curves.append(sample_outline_curve(vertices))
            outline_vertices.extend(vertices)
            self._outline_refs.extend((obj_id, index) for index in range(len(vertices)))
        self.imageView.set_outline(outline_curves, outline_vertices)

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
        self.crossSectionView.set_contours_visible(show_contours)
        self.imageView.set_splines_visible(show_splines)
        self.imageView.set_spline_nodes_visible(show_nodes)
        self.imageView.set_frame_visible(show_frames)
        self.imageView.set_histogram_visible(show_histogram)

    def _frame_count(self):
        if self.pixel_array is None:
            return 0
        # Color frames carry a trailing RGB axis, so a 3D array is one frame.
        frame_ndim = 4 if self.is_color else 3
        return self.pixel_array.shape[0] if self.pixel_array.ndim >= frame_ndim else 1

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
        # refresh_key_frames_list adds one label per key frame, in key_frames order.
        row = model_index.row()
        if 0 <= row < len(self.key_frames):
            return self.key_frames[row]
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
        write_keyframes(path, self.key_frames, self.key_frame_points, self.key_frame_outlines)
        self.show_status(f"Saved key frames to {path}", 6000)

    def load_key_frames(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load key frames", "", "XML files (*.xml)"
        )
        if not path:
            return
        try:
            key_frames, key_frame_points, key_frame_outlines = read_keyframes(path, self._frame_count())
        except ET.ParseError as exc:
            QMessageBox.critical(self, "Load error", f"Could not parse file:\n{exc}")
            return
        except ValueError as exc:
            QMessageBox.critical(self, "Load error", f"Could not load key frames:\n{exc}")
            return
        self.key_frames = key_frames
        self.key_frame_points = key_frame_points
        self.key_frame_outlines = key_frame_outlines
        self._invalidate_segmentation()
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

        output_dir = Path(__file__).resolve().parents[2] / "output"
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

        output_dir = Path(__file__).resolve().parents[2] / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{dicom_stem}_contours.json"

        with output_path.open("w", encoding="utf-8") as handle:
            json.dump(contours_to_jsonable(self.segmentation_contours), handle)

        self.show_status(f"Saved contours to {output_path}", 6000)

    def _checked_checkpoint_path(self):
        checkpoint_path = self._selected_checkpoint_path()
        if checkpoint_path is None:
            raise RuntimeError("No MedSAM2 checkpoint selected. Add MedSAM2*.pt files in checkpoints/MedSAM2/.")

        if not checkpoint_path.exists():
            raise RuntimeError(f"Selected checkpoint does not exist: {checkpoint_path}")
        return checkpoint_path

    def _ensure_ready_for_segmentation(self):
        if self.pixel_array is None:
            self.show_status("Load a DICOM or video file before segmentation.")
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
        self.update_cross_section_view()

    def _invalidate_object(self, obj_id):
        """Drop one object's labels after its prompts changed; other objects keep their masks."""
        if self.segmentation_mask is not None:
            self.segmentation_mask[self.segmentation_mask == obj_id] = 0
        # Contours and splines are derived from the whole mask, so they are rebuilt on demand.
        self.segmentation_contours = None
        self.segmentation_splines = None
        self.segmentation_spline_nodes = None
        self.update_cross_section_view()

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
        self.update_cross_section_view()
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

    def _run_segmentation(self, start_message, finish_message, segment_fn, on_done,
                          needs_segmenter=True, indeterminate=False):
        """Run segment_fn(segmenter, progress) on a worker thread, then on_done(result) on the GUI thread.

        The central widget is disabled while the worker runs, so the user cannot edit
        key frames or points mid-run. on_done may start another run (chained stages).
        A model that is not loaded yet is built on the worker thread.
        """
        if self._worker is not None:
            self.show_status("A segmentation is already running.")
            return
        checkpoint_path = None
        if needs_segmenter:
            try:
                checkpoint_path = self._checked_checkpoint_path()
            except RuntimeError as exc:
                QMessageBox.critical(self, "Segmentation error", str(exc))
                return
        # The worker writes the segmenter here; the GUI thread stores it on success or failure.
        holder = {"segmenter": self.segmenter}

        def work(progress):
            if needs_segmenter and holder["segmenter"] is None:
                holder["segmenter"] = self._create_segmenter_for_selection(checkpoint_path)
            return segment_fn(holder["segmenter"], progress)

        self.stop_playback()
        self._start_segmentation_progress(start_message, indeterminate=indeterminate)
        self.centralWidget().setEnabled(False)
        worker = SegmentationWorker(work, self)
        worker.progress.connect(self._update_segmentation_progress)
        worker.succeeded.connect(
            lambda result: self._on_segmentation_succeeded(result, finish_message, on_done, holder)
        )
        worker.failed.connect(lambda message: self._on_segmentation_failed(message, holder))
        worker.finished.connect(lambda: self._on_worker_finished(worker))
        self._worker = worker
        worker.start()

    def _on_segmentation_succeeded(self, result, finish_message, on_done, holder):
        self._worker = None
        self.segmenter = holder["segmenter"]
        self._finish_segmentation_progress(finish_message)
        on_done(result)

    def _on_segmentation_failed(self, message, holder):
        self._worker = None
        self.segmenter = holder["segmenter"]
        self.seg_progress_bar.setVisible(False)
        QMessageBox.critical(self, "Segmentation error", message)

    def _on_worker_finished(self, worker):
        worker.deleteLater()
        # A chained run may already be active; only re-enable the UI when nothing is.
        if self._worker is None:
            self.centralWidget().setEnabled(True)

    def segment_selected_keyframe(self):
        if not self._ensure_ready_for_segmentation():
            return

        frame_idx, points_by_object = self._require_selected_keyframe_with_points(
            "Select a key frame for single-frame segmentation."
        )
        if frame_idx is None:
            return

        percentile_clip = self._percentile_clip_from_ui()

        self._run_segmentation(
            "Running multi-object single-frame segmentation...",
            "Single-frame segmentation done for all prompted objects. Mask overlay updated.",
            lambda segmenter, progress: segmenter.segment_single_keyframe_multi_object(
                pixel_array=self.pixel_array,
                dicom_ds=self.dicom_dataset,
                frame_idx=frame_idx,
                frame_points_by_obj=points_by_object,
                percentile_clip=percentile_clip,
                progress_callback=progress,
            ),
            lambda mask: self._finalize_segmentation_result(mask, frame_idx, frame_idx, points_by_object.keys()),
        )

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

        self._run_segmentation(
            "Running multi-object forward range segmentation...",
            f"Forward segmentation done for all prompted objects ({frame_idx}->{end_frame}). Mask overlay updated.",
            lambda segmenter, progress: segmenter.segment_forward_range_multi_object(
                pixel_array=self.pixel_array,
                dicom_ds=self.dicom_dataset,
                start_frame_idx=frame_idx,
                end_frame_idx=end_frame,
                start_frame_points_by_obj=points_by_object,
                percentile_clip=percentile_clip,
                progress_callback=progress,
            ),
            lambda mask: self._finalize_segmentation_result(mask, frame_idx, end_frame, points_by_object.keys()),
        )

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

        self._run_segmentation(
            "Running multi-object backward range segmentation...",
            f"Backward segmentation done for all prompted objects ({frame_idx}->{end_frame}). Mask overlay updated.",
            lambda segmenter, progress: segmenter.segment_backward_range_multi_object(
                pixel_array=self.pixel_array,
                dicom_ds=self.dicom_dataset,
                start_frame_idx=frame_idx,
                end_frame_idx=end_frame,
                start_frame_points_by_obj=points_by_object,
                percentile_clip=percentile_clip,
                progress_callback=progress,
            ),
            lambda mask: self._finalize_segmentation_result(mask, end_frame, frame_idx, points_by_object.keys()),
        )

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

        self._run_segmentation(
            "Running all-object segmentation...",
            "All-object segmentation done. Mask overlay updated.",
            lambda segmenter, progress: segmenter.segment_all_with_keyframes(
                pixel_array=self.pixel_array,
                dicom_ds=self.dicom_dataset,
                key_frames=list(self.key_frames),
                key_frame_points=obj_points,
                percentile_clip=percentile_clip,
                progress_callback=progress,
            ),
            lambda mask: self._finalize_segmentation_result(mask, 0, self._frame_count() - 1, obj_points.keys()),
        )

    def _custom_masks_for_frame(self, frame_idx):
        height, width = self.cross_section_volume.shape[-2:]
        masks = {}
        for obj_id, frame_map in self.key_frame_outlines.items():
            vertices = frame_map.get(frame_idx, [])
            if len(vertices) >= 4:
                masks[int(obj_id)] = build_custom_mask(vertices, height, width)
        return masks

    def track_custom_mask(self):
        if not self._ensure_ready_for_segmentation():
            return

        frame_idx = self._selected_key_frame()
        if frame_idx is None:
            self.show_status("Select a key frame for custom mask tracking.")
            return

        masks_by_obj = self._custom_masks_for_frame(frame_idx)
        if not masks_by_obj:
            self.show_status(f"Key frame {frame_idx} has no custom mask outline with at least 4 vertices.")
            return

        sorted_kf = sorted(set(self.key_frames))
        start_pos = sorted_kf.index(frame_idx)
        end_forward = (
            sorted_kf[start_pos + 1]
            if start_pos + 1 < len(sorted_kf)
            else self._frame_count() - 1
        )
        end_backward = sorted_kf[start_pos - 1] if start_pos > 0 else 0
        obj_ids = list(masks_by_obj.keys())
        percentile_clip = self._percentile_clip_from_ui()

        def run_forward():
            self._run_segmentation(
                "Tracking custom mask forward...",
                f"Forward custom mask tracking done ({frame_idx}->{end_forward}). Mask overlay updated.",
                lambda segmenter, progress: segmenter.segment_mask_range_multi_object(
                    pixel_array=self.pixel_array,
                    dicom_ds=self.dicom_dataset,
                    start_frame_idx=frame_idx,
                    end_frame_idx=end_forward,
                    start_frame_masks_by_obj=masks_by_obj,
                    percentile_clip=percentile_clip,
                    reverse=False,
                    progress_callback=progress,
                ),
                lambda mask: self._finalize_segmentation_result(mask, frame_idx, end_forward, obj_ids),
            )

        def finish_backward(mask):
            self._finalize_segmentation_result(mask, end_backward, frame_idx, obj_ids)
            run_forward()

        self._run_segmentation(
            "Tracking custom mask backward...",
            f"Backward custom mask tracking done ({frame_idx}->{end_backward}).",
            lambda segmenter, progress: segmenter.segment_mask_range_multi_object(
                pixel_array=self.pixel_array,
                dicom_ds=self.dicom_dataset,
                start_frame_idx=frame_idx,
                end_frame_idx=end_backward,
                start_frame_masks_by_obj=masks_by_obj,
                percentile_clip=percentile_clip,
                reverse=True,
                progress_callback=progress,
            ),
            finish_backward,
        )

    def fix_masks(self):
        if self.segmentation_mask is None:
            self.show_status("No segmentation mask available. Run segmentation first.")
            return

        if self.segmentation_mask.ndim not in (2, 3):
            self.show_status(f"Unsupported mask shape: {self.segmentation_mask.shape}")
            return

        iterations = int(self.smoothSpinBox.value())

        def fix(_segmenter, progress):
            return fix_labeled_mask(
                self.segmentation_mask,
                iterations,
                progress_callback=lambda done, total: progress(done, total, "Fixing masks"),
            )

        def apply(fixed_mask):
            self.segmentation_mask = fixed_mask
            self.segmentation_contours = None
            self.segmentation_splines = None
            self.segmentation_spline_nodes = None
            self.update_cross_section_view()
            self.refresh_point_overlay()

        self._run_segmentation(
            "Fixing masks...",
            f"Mask fixing complete (smooth level: {iterations}).",
            fix,
            apply,
            needs_segmenter=False,
        )

    def find_external_contours(self):
        if self.segmentation_mask is None:
            self.show_status("No segmentation mask available. Run segmentation first.")
            return

        if self.segmentation_mask.ndim not in (2, 3):
            self.show_status(f"Unsupported mask shape: {self.segmentation_mask.shape}")
            return

        epsilon = float(self.epsilonSpinBox.value())
        use_approx = epsilon > 0.0
        mask = self.segmentation_mask
        if use_approx:
            finish_message = f"External contours extracted (approxPolyDP, epsilon={epsilon:g})."
        else:
            finish_message = "External contours extracted (no approximation)."

        def extract(_segmenter, _progress):
            return find_external_contours(mask, epsilon=epsilon)

        def apply(contour_map):
            self.segmentation_contours = contour_map
            self.segmentation_splines = None
            self.segmentation_spline_nodes = None
            self.imageView.set_contour_color((255, 255, 0, 255))
            self.refresh_point_overlay()
            self.update_cross_section_view()

        self._run_segmentation(
            "Extracting contours...",
            finish_message,
            extract,
            apply,
            needs_segmenter=False,
            indeterminate=True,
        )

    def fit_contour_splines(self):
        if self.segmentation_mask is None and self.segmentation_contours is None:
            self.show_status("No segmentation mask available. Run segmentation first.")
            return

        epsilon = float(self.epsilonSpinBox.value())
        num_control_points = int(self.splineNodesSpinBox.value())
        mask = self.segmentation_mask
        contours = self.segmentation_contours

        def fit(_segmenter, _progress):
            contour_map = contours
            if contour_map is None:
                contour_map = find_external_contours(mask, epsilon=epsilon)
            splines, nodes = fit_spline_contours(
                contour_map,
                num_control_points=num_control_points,
                num_samples=num_control_points * 10,
                return_nodes=True,
            )
            return contour_map, splines, nodes

        def apply(result):
            self.segmentation_contours, self.segmentation_splines, self.segmentation_spline_nodes = result
            self.imageView.set_spline_color((0, 255, 255, 255))
            self.imageView.set_spline_nodes_color((255, 80, 80, 255))
            self.refresh_point_overlay()

        self._run_segmentation(
            "Fitting splines...",
            f"Spline fitting complete (control points: {num_control_points}).",
            fit,
            apply,
            needs_segmenter=False,
            indeterminate=True,
        )

    def open_dicom_file(self):
        file_dialog = QFileDialog(self)
        file_dialog.setNameFilter("DICOM or video files (*)")
        if file_dialog.exec():
            selected_files = file_dialog.selectedFiles()
            if selected_files:
                dicom_file_path = selected_files[0]
                try:
                    if video_io.is_video(dicom_file_path):
                        count, rows, cols, _ = video_io.read_meta(dicom_file_path)
                        pixel_array = video_io.read_frames(dicom_file_path, count, rows, cols)
                        dicom = None
                        is_color = True
                    else:
                        dicom = dicom_io.read_dataset(dicom_file_path)
                        pixel_array = dicom_io.pixel_frames(dicom)
                        is_color = dicom_io.is_color(dicom)
                except Exception as exc:
                    QMessageBox.critical(self, "Load error", f"Could not read file:\n{exc}")
                    return
                self.dicom_file_path = dicom_file_path
                self.dicom_dataset = dicom
                self.is_color = is_color
                if FRAMES_LIMIT > 0 and pixel_array.ndim > 2 and pixel_array.shape[0] > FRAMES_LIMIT:
                    pixel_array = pixel_array[:FRAMES_LIMIT]
                self.pixel_array = pixel_array
                self.imageView.remove_line()
                if self.is_color:
                    # Cross-section slices need one channel; use the mean of RGB.
                    self.cross_section_volume = pixel_array.mean(axis=-1, dtype=np.float32)
                else:
                    self.cross_section_volume = pixel_array
                self.segmentation_mask = None
                self.segmentation_contours = None
                self.segmentation_splines = None
                self.segmentation_spline_nodes = None
                self.stop_playback()
                # ImageView takes (x=col, y=row) axes. Swap rows/cols, keeping an RGB channel axis last.
                self.imageView.setImage(display_array(self.pixel_array, self.is_color))
                self.imageView.set_frame_count(self._frame_count())
                self.imageView.set_mask(None)
                self.imageView.set_contours([])
                self.imageView.set_splines([])
                self.imageView.set_spline_nodes([])
                self.key_frames.clear()
                self.key_frame_points.clear()
                self.key_frame_outlines.clear()
                self.refresh_key_frames_list()
                self.refresh_point_overlay()
                self.update_cross_section_view()
                self._sync_cross_section_histogram()
                self.show_status(f"Loaded: {dicom_file_path}", 6000)
