import math
import time
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal


@dataclass
class Timeline:
    frame_count: int
    fps: float
    loop_start: int = 0
    loop_end: int = -1
    offset_s: float = 0.0

    def __post_init__(self) -> None:
        if self.fps <= 0:
            raise ValueError("fps must be positive")
        last = max(self.frame_count - 1, 0)
        end = last if self.loop_end == -1 else self.loop_end
        self.loop_start = min(max(self.loop_start, 0), last)
        self.loop_end = min(max(end, self.loop_start), last)

    @property
    def loop_duration_s(self) -> float:
        return (self.loop_end - self.loop_start + 1) / self.fps

    def frame_at(self, t: float) -> int:
        if self.frame_count <= 1:
            return 0
        local = (t - self.offset_s) % self.loop_duration_s
        index = self.loop_start + math.floor(local * self.fps)
        return min(max(index, self.loop_start), self.loop_end)


class PlaybackClock(QObject):
    position_changed = Signal(float)

    def __init__(self, parent=None, interval_ms: int = 16) -> None:
        super().__init__(parent)
        self._position = 0.0
        self._started_at = 0.0
        self._playing = False
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._on_timeout)

    def play(self) -> None:
        if self._playing:
            return
        self._started_at = time.monotonic()
        self._playing = True
        self._timer.start()

    def pause(self) -> None:
        if not self._playing:
            return
        self._position = self.position_s
        self._playing = False
        self._timer.stop()

    @property
    def is_playing(self) -> bool:
        return self._playing

    @property
    def position_s(self) -> float:
        if not self._playing:
            return self._position
        return self._position + (time.monotonic() - self._started_at)

    def set_position_s(self, t: float) -> None:
        self._position = float(t)
        if self._playing:
            self._started_at = time.monotonic()

    def _on_timeout(self) -> None:
        self._position = self.position_s
        self._started_at = time.monotonic()
        self.position_changed.emit(self._position)


class PlaybackController(QObject):
    state_changed = Signal(bool)  # True while playing

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._viewports: list = []
        self._clocks: list = []  # (viewport, private PlaybackClock) pairs
        self._synced = True
        self._loop = True
        self._playing = False
        self.shared_clock = PlaybackClock(self)
        self.shared_clock.position_changed.connect(self._on_shared_tick)

    def add_viewport(self, viewport) -> None:
        clock = PlaybackClock(self)
        clock.position_changed.connect(
            lambda t, v=viewport: self._on_private_tick(v, t)
        )
        self._viewports.append(viewport)
        self._clocks.append((viewport, clock))
        viewport.scrub_requested.connect(self.scrub)

    def set_synced(self, synced: bool) -> None:
        was_playing = self._playing
        self.pause()
        self._synced = bool(synced)
        if self._synced:
            self.shared_clock.set_position_s(0.0)
        for viewport, clock in self._clocks:
            clock.set_position_s(0.0)
        for viewport in self._viewports:
            if viewport.recording is None:
                continue
            viewport.show_time(0.0, hold_at_end=self._synced)
        if was_playing:
            self.play()

    def set_loop(self, enabled: bool) -> None:
        self._loop = bool(enabled)

    def play(self) -> None:
        if self._synced:
            period = self._synced_period()
            if not self._loop and period > 0 and self.shared_clock.position_s >= period:
                self.shared_clock.set_position_s(0.0)
                self.show_current()
            self.shared_clock.play()
        else:
            for _, clock in self._clocks:
                clock.play()
        self._set_playing(True)

    def pause(self) -> None:
        self.shared_clock.pause()
        for _, clock in self._clocks:
            clock.pause()
        self._set_playing(False)

    def restart(self) -> None:
        self.pause()
        self.shared_clock.set_position_s(0.0)
        for _, clock in self._clocks:
            clock.set_position_s(0.0)
        self.show_current()
        self.state_changed.emit(False)

    def scrub(self, viewport, frame_index: int) -> None:
        time_s = frame_index / viewport.timeline.fps
        if self._synced:
            self.shared_clock.set_position_s(time_s)
            self.show_current()
            return
        for owner, clock in self._clocks:
            if owner is viewport:
                clock.set_position_s(time_s)
                viewport.show_time(time_s, hold_at_end=False)
                return

    def show_current(self) -> None:
        if self._synced:
            t = self.shared_clock.position_s
            for viewport in self._visible_viewports():
                viewport.show_time(t, hold_at_end=True)
            return
        for viewport, clock in self._clocks:
            if not viewport.isHidden() and viewport.recording is not None:
                viewport.show_time(clock.position_s, hold_at_end=False)

    def _on_shared_tick(self, t: float) -> None:
        if not self._synced:
            return
        period = self._synced_period()
        if period > 0 and t >= period:
            if self._loop:
                self.shared_clock.set_position_s(0.0)
                for viewport in self._visible_viewports():
                    viewport.show_time(0.0, hold_at_end=True)
                return
            self.shared_clock.set_position_s(period)
            self.pause()
            for viewport in self._visible_viewports():
                viewport.show_time(period, hold_at_end=True)
            return
        for viewport in self._visible_viewports():
            viewport.show_time(t, hold_at_end=True)

    def _on_private_tick(self, viewport, t: float) -> None:
        if (
            viewport.isHidden()
            or viewport.recording is None
            or viewport.timeline is None
        ):
            return
        viewport.show_time(t, hold_at_end=False)

    def _visible_viewports(self) -> list:
        return [
            v
            for v in self._viewports
            if not v.isHidden() and v.recording is not None and v.timeline is not None
        ]

    def _synced_period(self) -> float:
        periods = [
            v.timeline.loop_duration_s
            for v in self._visible_viewports()
            if not v.recording.is_still
        ]
        return max(periods, default=0.0)

    def _set_playing(self, playing: bool) -> None:
        self._playing = playing
        self.state_changed.emit(playing)

    @property
    def synced(self) -> bool:
        return self._synced

    @property
    def loop_enabled(self) -> bool:
        return self._loop

    @property
    def is_playing(self) -> bool:
        return self._playing
