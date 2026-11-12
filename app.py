"""Desktop entry point. No server, network connection, or administrator required."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Desktop Icon Breakout / 桌面图标打砖块")
    parser.add_argument("--demo", action="store_true", help="Only public-safe installed app icons; no wallpaper or personal settings")
    parser.add_argument("--lang", choices=("en", "zh"), help="Interface language")
    parser.add_argument("--smoke-test", type=Path, metavar="PNG", help="Render the real application offscreen and exit")
    args = parser.parse_args()
    if args.smoke_test and sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication
    from desktop_breakout.ui import ArcadeWindow

    QCoreApplication.setOrganizationName("DesktopIconBreakout")
    QCoreApplication.setApplicationName("DesktopIconBreakout")
    app = QApplication(sys.argv[:1])
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    icon = root / "assets" / "app.png"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    window = ArcadeWindow(demo=args.demo or bool(args.smoke_test), lang=args.lang)
    if args.smoke_test:
        for _ in range(50):
            app.processEvents()
            if not getattr(window, "loading", False):
                break
        window.timer.stop()
        args.smoke_test.parent.mkdir(parents=True, exist_ok=True)
        image = window.render_to_image(1280, 800)
        if not image.save(str(args.smoke_test)):
            raise RuntimeError("Could not save smoke test image")
        metadata = {"platform": window.assets.platform_label, "icons": len(window.assets.icons),
                    "desktop": window.assets.desktop_count, "applications": window.assets.application_count,
                    "system": window.assets.system_count, "width": image.width(), "height": image.height()}
        args.smoke_test.with_suffix(".json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        window.close()
        return 0 if metadata["icons"] > 0 else 2
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
