import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from echo_viewer.playback import PlaybackController, Timeline  # noqa: E402


class FakeViewport(QObject):
    scrub_requested = Signal(object, int)

    def __init__(self, frames, fps, *, still=False, hidden=False):
        super().__init__()
        self.recording = SimpleNamespace(frames=frames, fps=fps, is_still=still)
        self.timeline = Timeline(frame_count=frames, fps=fps)
        self.hidden = hidden
        self.calls = []

    def isHidden(self):
        return self.hidden

    def show_time(self, t, hold_at_end):
        self.calls.append((t, hold_at_end))


@pytest.fixture
def controller():
    QApplication.instance() or QApplication([])
    ctrl = PlaybackController()
    yield ctrl
    ctrl.pause()


def _viewports(controller):
    long = FakeViewport(10, 10)  # 1.0 s
    short = FakeViewport(5, 10)  # 0.5 s
    still = FakeViewport(1, 30, still=True)
    hidden = FakeViewport(20, 10, hidden=True)  # 2.0 s, must not set the period
    for viewport in (long, short, still, hidden):
        controller.add_viewport(viewport)
        viewport.calls.clear()
    return long, short, still, hidden


def test_wraps_at_loop_duration():
    timeline = Timeline(frame_count=10, fps=10)
    assert timeline.frame_at(0.0) == 0
    assert timeline.frame_at(0.35) == 3
    assert timeline.frame_at(0.99) == 9
    assert timeline.frame_at(1.0) == 0


def test_loop_range_and_offset():
    timeline = Timeline(
        frame_count=10, fps=10, loop_start=2, loop_end=5, offset_s=0.5
    )
    assert timeline.loop_duration_s == pytest.approx(0.4)
    assert timeline.frame_at(0.5) == 2
    assert timeline.frame_at(0.85) == 5
    assert timeline.frame_at(0.95) == 2


def test_still_recording_always_frame_zero():
    assert Timeline(frame_count=1, fps=30).frame_at(2.5) == 0


def test_defaults_and_clamping():
    timeline = Timeline(frame_count=10, fps=10)
    assert timeline.loop_start == 0
    assert timeline.loop_end == 9
    clamped = Timeline(frame_count=5, fps=10, loop_start=-3, loop_end=99)
    assert clamped.loop_start == 0
    assert clamped.loop_end == 4


def test_rejects_non_positive_fps():
    with pytest.raises(ValueError):
        Timeline(frame_count=5, fps=0)


def test_synced_tick_holds_short_tile_and_skips_hidden(controller):
    long, short, still, hidden = _viewports(controller)
    controller.play()
    controller._on_shared_tick(0.7)
    assert long.calls[-1] == (0.7, True)
    assert short.calls[-1] == (0.7, True)  # 0.5 s tile holds its last frame
    assert still.calls[-1] == (0.7, True)
    assert hidden.calls == []
    assert controller.is_playing


def test_synced_loop_restarts_at_longest_visible_period(controller):
    long, short, *_ = _viewports(controller)
    controller.play()
    controller._on_shared_tick(1.0)  # hidden 2 s tile is ignored
    assert controller.shared_clock.position_s == pytest.approx(0.0, abs=0.05)
    assert long.calls[-1] == (0.0, True)
    assert short.calls[-1] == (0.0, True)
    assert controller.is_playing


def test_synced_without_loop_pauses_at_period(controller):
    long, *_ = _viewports(controller)
    states = []
    controller.state_changed.connect(states.append)
    controller.set_loop(False)
    controller.play()
    controller._on_shared_tick(1.2)
    assert not controller.is_playing
    assert states[-1] is False
    assert long.calls[-1] == (pytest.approx(1.0), True)
    assert controller.shared_clock.position_s == pytest.approx(1.0, abs=0.05)


def test_synced_scrub_moves_all_visible_tiles(controller):
    long, short, still, hidden = _viewports(controller)
    controller.scrub(long, 5)
    assert controller.shared_clock.position_s == pytest.approx(0.5)
    assert short.calls[-1] == (pytest.approx(0.5), True)
    assert hidden.calls == []


def test_independent_scrub_moves_only_that_tile(controller):
    long, short, *_ = _viewports(controller)
    controller.set_synced(False)
    long.calls.clear()
    short.calls.clear()
    controller.scrub(long, 5)
    assert long.calls[-1] == (pytest.approx(0.5), False)
    assert short.calls == []


def test_toggling_sync_rebases_to_zero(controller):
    long, short, *_ = _viewports(controller)
    controller.scrub(long, 5)
    controller.set_synced(False)
    assert long.calls[-1] == (0.0, False)
    assert short.calls[-1] == (0.0, False)
    controller.set_synced(True)
    assert controller.shared_clock.position_s == pytest.approx(0.0, abs=0.05)
    assert long.calls[-1] == (0.0, True)


def test_independent_private_tick_skips_hidden_and_recordingless(controller):
    visible = FakeViewport(10, 10)
    hidden = FakeViewport(10, 10, hidden=True)
    no_recording = FakeViewport(10, 10)
    no_recording.recording = None
    for viewport in (visible, hidden, no_recording):
        controller.add_viewport(viewport)
        viewport.calls.clear()
    controller.set_synced(False)
    for viewport in (visible, hidden, no_recording):
        viewport.calls.clear()
    controller._on_private_tick(visible, 0.3)
    controller._on_private_tick(hidden, 0.3)
    controller._on_private_tick(no_recording, 0.3)
    assert visible.calls == [(0.3, False)]
    assert hidden.calls == []
    assert no_recording.calls == []


def test_toggling_sync_skips_hidden_viewports(controller):
    long, short, still, hidden = _viewports(controller)
    controller.set_synced(False)
    assert hidden.calls == []
    assert long.calls == [(0.0, False)]
    assert short.calls == [(0.0, False)]
