import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from echo_viewer.window import ViewerWindow  # noqa: E402
from echo_viewer.playback import PlaybackController  # noqa: E402
from echo_viewer.session import scan_session  # noqa: E402

GRID_POSITIONS = ((0, 0), (0, 1), (1, 0), (1, 1))


def _app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def make_window():
    app = _app()
    windows = []

    def factory():
        window = ViewerWindow()
        windows.append(window)
        return window

    yield factory
    # Closing here runs even when an assertion in the test fails.
    for window in windows:
        window.close()
    app.processEvents()


def _write_session(tmp_path, write_dicom, n):
    for i in range(n):
        write_dicom(f"rec{i}.dcm", frames=3, instance=i + 1, color=True)
    return scan_session(tmp_path)


def _click(window, index):
    window.thumbnailList.itemClicked.emit(window.thumbnailList.item(index))


def _position(window, viewport):
    return window.gridLayout.getItemPosition(window.gridLayout.indexOf(viewport))[:2]


def _visible(window):
    return [v for v in window.viewports if not v.isHidden()]


def test_initial_layout_is_2x2_with_all_four_visible(make_window):
    w = make_window()
    assert w.layoutCombo.currentIndex() == 1
    assert w.gridLayout.count() == 4
    assert _visible(w) == w.viewports
    for viewport, expected in zip(w.viewports, GRID_POSITIONS):
        assert _position(w, viewport) == expected


def test_switch_to_1x1_shows_only_active_and_back_restores_four(make_window):
    w = make_window()
    w.layoutCombo.setCurrentIndex(0)
    assert w.gridLayout.count() == 1
    assert _visible(w) == [w.active_viewport]
    assert _position(w, w.active_viewport) == (0, 0)

    w.layoutCombo.setCurrentIndex(1)
    assert w.gridLayout.count() == 4
    assert _visible(w) == w.viewports
    for viewport, expected in zip(w.viewports, GRID_POSITIONS):
        assert _position(w, viewport) == expected


def test_in_1x1_activating_another_viewport_shows_that_one(make_window):
    w = make_window()
    w.layoutCombo.setCurrentIndex(0)
    target = w.viewports[2]
    target.activated.emit(target)
    assert w.active_viewport is target
    assert _visible(w) == [target]
    assert _position(w, target) == (0, 0)
    assert w.gridLayout.count() == 1


def test_in_1x1_loading_a_tile_shows_the_loaded_one(tmp_path, write_dicom, make_window):
    session = _write_session(tmp_path, write_dicom, 3)
    w = make_window()
    w.load_session(session)
    w.layoutCombo.setCurrentIndex(0)
    _click(w, 0)  # active empty tile takes it
    _click(w, 1)  # active occupied -> first empty tile (v[1]) becomes active
    assert w.viewports[1].recording == session.recordings[1]
    assert _visible(w) == [w.viewports[1]]


def test_play_button_toggles_text_and_controller_state(make_window):
    w = make_window()
    assert w.playButton.text() == "Play"
    w.playButton.click()
    assert w.controller.is_playing
    assert w.playButton.text() == "Pause"
    w.playButton.click()
    assert not w.controller.is_playing
    assert w.playButton.text() == "Play"


def test_stop_restarts_playback(tmp_path, write_dicom, make_window):
    session = _write_session(tmp_path, write_dicom, 2)
    w = make_window()
    w.load_session(session)
    _click(w, 0)
    w.playButton.click()
    # Move the clock forward by setting its position rather than sleeping.
    w.controller.shared_clock.set_position_s(0.5)
    assert w.controller.shared_clock.position_s >= 0.5
    w.stopButton.click()
    assert not w.controller.is_playing
    assert w.playButton.text() == "Play"
    assert w.controller.shared_clock.position_s == 0.0


def test_sync_checkbox_drives_controller_and_status(make_window):
    w = make_window()
    assert w.controller.synced
    w.syncCheckBox.setChecked(False)
    assert not w.controller.synced
    assert w.statusbar.currentMessage() == "Independent"
    w.syncCheckBox.setChecked(True)
    assert w.controller.synced
    assert w.statusbar.currentMessage() == "Synced"


def test_loop_checkbox_drives_controller(make_window):
    w = make_window()
    assert w.controller.loop_enabled
    w.loopCheckBox.setChecked(False)
    assert not w.controller.loop_enabled
    w.loopCheckBox.setChecked(True)
    assert w.controller.loop_enabled


def test_close_stops_playback_timers(tmp_path, write_dicom, make_window):
    session = _write_session(tmp_path, write_dicom, 2)
    w = make_window()
    w.load_session(session)
    _click(w, 0)
    w.playButton.click()
    assert w.controller.shared_clock.is_playing
    w.close()
    assert not w.controller.is_playing
    assert not w.controller.shared_clock.is_playing


def test_scrub_requested_reaches_controller_scrub_once(make_window, monkeypatch):
    calls = []
    original = PlaybackController.scrub

    def spy(self, viewport, frame_index):
        calls.append((viewport, frame_index))
        return original(self, viewport, frame_index)

    # Patch before constructing the window: add_viewport binds self.scrub at wiring time.
    monkeypatch.setattr(PlaybackController, "scrub", spy)
    w = make_window()
    viewport = w.viewports[1]
    viewport.scrub_requested.emit(viewport, 2)
    assert calls == [(viewport, 2)]
