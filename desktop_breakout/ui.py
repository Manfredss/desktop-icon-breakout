"""The same native Qt paint path powers the playable UI and exported previews."""
from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QEvent, QLocale, QPointF, QRectF, QStandardPaths, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget

from .audio import ArcadeAudio
from .engine import GameEngine, PlayState, build_level
from .native import load_assets


class ArcadeWindow(QWidget):
    COLORS = ("#a796ff", "#5edfcc", "#ffbe78", "#78adff", "#fa92b3", "#d8eaa0")

    def __init__(self, demo: bool = False, lang: str | None = None):
        super().__init__()
        self.demo = demo
        self.lang = lang or ("zh" if QLocale.system().language() == QLocale.Language.Chinese else "en")
        self.lang = "zh" if self.lang.startswith("zh") else "en"
        self.game = GameEngine(seed=123 if demo else None)
        self.game.language = self.lang
        self.assets = None
        self.loading = True
        self.asset_error = ""
        self.home = True
        self.help_open = False
        self.unique = False
        self.left_held = self.right_held = False
        self._mouse = QPointF(-100, -100)
        self._view_scale = 1.0
        self._view_offset = QPointF()
        self._buttons: list[tuple[QRectF, Callable]] = []
        self._fonts: dict[tuple, QFont] = {}
        self._normal_geometry = None
        self._started = self._previous = time.perf_counter()
        self.animation_time = 0.0
        self._prior_state = self.game.state
        self._settings = self._read_settings()
        try:
            self.best = max(0, int(self._settings.get("best_score", 0)))
        except (TypeError, ValueError, OverflowError):
            self.best = 0
        self.sound_enabled = bool(self._settings.get("sound", True)) and not demo
        self.audio = ArcadeAudio() if not demo else None
        self.game.sound = self._play_sound
        self.setWindowTitle("Desktop Breakout · 桌面打砖块")
        self.setMinimumSize(860, 580)
        screen = QApplication.primaryScreen()
        area = screen.availableGeometry() if screen else None
        self.resize(min(1280, int(area.width() * .92)) if area else 1280,
                    min(820, int(area.height() * .92)) if area else 820)
        if area:
            self.move(area.center() - self.rect().center())
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._frame)
        self.timer.start()
        QTimer.singleShot(0, self._load_assets)

    def tr2(self, zh: str, en: str) -> str:
        return zh if self.lang == "zh" else en

    def set_language(self, lang: str) -> None:
        self.lang = "zh" if lang.startswith("zh") else "en"
        self.game.language = self.lang
        self.update()

    def _settings_path(self) -> Path:
        directory = os.environ.get("DESKTOP_BREAKOUT_CONFIG_DIR")
        if not directory:
            directory = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
        return Path(directory) / "settings.json"

    def _read_settings(self) -> dict:
        if self.demo:
            return {}
        try:
            result = json.loads(self._settings_path().read_text(encoding="utf-8"))
            return result if isinstance(result, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_settings(self) -> None:
        if self.demo:
            return
        try:
            path = self._settings_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"best_score": self.best, "sound": self.sound_enabled}, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _save_best(self) -> None:
        if self.game.score > self.best:
            self.best = self.game.score
            self._save_settings()

    def _load_assets(self) -> None:
        try:
            self.assets = load_assets(demo=self.demo)
        except Exception as error:
            # Resource failures are recoverable; never substitute imaginary icons.
            self.asset_error = type(error).__name__
        self.loading = False
        self.update()

    def _play_sound(self, name: str) -> None:
        if self.sound_enabled and self.audio:
            self.audio.play(name)

    def _toggle_sound(self) -> None:
        if self.audio and self.audio.available:
            self.sound_enabled = not self.sound_enabled
            self._save_settings()

    def _has_icons(self) -> bool:
        return not self.loading and bool(self.assets and self.assets.icons)

    def start_game(self, fullscreen: bool = False) -> None:
        if not self._has_icons():
            return
        self.home = False
        self.help_open = False
        self._set_fullscreen(fullscreen)
        self._restart()
        self.setFocus()
        self.update()

    def _restart(self) -> None:
        if not self._has_icons():
            return
        self._save_best()
        self.game.start(build_level(len(self.assets.icons), 1, self.unique))
        self.left_held = self.right_held = False

    def _next_level(self) -> None:
        self.game.start(build_level(len(self.assets.icons), self.game.level + 1, self.unique),
                        self.game.level + 1, False)

    def _go_home(self) -> None:
        self._save_best()
        self.home = True
        self.help_open = False
        self.left_held = self.right_held = False
        self._set_fullscreen(False)

    def _set_fullscreen(self, fullscreen: bool) -> None:
        if fullscreen == self.isFullScreen():
            return
        if fullscreen:
            self._normal_geometry = self.geometry()
            current = self.screen() or QApplication.primaryScreen()
            if current:
                self.setGeometry(current.geometry())
            self.showFullScreen()
        else:
            self.showNormal()
            if self._normal_geometry is not None:
                self.setGeometry(self._normal_geometry)

    def _show_help(self) -> None:
        if self.game.state == PlayState.PLAYING:
            self.game.toggle_pause()
        self.help_open = not self.help_open

    def _toggle_unique(self) -> None:
        self.unique = not self.unique

    def _frame(self) -> None:
        now = time.perf_counter()
        dt = min(max(0.0, now - self._previous), .05)
        self._previous = now
        self.animation_time = now - self._started
        if not self.home and not self.help_open:
            if self.game.state in {PlayState.READY, PlayState.PLAYING}:
                self.game.move_paddle((int(self.right_held) - int(self.left_held)) * 900 * dt)
            self.game.update(dt)
            if self.game.state != self._prior_state:
                if self.game.state in {PlayState.WON, PlayState.GAME_OVER}:
                    self._save_best()
                self._prior_state = self.game.state
        self.update()

    def event(self, event):
        if event.type() == QEvent.Type.WindowDeactivate:
            self.left_held = self.right_held = False
            if not self.home and self.game.state == PlayState.PLAYING:
                self.game.toggle_pause()
        return super().event(event)

    def closeEvent(self, event):
        self.timer.stop()
        self._save_best()
        self._save_settings()
        if self.audio:
            self.audio.close()
        event.accept()

    def _logical_position(self, point: QPointF) -> QPointF:
        return QPointF((point.x() - self._view_offset.x()) / self._view_scale,
                       (point.y() - self._view_offset.y()) / self._view_scale)

    def mouseMoveEvent(self, event):
        self._mouse = self._logical_position(event.position())
        if not self.home and not self.help_open and self.game.state in {PlayState.READY, PlayState.PLAYING}:
            self.game.set_paddle(self._mouse.x())
        self.setCursor(Qt.CursorShape.PointingHandCursor if any(r.contains(self._mouse) for r, _ in self._buttons)
                       else Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._mouse = self._logical_position(event.position())
        self.setFocus()
        for bounds, callback in tuple(self._buttons):
            if bounds.contains(self._mouse):
                callback()
                self.update()
                return
        if not self.home and not self.help_open and self.game.state == PlayState.READY:
            self.game.launch()

    def leaveEvent(self, event):
        self._mouse = QPointF(-100, -100)

    def keyPressEvent(self, event):
        if event.isAutoRepeat():
            return
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.close()
        elif key == Qt.Key.Key_F11:
            self._set_fullscreen(not self.isFullScreen())
        elif key == Qt.Key.Key_M:
            self._toggle_sound()
        elif key == Qt.Key.Key_H:
            self._show_help()
        elif self.help_open:
            if key in {Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space}:
                self.help_open = False
        elif self.home:
            if key in {Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space}:
                self.start_game(False)
        else:
            if key in {Qt.Key.Key_Left, Qt.Key.Key_A}:
                self.left_held = True
            elif key in {Qt.Key.Key_Right, Qt.Key.Key_D}:
                self.right_held = True
            elif key == Qt.Key.Key_P:
                self.game.toggle_pause()
            elif key == Qt.Key.Key_R:
                self._restart()
            elif key in {Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space}:
                if self.game.state == PlayState.READY:
                    self.game.launch()
                elif self.game.state == PlayState.PAUSED:
                    self.game.toggle_pause()
                elif self.game.state == PlayState.WON:
                    self._next_level()
                elif self.game.state == PlayState.GAME_OVER:
                    self._restart()
        self.update()

    def keyReleaseEvent(self, event):
        if event.isAutoRepeat():
            return
        if event.key() in {Qt.Key.Key_Left, Qt.Key.Key_A}:
            self.left_held = False
        elif event.key() in {Qt.Key.Key_Right, Qt.Key.Key_D}:
            self.right_held = False

    def paintEvent(self, event):
        painter = QPainter(self)
        self._draw(painter, self.width(), self.height(), True)
        painter.end()

    def render_to_image(self, width: int = 1280, height: int = 800) -> QImage:
        image = QImage(width, height, QImage.Format.Format_ARGB32)
        image.fill(QColor("#090d17"))
        painter = QPainter(image)
        self._draw(painter, width, height, False)
        painter.end()
        return image

    def _draw(self, p: QPainter, width: int, height: int, interactive: bool) -> None:
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(QRectF(0, 0, width, height), self._color("#080b13"))
        scale = min(width / 1440, height / 900)
        offset = QPointF((width - 1440 * scale) / 2, (height - 900 * scale) / 2)
        if interactive:
            self._view_scale, self._view_offset = scale, offset
        p.save()
        p.translate(offset)
        p.scale(scale, scale)
        p.setClipRect(QRectF(0, 0, 1440, 900))
        self._buttons.clear()
        self._background(p)
        if self.home:
            self._draw_home(p)
        else:
            self._draw_game(p)
        if self.help_open:
            self._draw_help(p)
        p.restore()

    @staticmethod
    def _color(hex_color: str, opacity: float = 1) -> QColor:
        color = QColor(hex_color)
        color.setAlphaF(max(0, min(1, opacity)))
        return color

    def _font(self, size: float, bold: bool = False) -> QFont:
        key = (size, bold)
        if key not in self._fonts:
            font = QFont()
            font.setFamilies(["Segoe UI", "Microsoft YaHei UI", "PingFang SC", "Noto Sans CJK SC", "Noto Sans", "sans-serif"])
            font.setPixelSize(round(size))
            font.setWeight(QFont.Weight.Bold if bold else QFont.Weight.Normal)
            self._fonts[key] = font
        return self._fonts[key]

    def _text(self, p, text, x, y, size=16, color="#a6b4cd", bold=False, width=None, center=False):
        font = self._font(size, bold)
        p.setFont(font)
        p.setPen(self._color(color))
        metrics = QFontMetricsF(font)
        value = str(text)
        if width:
            value = metrics.elidedText(value, Qt.TextElideMode.ElideRight, width)
        text_width = metrics.horizontalAdvance(value)
        p.drawText(QPointF(x - text_width / 2 if center else x, y + metrics.ascent()), value)

    def _rounded(self, p, rect, fill, border=None, radius=10, opacity=1, line_width=1):
        p.setBrush(self._color(fill, opacity))
        p.setPen(QPen(self._color(border), line_width) if border else Qt.PenStyle.NoPen)
        p.drawRoundedRect(rect, radius, radius)

    def _line(self, p, x1, y1, x2, y2, color="#28324b", width=1, opacity=1):
        p.setPen(QPen(self._color(color, opacity), width))
        p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    def _button(self, p, rect, title, callback, primary=False, disabled=False, size=None):
        hovered = rect.contains(self._mouse) and not disabled
        color = ("#bcabff" if hovered else "#a58af8") if primary else ("#29344d" if hovered else "#172237")
        self._rounded(p, rect, color, None if primary else "#344058", 12 if primary else 9, .4 if disabled else 1)
        size = size or (20 if primary else 15)
        self._text(p, title, rect.center().x(), rect.center().y() - size * .63, size,
                   "#17142c" if primary else "#c0cbe0", primary, rect.width() - 18, True)
        if not disabled:
            self._buttons.append((rect, callback))

    def _pill(self, p, rect, title, color="#a997ff"):
        self._rounded(p, rect, color, None, rect.height() / 2, .10)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(self._color(color, .28), 1))
        p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        self._text(p, title, rect.center().x(), rect.y() + 6, 12, color, width=rect.width() - 14, center=True)

    def _brand(self, p, x, y, compact=False):
        for i in range(4):
            self._rounded(p, QRectF(x + i % 2 * 13, y + i // 2 * 13, 9, 9),
                          "#5edfcc" if i == 3 else "#ab95ff", radius=2, opacity=.5 if i == 1 else 1)
        self._text(p, self.tr2("桌面打砖块", "DESKTOP BREAKOUT"), x + 38, y - 2,
                   20 if self.lang == "zh" else 17, "#e2e6f5", True)
        if not compact and self.lang == "zh":
            self._text(p, "DESKTOP BREAKOUT", x + 168, y + 4, 10, "#6d7e9a")

    def _background(self, p):
        p.fillRect(QRectF(0, 0, 1440, 900), self._color("#101729"))
        wallpaper = self.assets.wallpaper if self.assets else None
        if wallpaper and not wallpaper.isNull() and not self.demo:
            p.save()
            p.setOpacity(.22 if self.home else .36)
            ratio = max(1440 / wallpaper.width(), 900 / wallpaper.height())
            p.drawPixmap(QRectF((1440 - wallpaper.width() * ratio) / 2, (900 - wallpaper.height() * ratio) / 2,
                               wallpaper.width() * ratio, wallpaper.height() * ratio), wallpaper, QRectF(wallpaper.rect()))
            p.restore()
        gradient = QLinearGradient(0, 0, 1440, 900)
        gradient.setColorAt(0, self._color("#152235", .40))
        gradient.setColorAt(.5, self._color("#12152a", .62))
        gradient.setColorAt(1, self._color("#080d17", .92))
        p.fillRect(QRectF(0, 0, 1440, 900), gradient)
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(46):
            p.setBrush(self._color("#c3cef3", .08 + .045 * math.sin(self.animation_time * .5 + i)))
            p.drawEllipse(QPointF((i * 113.7 + 35) % 1440, (i * 67.3 + 21) % 900), 1, 1)

    def _draw_home(self, p):
        self._brand(p, 64, 37)
        platform = self.assets.platform_label if self.assets else self.tr2("正在识别系统", "DETECTING YOUR SYSTEM")
        self._text(p, platform.upper(), 906, 42, 12, "#7e8da9", width=285)
        self._button(p, QRectF(1236, 31, 126, 36), "EN / 中文", lambda: self.set_language("en" if self.lang == "zh" else "zh"), size=13)
        self._line(p, 64, 94, 1376, 94)
        self._pill(p, QRectF(77, 146, 294, 31), self.tr2("正经软件，不务正业。", "SERIOUS SOFTWARE. SILLY PURPOSE."))
        if self.lang == "zh":
            self._text(p, "桌面图标", 70, 201, 76, "#f0f2ff", True)
            self._text(p, "集体下班。", 70, 292, 76, "#b5a2ff", True)
        else:
            self._text(p, "DESKTOP", 73, 202, 79, "#f0f2ff", True)
            self._text(p, "BREAKOUT.", 73, 290, 76, "#b5a2ff", True)
        self._text(p, self.tr2("让你的软件，体验一下被工作的感觉。", "Put your apps to work. As bricks."), 78, 405, 23, "#c2cce0", True)
        self._text(p, self.tr2("真实图标。熟悉的桌面。合理的物理报复。", "Real icons. Familiar desktop. Perfectly civil physics."), 78, 447, 18, "#8d9dbb", width=600)
        title = self.tr2("正在集合桌面图标…", "Rounding up the icons…") if self.loading else self.tr2("开始桌面游戏    ↗", "PLAY ON DESKTOP    ↗")
        self._button(p, QRectF(78, 509, 347, 63), title, lambda: self.start_game(True), True, not self._has_icons(), 19)
        self._button(p, QRectF(441, 509, 174, 63), self.tr2("窗口试玩", "Windowed"), lambda: self.start_game(False), disabled=not self._has_icons(), size=16)
        if self.loading:
            summary = self.tr2("读取本机图标，不打扰它们的文件。", "Reading local icons. Leaving their files alone.")
        elif self._has_icons():
            n = len(self.assets.icons)
            summary = self.tr2(f"{n} 个真实图标已就位，{self.assets.desktop_count} 个来自桌面。",
                               f"{n} real icons reporting for duty. {self.assets.desktop_count} from your desktop.")
        else:
            summary = self.tr2("未找到原生图标，请安装常用软件后重试。", "No native icons found. Install an app and try again.")
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._color("#5edfcc" if self._has_icons() else "#ffbc72"))
        p.drawEllipse(QPointF(83, 606), 3, 3)
        self._text(p, summary, 97, 595, 13, "#8c9db8", width=555)
        self._text(p, self.tr2("文件不会被删除。你的生产力可能会。", "No files will be harmed. Your productivity might be."), 78, 630, 14, "#72829e", width=540)
        self._preview(p)
        self._line(p, 78, 715, 1362, 715)
        self._stat(p, "PERSONAL BEST", f"{self.best:,}", 80, 749, "#eff2ff", 32)
        self._stat(p, "POWER UPS", self.tr2("加长 · 慢速 · 多球", "WIDE · SLOW · MULTIBALL"), 340, 749, "#a9b8d2", 21)
        self._button(p, QRectF(801, 754, 240, 44), self.tr2("图标模式：每个一次", "Mode: one of each") if self.unique else self.tr2("图标模式：街机砖墙", "Mode: arcade wall"), self._toggle_unique)
        self._button(p, QRectF(1055, 754, 153, 44), self._sound_label(), self._toggle_sound, disabled=not(self.audio and self.audio.available))
        self._button(p, QRectF(1223, 754, 137, 44), self.tr2("玩法说明", "How to play"), self._show_help)
        self._text(p, self.tr2("鼠标 / ← → 移动     SPACE 发球     P 暂停     F11 全屏     ESC 退出",
                               "MOUSE / ← → MOVE     SPACE LAUNCH     P PAUSE     F11 FULLSCREEN     ESC QUIT"), 79, 851, 12, "#647593")
        self._text(p, "NATIVE ICONS. UNNATURAL HABITS.", 1100, 852, 9, "#52627e", width=270)

    def _sound_label(self):
        if self.demo:
            return self.tr2("演示静音", "Demo muted")
        if not self.audio or not self.audio.available:
            return self.tr2("音效不可用", "Audio unavailable")
        return self.tr2("音效 开", "Sound ON") if self.sound_enabled else self.tr2("音效 关", "Sound OFF")

    def _preview(self, p):
        self._rounded(p, QRectF(716, 146, 648, 530), "#091120", "#2d3550", 24, .70)
        self._text(p, self.tr2("你的软件，也有脆弱的一面。", "Your apps have a breakable side."), 746, 176, 15, "#97a9c5")
        self._pill(p, QRectF(1250, 171, 82, 28), "LIVE", "#5edfcc")
        count = len(self.assets.icons) if self.assets else 0
        for row in range(4):
            for col in range(7):
                if (row, col) in {(3, 3), (2, 4)}:
                    continue
                bob = math.sin(self.animation_time * 1.2 + row * .4 + col * .15) * 2
                rect = QRectF(747 + col * 83, 234 + row * 73 + bob, 74, 59)
                if count:
                    self._tile(p, rect, row * 7 + col, row, False)
                else:
                    self._rounded(p, rect, "#1e2a40", "#2c3750", 9, .4)
        px = 1060 + math.sin(self.animation_time * .8) * 120
        self._line(p, px - 100, 587, px - 35, 509, "#ae9bff", 2, .2)
        self._line(p, px - 35, 509, px + 16, 551, "#ae9bff", 2, .6)
        self._ball(p, px + 16, 551, 8)
        self._paddle(p, px - 86, 620, 172, 13)
        self._text(p, "ICONS → BRICKS → REASONABLE EXCUSE", 746, 648, 10, "#5f708e")

    def _draw_game(self, p):
        self._rounded(p, QRectF(24, 20, 1392, 77), "#0b1324", "#2d3951", 16, .92)
        self._brand(p, 45, 43, True)
        self._stat(p, "SCORE", f"{self.game.score:06d}", 347, 29, "#f4f5ff", 25)
        self._stat(p, "BEST", f"{max(self.best, self.game.score):06d}", 520, 29, "#94a4c0", 25)
        self._stat(p, "LEVEL", f"{self.game.level:02d}", 700, 29, "#bcadff", 25)
        self._stat(p, "LIVES", "●" * max(0, self.game.lives) + "○" * max(0, 3 - self.game.lives), 820, 29, "#fa9bb6", 22)
        self._button(p, QRectF(975, 38, 96, 41), self.tr2("音效", "Audio"), self._toggle_sound, disabled=not(self.audio and self.audio.available))
        self._button(p, QRectF(1084, 38, 91, 41), self.tr2("继续", "Resume") if self.game.state == PlayState.PAUSED else self.tr2("暂停", "Pause"), self.game.toggle_pause)
        self._button(p, QRectF(1188, 38, 91, 41), self.tr2("菜单", "Menu"), self._go_home)
        self._button(p, QRectF(1292, 38, 101, 41), self.tr2("退出 ↗", "Quit ↗"), self.close)
        self._line(p, 25, 124, 25, 846, "#627aa6", 1, .25)
        self._line(p, 1415, 124, 1415, 846, "#627aa6", 1, .25)
        self._text(p, "YOUR APPS. THEIR PROBLEM.", 110, 130, 11, "#7388aa")
        remaining = sum(b.alive for b in self.game.bricks)
        self._text(p, f"{remaining:02d} / {len(self.game.bricks):02d} REMAINING", 1150, 130, 11, "#7388aa")
        for brick in self.game.bricks:
            if brick.alive:
                self._tile(p, QRectF(brick.x, brick.y, brick.width, brick.height), brick.icon_index,
                           brick.color_index, True, brick.hit_points)
        p.setPen(Qt.PenStyle.NoPen)
        for particle in self.game.particles:
            opacity = max(0, min(1, particle.life / max(.001, particle.max_life)))
            size = 2 + opacity * 4
            p.setBrush(self._color(self.COLORS[particle.color_index % len(self.COLORS)], opacity))
            p.drawRect(QRectF(particle.x, particle.y, size, size))
        for pickup in self.game.pickups:
            color = "#5edfcc" if pickup.kind == "wide" else "#78adff" if pickup.kind == "slow" else "#ffbe78"
            self._rounded(p, QRectF(pickup.x - 20, pickup.y - 14, 40, 28), color, None, 8, .18)
            self._text(p, "↔" if pickup.kind == "wide" else "S" if pickup.kind == "slow" else "×3", pickup.x, pickup.y - 12, 17, color, True, center=True)
        for ball in self.game.balls:
            p.setPen(Qt.PenStyle.NoPen)
            for i, point in enumerate(ball.trail):
                fraction = 1 - i / max(1, len(ball.trail))
                p.setBrush(self._color("#b7acff", fraction * .22))
                p.drawEllipse(QPointF(point[0], point[1]), ball.radius * fraction * .8, ball.radius * fraction * .8)
            self._ball(p, ball.x, ball.y, ball.radius)
        self._paddle(p, self.game.paddle_x - self.game.paddle_width / 2, self.game.paddle_y, self.game.paddle_width, 15)
        self._line(p, 25, 855, 1415, 855, "#78659d", 1, .3)
        self._text(p, self.tr2("鼠标 / ← → 移动    SPACE 发球    P 暂停    R 重开    ESC 退出",
                               "MOUSE / ← → MOVE    SPACE LAUNCH    P PAUSE    R RESTART    ESC QUIT"), 42, 873, 12, "#7184a1")
        self._text(p, self.tr2("文件没事。它们只是戏很多。", "Your files are fine. They are just being dramatic."), 1030, 873, 11, "#7184a1", width=355)
        if self.game.combo > 1:
            self._text(p, f"×{self.game.combo}", 60, 718, 40, "#bbaaed", True)
            self._text(p, "COMBO", 62, 769, 11, "#8d7bb4")
        effect = self.game.active_effect
        if effect:
            self._pill(p, QRectF(1125, 779, 240, 31), self._engine_message(effect), "#5edfcc")
        if self.game.notice_time > 0 and self.game.state == PlayState.PLAYING:
            self._text(p, self._engine_message(self.game.notice), 720, 696, 20, "#d1c7ff", True, width=650, center=True)
        if self.game.state == PlayState.READY:
            self._draw_ready(p)
        elif self.game.state == PlayState.PAUSED:
            self._draw_pause(p)
        elif self.game.state in {PlayState.WON, PlayState.GAME_OVER}:
            self._draw_result(p)

    def _engine_message(self, text):
        if self.lang == "zh":
            return text
        replacements = {"加宽挡板": "Wide paddle", "加宽": "Wide", "慢速时间": "Slow motion", "慢速": "Slow",
                        "多球齐发!": "Multiball!", "球齐发": "balls", "连击!": "combo!", "秒": "s",
                        "全部击破 · 漂亮!": "All cleared. Nice work!", "点击鼠标或按空格发球": "Click or SPACE to launch"}
        for source, target in replacements.items():
            text = text.replace(source, target)
        return text

    def _draw_ready(self, p):
        self._rounded(p, QRectF(470, 553, 500, 148), "#111d32", "#4c466c", 20, .96)
        title = self.tr2("准备好，打破日常。", "Ready to break the routine?") if self.game.lives == 3 else self.tr2("稳住，还有机会。", "Another ball. Another chance.")
        self._text(p, title, 720, 581, 27 if self.lang == "zh" else 25, "#f0f2ff", True, width=465, center=True)
        self._text(p, self.tr2("单击画面 / 按空格发球", "CLICK / SPACE TO LAUNCH"), 720, 630, 17, "#baa9ff", center=True)
        self._text(p, self.tr2("挡板边缘可以改变反弹方向", "The paddle edge changes the rebound angle."), 720, 667, 12, "#7f91af", center=True)

    def _modal(self, p, rect):
        self._buttons.clear()
        p.fillRect(QRectF(0, 0, 1440, 900), self._color("#030912", .77))
        self._rounded(p, rect, "#111c30", "#414262", 23)

    def _draw_pause(self, p):
        self._modal(p, QRectF(450, 288, 540, 350))
        self._text(p, "TAKE A BREATHER", 720, 321, 12, "#a793f0", center=True)
        self._text(p, self.tr2("快乐也需要中场休息", "A very productive pause."), 720, 361, 29, "#f0f2ff", True, width=490, center=True)
        self._text(p, self.tr2("切换窗口时，游戏会自动暂停。", "Switching windows pauses the game automatically."), 720, 416, 15, "#93a3bd", width=490, center=True)
        self._button(p, QRectF(505, 468, 430, 58), self.tr2("继续游戏    SPACE / P", "RESUME    SPACE / P"), self.game.toggle_pause, True)
        self._button(p, QRectF(505, 545, 206, 44), self.tr2("重新开始", "Restart"), self._restart)
        self._button(p, QRectF(729, 545, 206, 44), self.tr2("返回菜单", "Main menu"), self._go_home)

    def _draw_result(self, p):
        won = self.game.state == PlayState.WON
        self._modal(p, QRectF(440, 254, 560, 434))
        self._text(p, "DESKTOP CLEARED" if won else "ONE MORE ROUND?", 720, 287, 13, "#5edfcc" if won else "#ffbe78", center=True)
        self._text(p, self.tr2("漂亮！桌面清场。", "Desktop: professionally cleared.") if won else self.tr2("下班前，再来一局。", "One more. For research."), 720, 326, 32 if self.lang == "zh" else 26, "#f2f3ff", True, width=510, center=True)
        self._text(p, f"{self.game.score:,}", 720, 390, 64, "#baabff", True, center=True)
        self._text(p, self.tr2(f"最高连击 ×{self.game.best_combo}  /  第 {self.game.level} 关", f"BEST COMBO ×{self.game.best_combo}  /  LEVEL {self.game.level:02d}"), 720, 480, 16, "#9cabc5", center=True)
        self._button(p, QRectF(500, 532, 440, 61), self.tr2("下一关    →", "NEXT LEVEL    →") if won else self.tr2("再玩一次    ↻", "PLAY AGAIN    ↻"), self._next_level if won else self._restart, True)
        self._button(p, QRectF(500, 610, 440, 45), self.tr2("返回菜单", "Main menu"), self._go_home)

    def _draw_help(self, p):
        self._modal(p, QRectF(380, 159, 680, 580))
        self._text(p, "HOW TO PLAY", 430, 199, 12, "#ae9af9")
        self._text(p, self.tr2("把桌面，玩出花。", "A crash course. Literally."), 430, 232, 34, "#f2f3ff", True, width=590)
        lines = [self.tr2("01  鼠标或 ← → / A D 移动挡板，接住小球。", "01  Move the paddle with your mouse or ← → / A D."),
                 self.tr2("02  点击或按空格发球，击中真实图标得分。", "02  Click or press SPACE. Hit real icons. Earn points."),
                 self.tr2("03  挡板边缘反弹更斜，连续击中触发连击。", "03  Paddle edges steer the ball. Chain hits for combos."),
                 self.tr2("04  接住道具：↔ 加长、S 慢速、×3 多球。", "04  Catch power-ups: ↔ wide, S slow, ×3 multiball."),
                 self.tr2("05  清空砖墙进入下一关；漏球会损失生命。", "05  Clear the wall to advance. Lose all balls, lose a life.")]
        for i, line in enumerate(lines):
            self._text(p, line, 430, 307 + i * 43, 17, "#a9b9d3", width=593)
        self._text(p, "P PAUSE  ·  R RESTART  ·  M AUDIO  ·  F11 FULLSCREEN  ·  ESC QUIT", 430, 554, 12, "#8194b2", width=595)
        self._text(p, self.tr2("所有图标来自本机。真实文件，拒绝参加比赛。", "Every icon comes from this computer. Actual files sit this one out."), 430, 591, 14, "#76aaa0", width=595)
        self._button(p, QRectF(430, 646, 580, 53), self.tr2("明白了，开玩", "GOT IT. LET'S BE UNPRODUCTIVE."), self._show_help, True, size=18)

    def _tile(self, p, rect, index, color_index, label, hp=1):
        if not self.assets or not self.assets.icons:
            return
        icon = self.assets.icons[index % len(self.assets.icons)]
        color = self.COLORS[color_index % len(self.COLORS)]
        self._rounded(p, rect, "#172138", radius=9, opacity=.94)
        self._rounded(p, rect, color, radius=9, opacity=.1)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(self._color(color, .8 if hp > 1 else .38), 2 if hp > 1 else 1))
        p.drawRoundedRect(rect, 9, 9)
        self._line(p, rect.x() + 17, rect.y() + 1, rect.right() - 17, rect.y() + 1, color, 2, .65)
        size = 32 if label else 35
        destination = QRectF(rect.center().x() - size / 2, rect.y() + (6 if label else (rect.height() - size) / 2), size, size)
        if not icon.pixmap.isNull():
            p.drawPixmap(destination, icon.pixmap, QRectF(icon.pixmap.rect()))
        if label:
            self._text(p, icon.name, rect.center().x(), rect.y() + 41, 10, "#bdc8dd", width=rect.width() - 10, center=True)
        if hp > 1:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self._color(color))
            p.drawEllipse(QPointF(rect.right() - 8, rect.y() + 8), 2, 2)

    def _paddle(self, p, x, y, width, height):
        self._rounded(p, QRectF(x - 9, y - 7, width + 18, height + 14), "#a18cff", radius=14, opacity=.09)
        gradient = QLinearGradient(x, y, x + width, y)
        gradient.setColorAt(0, self._color("#b397ff"))
        gradient.setColorAt(1, self._color("#7385ff"))
        p.setBrush(gradient)
        p.setPen(QPen(self._color("#ddd0ff", .85), 1))
        p.drawRoundedRect(QRectF(x, y, width, height), 7, 7)
        self._line(p, x + width / 2 - 11, y + 6, x + width / 2 + 11, y + 6, "#f0e8ff", 2, .7)

    def _ball(self, p, x, y, radius):
        p.setPen(Qt.PenStyle.NoPen)
        for multiplier, alpha in ((3, .06), (1.8, .16), (1, 1)):
            p.setBrush(self._color("#f5f1ff" if multiplier == 1 else "#b6a5ff", alpha))
            p.drawEllipse(QPointF(x, y), radius * multiplier, radius * multiplier)

    def _stat(self, p, title, value, x, y, color, size=32):
        self._text(p, title, x, y, 11, "#6f83a2")
        self._text(p, value, x - 1, y + 20, size, color, True)
