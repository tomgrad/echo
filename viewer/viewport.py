import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QEvent, QRunnable, Qt, QThreadPool, Signal
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


class _FrameTask(QRunnable):
    """Decode one frame off the GUI thread; the result carries its generation."""

    def __init__(self, viewport, info: RecordingInfo, index: int, generation: int):
        super().__init__()
        self._viewport = viewport
        self._info = info
        self._index = index
        self._generation = generation

    def run(self):
        try:
            frame = decode_frame(self._info, self._index)
            result = (self._generation, self._index, frame, None)
        except Exception as exc:
            result = (self._generation, self._index, None, str(exc) or type(exc).__name__)
        self._viewport._frame_decoded.emit(result)


class RecordingViewport(QFrame):
    activated = Signal(object)
    closed = Signal(object)
    scrub_requested = Signal(object, int)
    error = Signal(str)
    _frame_decoded = Signal(object)  # worker thread -> GUI thread (queued)

    def __init__(self, cache: FrameCache, parent=None) -> None:
        super().__init__(parent)
        self._cache = cache
        self._index = 0
        # On-demand decodes: at most one in flight per tile, latest request wins.
        self._generation = 0
        self._decode_busy = False
        self._wanted = 0
        self._decode_pool = QThreadPool(self)
        self._decode_pool.setMaxThreadCount(1)
        self._frame_decoded.connect(self._on_frame_decoded)
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
        self._slider.valueChanged.connect(self._on_slider_value)
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
        self._cancel_decodes()
        self.recording = info
        self.timeline = Timeline(frame_count=info.frames, fps=info.fps)
        self._failed = False
        self._error = None
        self._prefetch_failed = False
        self._index = 0
        self._set_slider_range(0, max(info.frames - 1, 0))
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
        self._show_index(0, sync=True)
        self._place_overlays()

    def set_levels(self, levels: tuple[float, float] | None) -> None:
        self.levels = levels
        if self.recording is not None:
            self._show_index(self._index)

    def set_loop(self, loop: Loop) -> None:
        # The frames stay in the shared FrameCache; the viewport keeps only the
        # levels, which the prefetched loop makes stable for the whole recording.
        if loop.levels is not None:
            self.levels = loop.levels
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
        # np.array copies: ImageItem would otherwise keep a view that pins the
        # whole loop array after the cache evicts it.
        if self.recording.is_color:
            self._image.setImage(
                np.array(dicom_io.display_array(frame, True)),
                autoLevels=False,
                levels=None,
            )
        else:
            self._image.setImage(
                np.array(dicom_io.display_array(frame, False)),
                autoLevels=False,
                levels=self.levels,
            )

    def current_frame_index(self) -> int:
        return self._index

    def clear(self) -> None:
        self._cancel_decodes()
        self.recording = None
        self.timeline = None
        self._failed = False
        self._error = None
        self._prefetch_failed = False
        self._index = 0
        self.levels = None
        self._image.clear()
        self._image.setVisible(False)
        self._set_slider_range(0, 0)
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

    def shutdown(self) -> None:
        """Stop on-demand decoding and wait for a running decode to finish."""
        self._cancel_decodes()
        self._decode_pool.waitForDone()

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)

    def _cancel_decodes(self) -> None:
        self._generation += 1
        self._decode_busy = False
        self._decode_pool.clear()

    def _set_slider_range(self, low: int, high: int) -> None:
        # A range change can clamp the value; that is not a user scrub.
        self._slider.blockSignals(True)
        self._slider.setRange(low, high)
        self._slider.blockSignals(False)

    def _on_slider_value(self, value: int) -> None:
        # Programmatic updates block signals, so only user moves reach here.
        self.scrub_requested.emit(self, int(value))

    def _present(self, index: int, frame: np.ndarray) -> None:
        self.show_frame(frame)
        self._slider.blockSignals(True)
        self._slider.setValue(index)
        self._slider.blockSignals(False)
        self._refresh_bottom()

    def _start_decode(self) -> None:
        self._decode_busy = True
        self._decode_pool.start(
            _FrameTask(self, self.recording, self._wanted, self._generation)
        )

    def _on_frame_decoded(self, result) -> None:
        generation, index, frame, error = result
        if generation != self._generation or self.recording is None:
            return
        self._decode_busy = False
        if error is not None:
            self._fail(error)
            return
        if index == self._wanted:
            self._present(index, frame)
        else:
            # The user moved on while this decode ran: show the latest request.
            self._show_index(self._wanted)

    def _show_index(self, index: int, sync: bool = False) -> None:
        if self._failed or self.recording is None:
            return
        info = self.recording
        self._index = index
        self._wanted = index
        loop = self._cache.get(info.path)
        if loop is not None:
            self._present(index, loop.frames[index])
            return
        if sync:
            try:
                frame = decode_frame(info, index)
            except Exception as exc:
                self._fail(str(exc) or type(exc).__name__)
                return
            self._present(index, frame)
            return
        # Cache miss: the counter moves now, the frame follows from the worker.
        self._refresh_bottom()
        if not self._decode_busy:
            self._start_decode()

    def _fail(self, message: str) -> None:
        self._failed = True
        self._error = message
        self._refresh_bottom()
        self.error.emit(message)

    def _state(self) -> str:
        assert self.recording is not None
        if self.recording.is_still:
            return "STILL"
        if self._cache.get(self.recording.path) is not None:
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
