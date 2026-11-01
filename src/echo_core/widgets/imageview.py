import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QEvent, QPointF, Qt, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QGraphicsView

OUTLINE_HANDLE_RADIUS_PX = 10


class ImageView(pg.ImageView):
    frameChanged = Signal(int)
    # action: "positive" | "negative" | "delete"
    pointClicked = Signal(int, int, str)
    # Emitted while the user drags the custom cross-section line.
    lineChanged = Signal()
    # Custom mask vertex drag: handle index into the last set_outline() vertices.
    outlineHandlePressed = Signal(int)
    outlineHandleMoved = Signal(int, int)
    outlineHandleReleased = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, view=pg.PlotItem())
        self.ui.menuBtn.hide()
        self.ui.roiBtn.hide()
        cm = pg.colormap.getFromMatplotlib("gray")
        self.setColorMap(cm)
        self.view.setAspectLocked(lock=True)
        # Image axes are (x=col, y=row) with row 0 at the top.
        self.view.invertY(True)
        # self.ui.roiPlot.hideButtons()
        self.timeLine.sigPositionChanged.connect(self._on_timeline_changed)

        # Number of frames on the timeline; set by the owner, since RGB frames look 3D.
        self._frame_count = 1
        # Dynamic scatter overlays by object id.
        self._point_items = {}
        self._points_visible = True
        self._mask_item = pg.ImageItem()
        self._mask_item.setZValue(10)
        self._mask_item.setCompositionMode(QPainter.CompositionMode_SourceOver)
        self._contour_color = (255, 255, 0, 255)
        self._contour_width = 4
        self._contour_item = pg.PlotDataItem(
            pen=pg.mkPen(self._contour_color, width=self._contour_width),
            connect="finite",
        )
        self._spline_color = (0, 255, 255, 255)
        self._spline_width = 4
        self._spline_item = pg.PlotDataItem(
            pen=pg.mkPen(self._spline_color, width=self._spline_width),
            connect="finite",
        )
        self._spline_nodes_color = (255, 80, 80, 255)
        self._spline_nodes_item = pg.ScatterPlotItem(
            symbol="o",
            size=8,
            pen=pg.mkPen(self._spline_nodes_color, width=1),
            brush=pg.mkBrush(self._spline_nodes_color),
            hoverable=False,
        )
        self._outline_vertex_xy = np.zeros((0, 2))
        self._outline_edit_enabled = False
        self._outline_drag_index = None
        self.ui.graphicsView.viewport().installEventFilter(self)
        # Partial repaints leave stale thin lines while the cross-section ROI moves.
        self.ui.graphicsView.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self._outline_color = (255, 160, 0, 255)
        self._outline_item = pg.PlotDataItem(
            pen=pg.mkPen(self._outline_color, width=2),
            connect="finite",
        )
        self._outline_vertices_item = pg.ScatterPlotItem(
            symbol="s",
            size=7,
            pen=pg.mkPen(self._outline_color, width=1),
            brush=pg.mkBrush(self._outline_color),
            hoverable=False,
        )
        self._contour_item.setZValue(20)
        self._spline_item.setZValue(21)
        self._spline_nodes_item.setZValue(22)
        self._outline_item.setZValue(23)
        self._outline_vertices_item.setZValue(24)
        self._line_roi = None
        self.view.addItem(self._mask_item)
        self.view.addItem(self._contour_item)
        self.view.addItem(self._spline_item)
        self.view.addItem(self._spline_nodes_item)
        self.view.addItem(self._outline_item)
        self.view.addItem(self._outline_vertices_item)

        self.view.scene().sigMouseClicked.connect(self._on_scene_click)
        self.ui.roiPlot.scene().sigMouseClicked.connect(self._on_timeline_click)

    def set_frame_count(self, frame_count):
        self._frame_count = max(1, int(frame_count))

    def _on_timeline_changed(self, *args):
        self.frameChanged.emit(self.currentIndex)

    def _on_scene_click(self, event):
        if event.button() != Qt.LeftButton:
            return
        # Clicks on the cross-section line or its handles are not prompt points.
        if self._line_roi is not None and self._line_roi.isVisible():
            for item in self.view.scene().items(event.scenePos()):
                if item is self._line_roi or item.parentItem() is self._line_roi:
                    return
        img_item = self.getImageItem()
        if img_item.image is None:
            return
        pos = img_item.mapFromScene(event.scenePos())
        if not img_item.boundingRect().contains(pos):
            return
        mods = event.modifiers()
        if mods & Qt.ControlModifier:
            action = "delete"
        elif mods & Qt.ShiftModifier:
            action = "negative"
        else:
            action = "positive"
        self.pointClicked.emit(int(pos.x()), int(pos.y()), action)

    def _on_timeline_click(self, event):
        if event.button() != Qt.LeftButton:
            return
        if self.image is None:
            return

        frame_count = self._frame_count
        if frame_count <= 1:
            return

        view_box = self.ui.roiPlot.getViewBox()
        clicked = view_box.mapSceneToView(event.scenePos())
        target = int(round(clicked.x()))
        target = max(0, min(frame_count - 1, target))
        self.setCurrentIndex(target)

    def _color_for_obj_id(self, obj_id):
        # Use deterministic HSV wheel to keep object colors stable across frames.
        hue = (int(obj_id) * 53) % 360
        return pg.hsvColor(hue / 360.0, sat=0.85, val=1.0, alpha=0.95)

    def _point_items_for_obj(self, obj_id):
        obj_id = int(obj_id)
        if obj_id in self._point_items:
            return self._point_items[obj_id]

        color = self._color_for_obj_id(obj_id)
        pen = pg.mkPen(color, width=2)
        pos = pg.ScatterPlotItem(
            symbol="o",
            size=12,
            pen=pen,
            brush=pg.mkBrush(color),
            hoverable=False,
        )
        neg = pg.ScatterPlotItem(
            symbol="x",
            size=12,
            pen=pen,
            brush=pg.mkBrush(color),
            hoverable=False,
        )
        pos.setVisible(self._points_visible)
        neg.setVisible(self._points_visible)
        self.view.addItem(pos)
        self.view.addItem(neg)
        self._point_items[obj_id] = {"positive": pos, "negative": neg}
        return self._point_items[obj_id]

    def set_points_by_object(self, points_by_object):
        """Update prompt points for all objects.

        points_by_object format:
            {obj_id: {"positive": [(x, y), ...], "negative": [(x, y), ...]}}
        """
        active_ids = {int(obj_id) for obj_id in points_by_object.keys()}

        for obj_id in active_ids:
            items = self._point_items_for_obj(obj_id)
            obj_points = points_by_object.get(obj_id, {})
            items["positive"].setData(pos=obj_points.get("positive") or [])
            items["negative"].setData(pos=obj_points.get("negative") or [])

        # Clear stale object markers when they are not present on the frame.
        for obj_id, items in self._point_items.items():
            if obj_id in active_ids:
                continue
            items["positive"].setData(pos=[])
            items["negative"].setData(pos=[])

        self.view.update()

    def set_points_visible(self, visible):
        self._points_visible = bool(visible)
        for items in self._point_items.values():
            items["positive"].setVisible(self._points_visible)
            items["negative"].setVisible(self._points_visible)
        self.view.update()

    def set_mask(self, mask_2d):
        """Display a transparent segmentation mask over the current frame."""
        if mask_2d is None:
            self._mask_item.clear()
        else:
            # Colour each label directly into RGBA, so labels above 255 are not truncated.
            labels = np.asarray(mask_2d)
            palette = np.zeros((int(labels.max()) + 1 if labels.size else 1, 4), dtype=np.uint8)
            for label in np.unique(labels):
                if label == 0:
                    continue
                rgba = self._color_for_obj_id(int(label)).getRgb()
                palette[label] = [rgba[0], rgba[1], rgba[2], 160]
            # Image axes are (x=col, y=row), so transpose (rows, cols, 4) -> (cols, rows, 4).
            self._mask_item.setImage(palette[labels].transpose(1, 0, 2), autoLevels=False)
        self.view.update()

    def set_mask_visible(self, visible):
        self._mask_item.setVisible(bool(visible))
        self.view.update()

    def set_contours(self, contours):
        """Display external contours as polylines over the current frame."""
        if not contours:
            self._contour_item.clear()
            self.view.update()
            return

        xs = []
        ys = []
        for contour in contours:
            pts = np.asarray(contour)
            if pts.ndim != 2 or pts.shape[1] != 2 or pts.shape[0] < 2:
                continue
            # Close contour loop and separate contours with NaN for connect='finite'.
            closed = np.vstack([pts, pts[0]])
            # cv2 contours are (x=col, y=row), matching the image axes.
            xs.extend(closed[:, 0].astype(float).tolist())
            ys.extend(closed[:, 1].astype(float).tolist())
            xs.append(np.nan)
            ys.append(np.nan)

        if not xs:
            self._contour_item.clear()
        else:
            self._contour_item.setData(x=xs, y=ys)
        self.view.update()

    def set_contours_visible(self, visible):
        self._contour_item.setVisible(bool(visible))
        self.view.update()

    def set_splines(self, splines):
        """Display spline curves as polylines over the current frame."""
        if not splines:
            self._spline_item.clear()
            self.view.update()
            return

        xs = []
        ys = []
        for spline in splines:
            pts = np.asarray(spline)
            if pts.ndim != 2 or pts.shape[1] != 2 or pts.shape[0] < 2:
                continue
            closed = np.vstack([pts, pts[0]])
            xs.extend(closed[:, 0].astype(float).tolist())
            ys.extend(closed[:, 1].astype(float).tolist())
            xs.append(np.nan)
            ys.append(np.nan)

        if not xs:
            self._spline_item.clear()
        else:
            self._spline_item.setData(x=xs, y=ys)
        self.view.update()

    def set_outline_edit_enabled(self, enabled):
        """Allow dragging custom mask vertices with the left mouse button."""
        self._outline_edit_enabled = bool(enabled)
        self._outline_drag_index = None

    def _outline_handle_at(self, pos):
        """Index of the outline vertex under viewport position pos, or None."""
        img_item = self.getImageItem()
        best_index = None
        best_d2 = OUTLINE_HANDLE_RADIUS_PX ** 2
        for index, (x, y) in enumerate(self._outline_vertex_xy):
            handle = self.ui.graphicsView.mapFromScene(img_item.mapToScene(QPointF(x, y)))
            d2 = (handle.x() - pos.x()) ** 2 + (handle.y() - pos.y()) ** 2
            if d2 <= best_d2:
                best_index = index
                best_d2 = d2
        return best_index

    def _image_xy_from_viewport(self, pos):
        scene_pos = self.ui.graphicsView.mapToScene(pos)
        image_pos = self.getImageItem().mapFromScene(scene_pos)
        return int(round(image_pos.x())), int(round(image_pos.y()))

    def eventFilter(self, obj, event):
        if obj is not self.ui.graphicsView.viewport() or not self._outline_edit_enabled:
            return False
        kind = event.type()
        if kind == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            index = self._outline_handle_at(event.position().toPoint())
            if index is None:
                return False
            self._outline_drag_index = index
            self.outlineHandlePressed.emit(index)
            return True
        if kind == QEvent.MouseMove and self._outline_drag_index is not None:
            x, y = self._image_xy_from_viewport(event.position().toPoint())
            self.outlineHandleMoved.emit(x, y)
            return True
        if kind == QEvent.MouseButtonRelease and self._outline_drag_index is not None:
            self._outline_drag_index = None
            self.outlineHandleReleased.emit()
            return True
        return False

    def set_outline(self, curves, vertices):
        """Display custom mask outlines: closed spline curves and their vertices."""
        self._outline_vertex_xy = np.asarray(vertices, dtype=float).reshape(-1, 2)
        xs = []
        ys = []
        for curve in curves:
            pts = np.asarray(curve)
            if pts.ndim != 2 or pts.shape[1] != 2 or pts.shape[0] < 2:
                continue
            closed = np.vstack([pts, pts[0]])
            xs.extend(closed[:, 0].astype(float).tolist())
            ys.extend(closed[:, 1].astype(float).tolist())
            xs.append(np.nan)
            ys.append(np.nan)

        if xs:
            self._outline_item.setData(x=xs, y=ys)
        else:
            self._outline_item.clear()

        if len(vertices) == 0:
            self._outline_vertices_item.setData(pos=[])
        else:
            self._outline_vertices_item.setData(pos=np.asarray(vertices, dtype=float))
        self.view.update()

    def set_splines_visible(self, visible):
        self._spline_item.setVisible(bool(visible))
        self.view.update()

    def set_spline_nodes(self, nodes):
        """Display spline control nodes over the current frame."""
        if not nodes:
            self._spline_nodes_item.setData(pos=[])
            self.view.update()
            return

        xs = []
        ys = []
        for node_set in nodes:
            pts = np.asarray(node_set)
            if pts.ndim != 2 or pts.shape[1] != 2 or pts.shape[0] < 1:
                continue
            xs.extend(pts[:, 0].astype(float).tolist())
            ys.extend(pts[:, 1].astype(float).tolist())

        if not xs:
            self._spline_nodes_item.setData(pos=[])
        else:
            self._spline_nodes_item.setData(x=xs, y=ys)
        self.view.update()

    def set_spline_nodes_visible(self, visible):
        self._spline_nodes_item.setVisible(bool(visible))
        self.view.update()

    def set_contour_color(self, rgba):
        self._contour_color = tuple(rgba)
        self._contour_item.setPen(
            pg.mkPen(self._contour_color, width=self._contour_width)
        )
        self.view.update()

    def set_spline_color(self, rgba):
        self._spline_color = tuple(rgba)
        self._spline_item.setPen(pg.mkPen(self._spline_color, width=self._spline_width))
        self.view.update()

    def set_spline_nodes_color(self, rgba):
        self._spline_nodes_color = tuple(rgba)
        self._spline_nodes_item.setPen(pg.mkPen(self._spline_nodes_color, width=1))
        self._spline_nodes_item.setBrush(pg.mkBrush(self._spline_nodes_color))
        self.view.update()

    def set_contour_width(self, width):
        self._contour_width = max(1, int(width))
        self._contour_item.setPen(
            pg.mkPen(self._contour_color, width=self._contour_width)
        )
        self.view.update()

    def set_spline_width(self, width):
        self._spline_width = max(1, int(width))
        self._spline_item.setPen(pg.mkPen(self._spline_color, width=self._spline_width))
        self.view.update()

    def set_line_endpoints(self, p0, p1):
        """Create the editable cross-section line from p0 to p1, given as (x=col, y=row)."""
        self.remove_line()
        roi = pg.LineSegmentROI(
            positions=[p0, p1],
            pen=pg.mkPen((0, 255, 0, 255), width=3),
        )
        roi.setZValue(30)
        roi.sigRegionChanged.connect(lambda *_args: self.lineChanged.emit())
        self.view.addItem(roi)
        self._line_roi = roi

    def remove_line(self):
        if self._line_roi is not None:
            self.view.removeItem(self._line_roi)
            self._line_roi = None

    def set_line_visible(self, visible):
        if self._line_roi is not None:
            self._line_roi.setVisible(bool(visible))
        self.view.update()

    def line_endpoints(self):
        """Return [(x, y), (x, y)] for the cross-section line, or None when there is no line."""
        if self._line_roi is None:
            return None
        return [
            (float(p.x()), float(p.y()))
            for p in (self._line_roi.mapToParent(handle.pos()) for handle in self._line_roi.endpoints)
        ]

    def set_frame_visible(self, visible):
        self.getImageItem().setVisible(bool(visible))
        self.view.update()

    def set_histogram_visible(self, visible):
        self.ui.histogram.setVisible(bool(visible))
