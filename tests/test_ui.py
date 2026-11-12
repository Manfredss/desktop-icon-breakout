"""Qt input regressions, without reading personal desktop files or settings."""
from __future__ import annotations

import os
import sys

import pytest

# Native Windows/macOS icon providers must keep their native platform plugin.
# Linux CI without a display can still verify input behavior; native-icon cases
# are skipped if the current machine has no installed application artwork.
if sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

from desktop_breakout.engine import PlayState
from desktop_breakout.native import NativeAssets, load_assets
from desktop_breakout import ui


@pytest.fixture(scope="session")
def qt_app():
    application = QApplication.instance() or QApplication([])
    yield application


@pytest.fixture(scope="session")
def native_demo_assets(qt_app):
    # Demo discovery excludes personal desktop files, names, and wallpaper.
    assets = load_assets(demo=True)
    if not assets.icons:
        pytest.skip("No installed native application icons on this test machine")
    assert all(not icon.pixmap.isNull() for icon in assets.icons)
    assert assets.desktop_count == 0
    assert assets.wallpaper is None
    return assets


@pytest.fixture
def make_window(qt_app, monkeypatch, tmp_path):
    monkeypatch.setenv("DESKTOP_BREAKOUT_CONFIG_DIR", str(tmp_path / "settings"))
    windows = []

    def create(assets):
        monkeypatch.setattr(ui, "load_assets", lambda demo=False: assets)
        window = ui.ArcadeWindow(demo=True, lang="en")
        windows.append(window)
        qt_app.processEvents()
        window.timer.stop()
        assert not window.loading
        return window

    yield create
    for window in windows:
        window.close()
    qt_app.processEvents()
    assert not (tmp_path / "settings").exists(), "Demo tests wrote application settings"


def press(app, window, key, repeat=False):
    app.sendEvent(window, QKeyEvent(QEvent.Type.KeyPress, key,
                                  Qt.KeyboardModifier.NoModifier, "", repeat))


def test_pause_auto_repeat_is_ignored(qt_app, make_window, native_demo_assets):
    window = make_window(native_demo_assets)
    window.start_game(False)
    press(qt_app, window, Qt.Key.Key_Space)
    assert window.game.state == PlayState.PLAYING
    press(qt_app, window, Qt.Key.Key_P, repeat=True)
    assert window.game.state == PlayState.PLAYING
    press(qt_app, window, Qt.Key.Key_P)
    assert window.game.state == PlayState.PAUSED
    press(qt_app, window, Qt.Key.Key_P, repeat=True)
    assert window.game.state == PlayState.PAUSED
    press(qt_app, window, Qt.Key.Key_P)
    assert window.game.state == PlayState.PLAYING


def test_mouse_press_uses_fresh_event_position(qt_app, make_window):
    window = make_window(NativeAssets())
    # Reproduce a scaled/letterboxed window whose old hover point is stale.
    window._view_scale = .75
    window._view_offset = QPointF(17, 23)
    window._mouse = QPointF(-100, -100)
    clicked = []
    window._buttons = [(QRectF(100, 200, 300, 70), lambda: clicked.append(True))]
    logical = QPointF(200, 230)
    local = QPointF(logical.x() * .75 + 17, logical.y() * .75 + 23)
    event = QMouseEvent(QEvent.Type.MouseButtonPress, local, local,
                        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                        Qt.KeyboardModifier.NoModifier)
    qt_app.sendEvent(window, event)
    assert clicked == [True]
    assert window._mouse == logical


def test_losing_focus_pauses_and_clears_held_movement(qt_app, make_window, native_demo_assets):
    window = make_window(native_demo_assets)
    window.start_game(False)
    press(qt_app, window, Qt.Key.Key_Space)
    press(qt_app, window, Qt.Key.Key_Left)
    assert window.left_held
    qt_app.sendEvent(window, QEvent(QEvent.Type.WindowDeactivate))
    assert window.game.state == PlayState.PAUSED
    assert not window.left_held and not window.right_held
    elapsed = window.game.elapsed
    window.game.update(.1)
    assert window.game.elapsed == elapsed
    # Repeated deactivation must not accidentally resume the game.
    qt_app.sendEvent(window, QEvent(QEvent.Type.WindowDeactivate))
    assert window.game.state == PlayState.PAUSED


def test_no_native_icons_prevents_start(qt_app, make_window):
    window = make_window(NativeAssets(notes=["No native icons available"]))
    assert not window._has_icons()
    window.start_game(False)
    assert window.home
    press(qt_app, window, Qt.Key.Key_Space)
    assert window.home
    assert window.game.bricks == []
    # The empty-state UI is still renderable and offers no enabled play action.
    assert not window.render_to_image(960, 600).isNull()


def test_language_switch_updates_engine_and_all_states_render(make_window, native_demo_assets):
    window = make_window(native_demo_assets)
    window.start_game(False)
    for language in ("zh", "en"):
        window.set_language(language)
        assert window.game.language == language
        for state in PlayState:
            window.game.state = state
            image = window.render_to_image(960, 600)
            assert image.width() == 960 and image.height() == 600
            assert not image.isNull()
