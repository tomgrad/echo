import pyqtgraph as pg
import numpy as np

class CrossSectionView(pg.ImageView):

    def __init__(self, parent=None):
        super().__init__(parent, view=pg.PlotItem())
        self.ui.menuBtn.hide()
        self.ui.roiBtn.hide()
        cm = pg.colormap.getFromMatplotlib('gray')
        self.setColorMap(cm)
        # Cross-section slices should stretch to fill available widget space.
        self.view.setAspectLocked(lock=False)
        self.view.hideAxis('left')
        self.view.invertY(True)
        self.view.setMouseEnabled(x=True, y=False)
        self.ui.roiPlot.hideButtons()
        self.ui.histogram.setVisible(False)
        self._histogram_levels = None
        self._locked_y_range = (0.0, 1.0)
        self._frame_count = 1
        self._current_frame = 0
        self._is_restoring_y = False
        self._frame_line = pg.InfiniteLine(
            angle=90,
            movable=False,
            pen=pg.mkPen((255, 255, 0, 255), width=2),
        )
        self._cross_section_points = pg.ScatterPlotItem(
            symbol='o',
            size=3,
            pen=pg.mkPen((255, 255, 0, 255), width=1),
            brush=pg.mkBrush((255, 255, 0, 200)),
            hoverable=False,
        )
        self._intensity = None
        self._intensity_visible = True
        self._intensity_curve = self._make_series_curve((0, 220, 255, 255))
        self._area = None
        self._area_visible = True
        self._area_curve = self._make_series_curve((255, 150, 0, 255))
        self._frame_line.setZValue(100)
        self._cross_section_points.setZValue(90)
        self._frame_line.setVisible(False)
        self.view.addItem(self._frame_line)
        self.view.addItem(self._cross_section_points)
        self.view.sigRangeChanged.connect(self._enforce_locked_y_range)

    def _enforce_locked_y_range(self, _view_box, _ranges):
        if self._is_restoring_y:
            return
        current_y_range = tuple(self.view.viewRange()[1])
        if current_y_range == self._locked_y_range:
            return
        self._is_restoring_y = True
        self.view.setYRange(self._locked_y_range[0], self._locked_y_range[1], padding=0.0)
        self._is_restoring_y = False

    def set_cross_section(self, image_2d):
        """Render a 2D cross-section slice and fit it to the full view area."""
        if image_2d is None:
            self.clear()
            self._frame_line.setVisible(False)
            self._cross_section_points.setData(pos=[])
            self._intensity_curve.setVisible(False)
            self._area_curve.setVisible(False)
            return

        prev_x_range = None
        if self.image is not None:
            prev_x_range = tuple(self.view.viewRange()[0])

        image_size = int(max(1, image_2d.shape[0]))
        frame_count = int(max(1, image_2d.shape[1]))
        self._frame_count = frame_count

        # Rotate view so cross-section slices are displayed with the expected orientation.
        rotated = np.rot90(image_2d, k=-1)
        self.setImage(rotated, autoLevels=self._histogram_levels is None)
        if self._histogram_levels is not None:
            self.setLevels(*self._histogram_levels)

        if prev_x_range is None:
            x_range = (0.0, float(frame_count))
        else:
            x0, x1 = prev_x_range
            x0 = float(np.clip(x0, 0.0, float(frame_count)))
            x1 = float(np.clip(x1, 0.0, float(frame_count)))
            if x1 - x0 < 1e-6:
                x_range = (0.0, float(frame_count))
            else:
                x_range = (x0, x1)

        self._locked_y_range = (0.0, float(image_size))
        self.view.setRange(
            xRange=x_range,
            yRange=self._locked_y_range,
            padding=0.0,
        )
        # Hard bounds keep y panning/zooming fixed while allowing free x navigation.
        self.view.setLimits(
            xMin=0.0,
            xMax=float(frame_count),
            yMin=self._locked_y_range[0],
            yMax=self._locked_y_range[1],
        )
        self.set_current_frame(self._current_frame)
        self._render_intensity()

    def _make_series_curve(self, color):
        curve = pg.PlotDataItem(pen=pg.mkPen(color, width=2), connect='finite')
        curve.setZValue(95)
        curve.setVisible(False)
        self.view.addItem(curve)
        return curve

    def set_intensity(self, values):
        """Plot a per-frame series normalized to [0, 1] (NaN = gap) over the image.

        High values are drawn near the top of the view.
        """
        self._intensity = None if values is None else np.asarray(values, dtype=float)
        self._render_series(self._intensity_curve, self._intensity, self._intensity_visible)

    def set_intensity_visible(self, visible):
        self._intensity_visible = bool(visible)
        self._render_series(self._intensity_curve, self._intensity, self._intensity_visible)

    def set_area(self, values):
        """Same as set_intensity, for the normalized mask area series."""
        self._area = None if values is None else np.asarray(values, dtype=float)
        self._render_series(self._area_curve, self._area, self._area_visible)

    def set_area_visible(self, visible):
        self._area_visible = bool(visible)
        self._render_series(self._area_curve, self._area, self._area_visible)

    def _render_intensity(self):
        self._render_series(self._intensity_curve, self._intensity, self._intensity_visible)
        self._render_series(self._area_curve, self._area, self._area_visible)

    def _render_series(self, curve, values, visible):
        if values is None or self.image is None or len(values) == 0:
            curve.setData([], [])
            curve.setVisible(False)
            return
        height = self._locked_y_range[1]
        x = np.arange(len(values), dtype=float)
        # The view's y axis is inverted, so y = 0 is the top edge.
        curve.setData(x, height * (1.0 - values))
        curve.setVisible(visible)

    def set_contour_cross_sections(self, points):
        """Display contour cross-section points in cross-section coordinates."""
        if not points:
            self._cross_section_points.setData(pos=[])
            return
        self._cross_section_points.setData(pos=points)

    def set_contours_visible(self, visible):
        self._cross_section_points.setVisible(bool(visible))

    def set_current_frame(self, frame_idx):
        self._current_frame = int(frame_idx)
        clamped = max(0, min(self._current_frame, self._frame_count - 1))
        self._frame_line.setValue(float(clamped))
        self._frame_line.setVisible(self.image is not None)

    def set_histogram_levels(self, levels):
        if levels is None:
            self._histogram_levels = None
            if self.image is not None:
                self.autoLevels()
            return

        lo, hi = levels
        self._histogram_levels = (float(lo), float(hi))
        if self.image is not None:
            self.setLevels(*self._histogram_levels)
