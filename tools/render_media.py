"""Export actual game frames using native installed-app artwork, not mockups.

Run on a real desktop OS. demo=True excludes personal desktop files and wallpaper.
The paddle is automated and the score must never be described as a human record.
"""
from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import sys

from PIL import Image
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desktop_breakout.engine import PlayState
from desktop_breakout.ui import ArcadeWindow


def frame_to_pillow(image):
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return Image.open(BytesIO(bytes(buffer.data()))).convert("RGB")


def main():
    app = QApplication(sys.argv[:1])
    app.setApplicationName("DesktopIconBreakoutMedia")
    window = ArcadeWindow(demo=True, lang="zh")
    app.processEvents()
    window.timer.stop()
    assert window.assets and window.assets.icons, "Native app artwork required"
    assert window.assets.desktop_count == 0 and window.assets.wallpaper is None
    out = ROOT / "docs/media"
    out.mkdir(parents=True, exist_ok=True)
    window.animation_time = 1.25
    window.render_to_image(1440, 900).save(str(out / "menu-zh.png"))
    window.set_language("en")
    window.render_to_image(1440, 900).save(str(out / "menu-en.png"))
    window.start_game(False)
    window.game.set_assist(True)
    window.game.launch()
    frames = []
    palette = None
    fps = 20
    for index in range(16 * fps):
        # The simulation uses the same sub-stepped collisions as interactive play.
        for _ in range(3):
            window.game.update(1 / (fps * 3))
        if window.game.state == PlayState.READY:
            window.game.launch()
        if window.game.state == PlayState.WON:
            window._next_level()
            window.game.launch()
        window.animation_time = index / fps
        if index == 8 * fps:
            window.render_to_image(1440, 900).save(str(out / "gameplay.png"))
        frame = frame_to_pillow(window.render_to_image(1024, 640))
        if palette is None:
            palette = frame.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
        frames.append(frame.quantize(palette=palette, dither=Image.Dither.NONE))
    frames[0].save(out / "gameplay.gif", save_all=True, append_images=frames[1:],
                   loop=0, duration=50, disposal=1, optimize=True)
    (out / "provenance.json").write_text(json.dumps({
        "renderer": "Actual PySide6/QPainter game renderer",
        "platform": window.assets.platform_label,
        "icons": [{"name": icon.name, "source": icon.source} for icon in window.assets.icons],
        "personal_desktop_icons": 0, "personal_wallpaper": False,
        "automated_paddle": True, "fps": fps, "seconds": len(frames) / fps,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    window.close()
    print(f"Exported {len(frames)} actual game frames with {len(window.assets.icons)} native icons.")


if __name__ == "__main__":
    main()
