import pyqtgraph as pg
import numpy as np

class LongitudinalView(pg.ImageView):

    def __init__(self, parent=None):
        super().__init__(parent, view=pg.PlotItem())
        self.ui.menuBtn.hide()
        self.ui.roiBtn.hide()
        cm = pg.colormap.getFromMatplotlib('gray')
        self.setColorMap(cm)
        # Longitudinal slices should stretch to fill available widget space.
        self.view.setAspectLocked(lock=False)
        self.view.hideAxis('left')
        self.view.invertY(True)
        self.view.setMouseEnabled(x=True, y=False)
        self.ui.roiPlot.hideButtons()
        self.ui.histogram.setVisible(False)
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
        """Render a 2D longitudinal slice and fit it to the full view area."""
        if image_2d is None:
            self.clear()
            self._frame_line.setVisible(False)
            self._cross_section_points.setData(pos=[])
            return

        image_size = int(max(1, image_2d.shape[0]))
        frame_count = int(max(1, image_2d.shape[1]))
        self._frame_count = frame_count

        # Rotate view so longitudinal slices are displayed with the expected orientation.
        rotated = np.rot90(image_2d, k=-1)
        self.setImage(rotated, autoLevels=True)

        rows, cols = rotated.shape
        self._locked_y_range = (0.0, float(image_size))
        self.view.setRange(
            xRange=(0.0, float(frame_count)),
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

    def set_contour_cross_sections(self, points):
        """Display contour cross-section points in longitudinal coordinates."""
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
