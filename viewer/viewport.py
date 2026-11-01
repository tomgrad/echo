import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
)

import dicom_io
from viewer.frames import FrameCache, Loop, decode_frame
from viewer.playback import Timeline
from viewer.session import RecordingInfo

_OVERLAY_STYLE = "color: #e8e8e8; background: rgba(0, 0, 0, 120); padding: 2px 4px;"
_ACTIVE_STYLE = 'RecordingViewport[active="true"] { border: 2px solid #5aa9e6; }'


def _overlay_label(parent) -> QLabel:
    label = QLabel(parent)
    label.setStyleSheet(_OVERLAY_STYLE)
    label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    return label


class RecordingViewport(QFrame):
    activated = Signal(object)
    closed = Signal(object)
    scrub_requested = Signal(object, int)
    error = Signal(str)

    def __init__(self, cache: FrameCache, parent=None) -> None:
        super().__init__(parent)
        self._cache = cache
        self._loop: Loop | None = None
        self._index = 0
        self._failed = False
        self._error: str | None = None
        self._prefetch_failed = False
        self.recording: RecordingInfo | None = None
        self.timeline: Timeline | None = None
        self.levels: tuple[float, float] | None = None

        self.setStyleSheet(_ACTIVE_STYLE)
        self.setProperty("active", "false")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._plot = pg.PlotWidget(self)
        self._plot.setAspectLocked(True)
        self._plot.invertY(True)
        self._plot.setMouseEnabled(False, False)
        self._plot.setMenuEnabled(False)
        self._plot.hideAxis("left")
        self._plot.hideAxis("bottom")
        self._image = pg.ImageItem()
        self._plot.addItem(self._image)

        self._top_left = _overlay_label(self._plot)
        self._top_right = _overlay_label(self._plot)
        self._bottom_left = _overlay_label(self._plot)
        self._empty = _overlay_label(self._plot)
        self._empty.setText("No recording")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setStyleSheet("color: #909090; font-size: 14px;")

        self._plot.viewport().installEventFilter(self)
        self._plot.installEventFilter(self)

        self._slider = QSlider(Qt.Orientation.Horizontal, self)
        self._slider.sliderMoved.connect(self._on_slider_moved)
        self._counter = QLabel(self)
        self._close_button = QPushButton("×", self)
        self._close_button.setFixedWidth(28)
        self._close_button.clicked.connect(lambda: self.closed.emit(self))

        bottom = QHBoxLayout()
        bottom.addWidget(self._slider, 1)
        bottom.addWidget(self._counter)
        bottom.addWidget(self._close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self._plot, 1)
        layout.addLayout(bottom)

        self.clear()

    # ----- public API -------------------------------------------------

    def set_recording(self, info: RecordingInfo) -> None:
        self.recording = info
        self.timeline = Timeline(frame_count=info.frames, fps=info.fps)
        self._loop = None
        self._failed = False
        self._error = None
        self._prefetch_failed = False
        self._index = 0
        self._slider.setRange(0, max(info.frames - 1, 0))
        self._slider.setVisible(not info.is_still and info.frames > 1)
        self._empty.hide()
        self._top_left.setText(
            f"{info.patient_name}\n{info.patient_id} · {info.study_date}"
        )
        hr = f"HR {info.heart_rate}" if info.heart_rate is not None else "HR —"
        self._top_right.setText(
            f"inst {info.instance_number} · {info.acquisition_datetime[8:14]} · "
            f"{info.frames}f · {info.fps:g} fps · {hr}"
        )
        self._top_left.show()
        self._top_right.show()
        self._bottom_left.show()
        if info.is_color:
            self.levels = None
        else:
            try:
                mid = decode_frame(info, info.frames // 2)
                self.levels = dicom_io.mono_levels(mid)
            except Exception as exc:
                # Drop the previous recording's image and levels so the old
                # frame is not left visible under the error.
                self.levels = None
                self._image.clear()
                self._image.setVisible(False)
                self._fail(str(exc) or type(exc).__name__)
                self._place_overlays()
                return
        self.show_time(0.0, hold_at_end=False)
        self._place_overlays()

    def set_levels(self, levels: tuple[float, float] | None) -> None:
        self.levels = levels
        if self.recording is not None:
            self._show_index(self._index)

    def set_loop(self, loop: Loop) -> None:
        self._loop = loop
        if self.recording is not None:
            self._show_index(self._index)
        self._refresh_bottom()

    def mark_prefetch_failed(self) -> None:
        self._prefetch_failed = True
        self._refresh_bottom()

    def show_time(self, t: float, hold_at_end: bool) -> None:
        if self.recording is None or self.timeline is None:
            return
        if self.recording.is_still:
            index = 0
        elif hold_at_end and t >= self.timeline.loop_duration_s:
            index = self.timeline.loop_end
        else:
            index = self.timeline.frame_at(t)
        self._show_index(index)

    def show_frame(self, frame: np.ndarray) -> None:
        if self.recording is None:
            return
        self._image.setVisible(True)
        if self.recording.is_color:
            self._image.setImage(
                dicom_io.display_array(frame, True), autoLevels=False, levels=None
            )
        else:
            self._image.setImage(
                dicom_io.display_array(frame, False),
                autoLevels=False,
                levels=self.levels,
            )

    def current_frame_index(self) -> int:
        return self._index

    def clear(self) -> None:
        self.recording = None
        self.timeline = None
        self._loop = None
        self._failed = False
        self._error = None
        self._prefetch_failed = False
        self._index = 0
        self.levels = None
        self._image.clear()
        self._image.setVisible(False)
        self._slider.setRange(0, 0)
        self._slider.setVisible(False)
        self._counter.setText("")
        self._top_left.hide()
        self._top_right.hide()
        self._bottom_left.hide()
        self._empty.show()
        self._empty.raise_()
        self._place_overlays()

    def set_active(self, active: bool) -> None:
        self.setProperty("active", "true" if active else "false")
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    # ----- layout and events -----------------------------------------

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_overlays()

    def _place_overlays(self) -> None:
        width = self._plot.width()
        height = self._plot.height()
        margin = 8
        for label in (self._top_left, self._top_right, self._bottom_left):
            label.adjustSize()
        self._top_left.move(margin, margin)
        self._top_right.move(width - self._top_right.width() - margin, margin)
        self._bottom_left.move(margin, height - self._bottom_left.height() - margin)
        self._empty.setGeometry(0, 0, width, height)

    def eventFilter(self, obj, event):
        if obj is self._plot.viewport() and event.type() == QEvent.Type.MouseButtonPress:
            self.activated.emit(self)
        elif obj is self._plot and event.type() == QEvent.Type.Resize:
            self._place_overlays()
        return super().eventFilter(obj, event)

    # ----- internals --------------------------------------------------

    def _on_slider_moved(self, value: int) -> None:
        self.scrub_requested.emit(self, int(value))

    def _show_index(self, index: int) -> None:
        if self._failed or self.recording is None:
            return
        info = self.recording
        loop = self._cache.get(info.path)
        if loop is None:
            loop = self._loop
        if loop is not None:
            frame = loop.frames[index]
        else:
            try:
                frame = decode_frame(info, index)
            except Exception as exc:
                self._fail(str(exc) or type(exc).__name__)
                return
        self._index = index
        self.show_frame(frame)
        self._slider.blockSignals(True)
        self._slider.setValue(index)
        self._slider.blockSignals(False)
        self._refresh_bottom()

    def _fail(self, message: str) -> None:
        self._failed = True
        self._error = message
        self._refresh_bottom()
        self.error.emit(message)

    def _state(self) -> str:
        assert self.recording is not None
        if self.recording.is_still:
            return "STILL"
        if self._loop is not None or self._cache.get(self.recording.path) is not None:
            return "LOOP"
        if self._prefetch_failed:
            return "ON DEMAND"
        return "LOADING"

    def _refresh_bottom(self) -> None:
        if self.recording is None:
            return
        counter = f"{self._index + 1}/{self.recording.frames}"
        if self._error is not None:
            self._counter.setText(f"error: {self._error}")
            self._bottom_left.setText(f"error: {self._error}")
        else:
            self._counter.setText(counter)
            self._bottom_left.setText(f"{counter} · {self._state()}")
        self._place_overlays()
