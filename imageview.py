import pyqtgraph as pg
import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter

class ImageView(pg.ImageView):
    dragCoordinates = Signal(int, int)
    frameChanged = Signal(int)
    # action: "positive" | "negative" | "delete"
    pointClicked = Signal(int, int, str)

    def __init__(self, parent=None):
        super().__init__(parent, view=pg.PlotItem())
        self.ui.menuBtn.hide()
        self.ui.roiBtn.hide()
        cm = pg.colormap.getFromMatplotlib('gray')
        self.setColorMap(cm)
        self.view.setAspectLocked(lock=True)
        self.view.invertY(False)
        self.ui.roiPlot.hideButtons()
        self.timeLine.sigPositionChanged.connect(self._on_timeline_changed)

        # Scatter overlays for prompt points
        self._pos_scatter = pg.ScatterPlotItem(
            symbol='o', size=12,
            pen=pg.mkPen('g', width=2),
            brush=pg.mkBrush(0, 200, 0, 160),
            hoverable=False,
        )
        self._neg_scatter = pg.ScatterPlotItem(
            symbol='o', size=12,
            pen=pg.mkPen('r', width=2),
            brush=pg.mkBrush(200, 0, 0, 160),
            hoverable=False,
        )
        self._mask_item = pg.ImageItem()
        self._mask_item.setZValue(10)
        self._mask_item.setCompositionMode(QPainter.CompositionMode_SourceOver)
        self._mask_lut = np.zeros((256, 4), dtype=np.ubyte)
        self._mask_lut[1] = [255, 0, 0, 160]
        self._mask_item.setLookupTable(self._mask_lut)
        self._mask_item.setLevels((0, 255))
        self._contour_color = (255, 255, 0, 255)
        self._contour_width = 4
        self._contour_item = pg.PlotDataItem(
            pen=pg.mkPen(self._contour_color, width=self._contour_width),
            connect="finite",
        )
        self._contour_item.setZValue(20)
        self.view.addItem(self._pos_scatter)
        self.view.addItem(self._neg_scatter)
        self.view.addItem(self._mask_item)
        self.view.addItem(self._contour_item)

        self.view.scene().sigMouseClicked.connect(self._on_scene_click)
        self.ui.roiPlot.scene().sigMouseClicked.connect(self._on_timeline_click)

    def _on_timeline_changed(self, *args):
        self.frameChanged.emit(self.currentIndex)

    def _on_scene_click(self, event):
        if event.button() != Qt.LeftButton:
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

        frame_count = self.image.shape[0] if self.image.ndim > 2 else 1
        if frame_count <= 1:
            return

        view_box = self.ui.roiPlot.getViewBox()
        clicked = view_box.mapSceneToView(event.scenePos())
        target = int(round(clicked.x()))
        target = max(0, min(frame_count - 1, target))
        self.setCurrentIndex(target)

    def set_points(self, positive_points, negative_points):
        """Update prompt-point overlays.  Each arg is a list of (x, y) tuples."""
        self._pos_scatter.setData(pos=positive_points or [])
        self._neg_scatter.setData(pos=negative_points or [])
        self.view.update()

    def set_points_visible(self, visible):
        self._pos_scatter.setVisible(bool(visible))
        self._neg_scatter.setVisible(bool(visible))
        self.view.update()

    def set_mask(self, mask_2d):
        """Display a transparent segmentation mask over the current frame."""
        if mask_2d is None:
            self._mask_item.clear()
        else:
            # Multiply by 1 so value 1 stays at LUT index 1 with levels (0, 255)
            self._mask_item.setImage(mask_2d.astype(np.uint8), autoLevels=False, levels=(0, 255))
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
            # cv2 contours are returned as (col=x, row=y); ImageItem displays with swapped axes.
            xs.extend(closed[:, 1].astype(float).tolist())
            ys.extend(closed[:, 0].astype(float).tolist())
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

    def set_contour_color(self, rgba):
        self._contour_color = tuple(rgba)
        self._contour_item.setPen(pg.mkPen(self._contour_color, width=self._contour_width))
        self.view.update()

    def set_contour_width(self, width):
        self._contour_width = max(1, int(width))
        self._contour_item.setPen(pg.mkPen(self._contour_color, width=self._contour_width))
        self.view.update()

    def set_frame_visible(self, visible):
        self.getImageItem().setVisible(bool(visible))
        self.view.update()

    def set_histogram_visible(self, visible):
        self.ui.histogram.setVisible(bool(visible))

