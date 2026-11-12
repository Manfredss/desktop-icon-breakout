# Third-party notices / 第三方说明

The game code is MIT licensed. Platform and application icons remain the property
of their respective owners; they are read locally at runtime. We do not ship an
application-logo collection. Software marks visible in demonstrations identify
the installed applications and imply no endorsement.

游戏源码使用 MIT 许可证。系统及软件图标归各权利人所有，运行时从本机读取；
发行包不附送软件商标图库。演示中的软件标志仅用于说明实际图标来源，不代表合作或背书。

## Runtime libraries

- **Qt for Python / PySide6 / Shiboken6 6.8.3**, The Qt Company and contributors.
  Distributed under the LGPL v3 option. Qt shared libraries remain separate in
  the portable bundle and may be replaced with compatible modified versions.
  The license texts from the installed distribution are included in `licenses/`.
  [Source and release archives](https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.8.3-src/)
  · [Qt 6.8.3 source](https://download.qt.io/official_releases/qt/6.8/6.8.3/single/)
- **Python**, Python Software Foundation license; license included with the bundle.
  [Source](https://www.python.org/downloads/source/)
- **PyInstaller**, GPL with the bootloader exception permitting distribution of
  bundled applications under their own license.
  [License](https://pyinstaller.org/en/stable/license.html)

Pillow and pytest are development tools, not required by the game runtime.

## Inspiration

[Desktop Icon Billiards](https://github.com/liuxiaogang-com/desktop-icon-billiards)
by liuxiaogang-com inspired the idea of turning desktop icons into a game. This
project uses independently written code and a different game and window model.

创意向「桌面图标台球」致敬。这里的挡板、小球、物理引擎和跨平台界面均为独立实现。
