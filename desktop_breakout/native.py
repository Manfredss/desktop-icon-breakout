"""Read local desktop artwork. No synthetic app logos, shell execution, or desktop edits.

QFileIconProvider delegates file/application artwork to the native platform. Linux
desktop entries use their installed icon theme. The public demo deliberately omits
personal desktop names and wallpaper, and only admits known application names.
"""
from __future__ import annotations

import configparser
import ctypes
import locale
import os
import platform
import re
import shutil
import struct
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlparse

from PySide6.QtCore import QFileInfo, QStandardPaths
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QFileIconProvider


@dataclass
class NativeIcon:
    name: str
    pixmap: QPixmap
    source: str = "desktop"


@dataclass
class NativeAssets:
    icons: list[NativeIcon] = field(default_factory=list)
    wallpaper: QPixmap | None = None
    platform_label: str = ""
    desktop_count: int = 0
    application_count: int = 0
    system_count: int = 0
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DesktopEntry:
    name: str
    icon: str


# This maps locally installed application names to safe public labels. It does not
# ship icons: each accepted name still needs artwork from that installed app.
_DEMO_NAMES = (
    "Visual Studio Code", "Google Chrome", "Microsoft Edge", "Mozilla Firefox",
    "Firefox", "Microsoft Visual Studio", "Visual Studio", "Windows Terminal",
    "Windows PowerShell", "PowerShell", "Command Prompt", "File Explorer",
    "Adobe Acrobat", "Adobe Photoshop", "Adobe Illustrator", "Adobe Premiere",
    "Docker Desktop", "OBS Studio", "VLC media player", "LibreOffice Writer",
    "LibreOffice Calc", "LibreOffice Impress", "LibreOffice", "Git Bash", "Git GUI",
    "Jupyter Notebook", "JupyterLab", "Anaconda Navigator", "Anaconda", "Notepad++",
    "Notepad", "Calculator", "Paint", "7-Zip", "WinRAR", "Steam", "Discord",
    "Spotify", "Blender", "Inkscape", "GIMP", "Krita", "Figma", "Safari",
    "Microsoft Word", "Microsoft Excel", "Microsoft PowerPoint", "Microsoft Outlook",
    "Microsoft OneNote", "Microsoft Teams", "Word", "Excel", "PowerPoint", "Outlook",
    "OneNote", "Teams", "Activity Monitor", "System Settings", "System Preferences",
    "QuickTime Player", "TextEdit", "Preview", "App Store", "Calendar", "Notes",
    "Photos", "Music", "Maps", "Mail", "Finder", "Terminal", "System Monitor",
    "GNOME Text Editor", "Konsole", "Files", "gedit", "Kate", "Python", "Git", "VLC",
    "计算器", "记事本", "画图", "终端", "文件资源管理器", "谷歌浏览器", "火狐浏览器",
)

_WINDOWS_EXE_NAMES = {
    "explorer": "File Explorer", "notepad": "Notepad", "mspaint": "Paint",
    "calc": "Calculator", "powershell": "PowerShell", "cmd": "Command Prompt",
}
_MAIN_APP_ORDER = (
    "Google Chrome", "Microsoft Edge", "Mozilla Firefox", "Firefox", "Visual Studio Code",
    "Blender", "Steam", "Microsoft Word", "Word", "Microsoft Excel", "Excel",
    "Microsoft PowerPoint", "PowerPoint", "Adobe Photoshop", "Adobe Acrobat",
    "OBS Studio", "VLC media player", "VLC", "Notepad++", "Notepad", "Calculator",
    "Paint", "File Explorer", "Windows Terminal", "Spotify", "Discord", "7-Zip",
    "WinRAR", "Microsoft Outlook", "Outlook", "OneNote", "Microsoft OneNote",
    "Microsoft Teams", "Teams", "Docker Desktop", "Figma", "Inkscape", "GIMP",
    "Krita", "LibreOffice", "PowerShell", "Windows PowerShell", "Command Prompt",
)


def _helper_shortcut(name: str) -> bool:
    """Distinguish a main application from its developer/shell launchers."""
    if name.strip().casefold() == "command prompt":
        return False  # The actual Windows application has this exact name.
    return bool(re.search(r"\b(?:prompt|console|shell|ise|manual|documentation)\b|release[ -]notes|command[ -]line|命令提示|开发人员命令", name, re.I))


def safe_demo_name(name: str) -> str | None:
    """A strict public allowlist, never a filename/path supplied by the desktop."""
    if any(character in name for character in ("/", "\\", "\n", "\r", ":")) or _helper_shortcut(name):
        return None
    normalized = re.sub(r"[®™]", "", name).strip()
    for known in _DEMO_NAMES:
        # Accept the app's name plus a version / packaging suffix, not a substring
        # such as 'Notes' inside 'Git Release Notes' or a user's renamed shortcut.
        suffix = r"(?:\s+(?:\([^\r\n]+\)|\d[\w. -]*|x64|x86|ARM64))*"
        if re.fullmatch(re.escape(known) + suffix, normalized, re.I):
            return known
    return None


def _application_priority(path: Path) -> tuple[int, str]:
    name = _WINDOWS_EXE_NAMES.get(path.stem.lower(), path.stem) if path.suffix.lower() == ".exe" else path.stem
    if _helper_shortcut(name):
        return 1000, name.casefold()
    canonical = safe_demo_name(name)
    rank = _MAIN_APP_ORDER.index(canonical) if canonical in _MAIN_APP_ORDER else 500
    return rank, name.casefold()


def _read_os_release() -> str:
    try:
        values = {}
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                values[key] = value.strip().strip('"')
        return values.get("PRETTY_NAME", "Linux")
    except (OSError, UnicodeError):
        return "Linux"


def platform_label() -> str:
    system = platform.system()
    if system == "Windows":
        # platform.release() has returned '10' on Windows 11 in older Python builds.
        build = int(platform.version().split(".")[-1]) if platform.version().split(".")[-1].isdigit() else 0
        return f"Windows {'11' if build >= 22000 else platform.release()} · {platform.machine()}"
    if system == "Darwin":
        return f"macOS {platform.mac_ver()[0]} · {platform.machine()}"
    return f"{_read_os_release()} · {platform.machine()}"


def parse_desktop_entry(path: Path, language: str | None = None) -> DesktopEntry | None:
    """Parse metadata only. In particular, Exec and TryExec are never executed."""
    try:
        if path.stat().st_size > 256_000:
            return None
        config = configparser.ConfigParser(interpolation=None, strict=False)
        config.optionxform = str
        config.read_string(path.read_text(encoding="utf-8-sig"))
        entry = config["Desktop Entry"]
        if entry.get("Type", "Application") != "Application":
            return None
        if entry.get("Hidden", "false").lower() == "true" or entry.get("NoDisplay", "false").lower() == "true":
            return None
        language = (language or locale.getlocale()[0] or "").split(".", 1)[0]
        name = entry.get(f"Name[{language}]", entry.get(f"Name[{language.split('_')[0]}]", entry.get("Name", "")))
        icon = entry.get("Icon", "").strip()
        if not name.strip() or not icon:
            return None
        return DesktopEntry(name.strip(), icon)
    except (OSError, UnicodeError, configparser.Error, KeyError):
        return None


def _directory_entries(path: Path, suffixes: tuple[str, ...] | None = None, depth: int = 0, budget: int = 500):
    """Bounded local traversal: no symlink directories and never inside .app bundles."""
    if str(path).startswith("\\\\") or not path.is_dir():
        return
    pending = [(path, 0)]
    seen = 0
    while pending and seen < budget:
        folder, current_depth = pending.pop(0)
        try:
            entries = sorted(folder.iterdir(), key=lambda item: item.name.casefold())
        except OSError:
            continue
        for item in entries:
            seen += 1
            if seen > budget:
                return
            if item.name.startswith(".") or item.name.casefold() in ("desktop.ini", "thumbs.db"):
                continue
            try:
                if suffixes is None or item.suffix.lower() in suffixes:
                    yield item
                if current_depth < depth and item.is_dir() and not item.is_symlink() and item.suffix.lower() != ".app":
                    pending.append((item, current_depth + 1))
            except OSError:
                continue


def desktop_directories() -> list[Path]:
    value = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
    directories = [Path(value)] if value else [Path.home() / "Desktop"]
    if platform.system() == "Windows":
        # CSIDL_COMMON_DESKTOPDIRECTORY is the shell's configured public desktop.
        buffer = ctypes.create_unicode_buffer(32768)
        try:
            if ctypes.windll.shell32.SHGetFolderPathW(None, 0x0019, None, 0, buffer) == 0:
                directories.append(Path(buffer.value))
        except (AttributeError, OSError):
            pass
    return list(dict.fromkeys(directories))


def _application_paths(system: str):
    if system == "Windows":
        candidates = []
        for variable in ("APPDATA", "PROGRAMDATA"):
            base = os.environ.get(variable)
            if base:
                candidates.extend(_directory_entries(Path(base) / "Microsoft/Windows/Start Menu/Programs", (".lnk",), depth=3, budget=1400))
        root = Path(os.environ.get("WINDIR", r"C:\Windows"))
        for relative in ("explorer.exe", "System32/notepad.exe", "System32/mspaint.exe", "System32/calc.exe", "System32/WindowsPowerShell/v1.0/powershell.exe", "System32/cmd.exe"):
            path = root / relative
            if path.is_file():
                candidates.append(path)
        # User and common Start menus are considered together, so developer
        # command prompts cannot crowd out Chrome, Word, or other main apps.
        yield from sorted(dict.fromkeys(candidates), key=_application_priority)
    elif system == "Darwin":
        for root in (Path("/Applications"), Path("/System/Applications"), Path.home() / "Applications", Path("/System/Library/CoreServices")):
            yield from _directory_entries(root, (".app",), depth=1, budget=450)
    else:
        roots = [Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))]
        roots.extend(Path(root) for root in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":"))
        roots.extend((Path("/var/lib/flatpak/exports/share"), Path.home() / ".local/share/flatpak/exports/share", Path("/var/lib/snapd/desktop")))
        seen_names = set()
        for root in dict.fromkeys(roots):
            for path in _directory_entries(root / "applications", (".desktop",), depth=1, budget=700):
                # XDG gives user overrides priority over system applications.
                if path.name not in seen_names:
                    seen_names.add(path.name)
                    yield path


def _linux_theme_roots() -> list[Path]:
    roots = [Path.home() / ".icons", Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "icons"]
    roots.extend(Path(root) / "icons" for root in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":"))
    return list(dict.fromkeys(roots))


def _themed_icon(name: str) -> QIcon:
    """Use the selected desktop theme, then installed hicolor files, never a logo URL."""
    if Path(name).is_absolute():
        return QIcon(name) if Path(name).is_file() else QIcon()
    if "/" in name or "\\" in name or name in (".", ".."):
        return QIcon()
    icon = QIcon.fromTheme(name)
    if not icon.isNull():
        return icon
    filename = Path(name)
    basenames = (name,) if filename.suffix.lower() in (".png", ".svg", ".xpm") else (name + ".png", name + ".svg", name + ".xpm")
    themes = tuple(dict.fromkeys((QIcon.themeName(), QIcon.fallbackThemeName(), "hicolor", "Adwaita", "breeze")))
    for root in _linux_theme_roots():
        for theme in themes:
            if not theme or "/" in theme or "\\" in theme:
                continue
            for size in ("128x128", "64x64", "48x48", "scalable", "256x256", "32x32", "512x512", "symbolic"):
                for context in ("apps", "applications", "places", "mimetypes", "devices"):
                    for basename in basenames:
                        candidate = root / theme / size / context / basename
                        if candidate.is_file():
                            icon = QIcon(str(candidate))
                            if not icon.isNull():
                                return icon
    for root in (Path("/usr/share/pixmaps"), Path("/usr/local/share/pixmaps")):
        for basename in basenames:
            path = root / basename
            if path.is_file():
                return QIcon(str(path))
    return QIcon()


def _quiet_read(command: list[str]) -> str:
    executable = shutil.which(command[0])
    if not executable:
        return ""
    try:
        result = subprocess.run([executable, *command[1:]], capture_output=True, text=True, timeout=1.5, check=False)
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _remote_windows_shortcut(path: Path) -> bool:
    """Avoid asking the Shell to resolve icon resources from UNC shortcuts.

    This only inspects bounded shortcut metadata, not the shortcut target. Shell
    link strings may be ANSI or UTF-16; either UNC spelling is excluded.
    """
    if path.suffix.lower() != ".lnk":
        return False
    try:
        if path.stat().st_size > 1_048_576:
            return True
        metadata = path.read_bytes()
        return b"\\\\" in metadata or "\\\\".encode("utf-16-le") in metadata
    except OSError:
        return True


def _shortcut_artwork(path: Path) -> tuple[Path | None, bool]:
    """Return real local artwork/target metadata without resolving or running a link.

    The boolean distinguishes an explicit IconLocation from an ordinary target.
    Reading Shell Link metadata directly avoids asking COM to resolve missing
    targets. In particular, Qt sometimes gives a generic icon for a valid .lnk
    whose IconLocation is empty, while the real target .exe has its proper logo.
    """
    try:
        if path.stat().st_size > 1_048_576:
            return None, False
        data = path.read_bytes()
        if len(data) < 76 or struct.unpack_from("<I", data)[0] != 76:
            return None, False
        flags = struct.unpack_from("<I", data, 20)[0]
        offset = 76
        if flags & 1:  # HasLinkTargetIDList
            offset += 2 + struct.unpack_from("<H", data, offset)[0]
        target = ""

        def terminated(start: int, end: int, wide: bool = False) -> str:
            if start <= 0 or start >= end or end > len(data):
                return ""
            step = 2 if wide else 1
            stop = start
            while stop + step <= end and data[stop:stop + step] != b"\0" * step:
                stop += step
            return data[start:stop].decode("utf-16-le" if wide else "cp1252", errors="replace")

        if flags & 2:  # HasLinkInfo
            block_size, header_size = struct.unpack_from("<II", data, offset)
            end = offset + block_size
            if block_size < 28 or end > len(data):
                return None, False
            local_offset = struct.unpack_from("<I", data, offset + 16)[0]
            wide_offset = struct.unpack_from("<I", data, offset + 28)[0] if header_size >= 36 else 0
            if wide_offset:
                target = terminated(offset + wide_offset, end, True)
            elif local_offset:
                target = terminated(offset + local_offset, end)
            offset = end
        icon_location = ""
        for flag in (4, 8, 16, 32, 64):  # Name, RelativePath, WorkingDir, Arguments, Icon
            if not flags & flag:
                continue
            length = struct.unpack_from("<H", data, offset)[0]
            offset += 2
            byte_count = length * (2 if flags & 128 else 1)
            if offset + byte_count > len(data):
                return None, False
            value = data[offset:offset + byte_count].decode("utf-16-le" if flags & 128 else "cp1252", errors="replace")
            if flag == 64:
                icon_location = value
            offset += byte_count
        artwork = os.path.expandvars(icon_location or target).strip().strip('"')
        if not artwork or artwork.startswith("\\\\") or "://" in artwork:
            return None, bool(icon_location)
        candidate = Path(artwork)
        if not candidate.is_absolute() or not candidate.is_file():
            return None, bool(icon_location)
        return candidate, bool(icon_location)
    except (OSError, ValueError, struct.error):
        return None, False


def _windows_artwork(path: Path, provider: QFileIconProvider) -> QIcon:
    artwork = path
    explicit = False
    if path.suffix.lower() == ".lnk":
        candidate, explicit = _shortcut_artwork(path)
        if candidate is None:
            # Do not label a generic broken-shortcut icon as a real application.
            return QIcon()
        artwork = candidate
    if artwork.suffix.lower() in (".ico", ".png", ".bmp"):
        return QIcon(str(artwork))
    if artwork.suffix.lower() in (".exe", ".dll"):
        try:
            if ctypes.windll.shell32.ExtractIconExW(str(artwork), -1, None, None, 0) <= 0:
                return QIcon()
        except (AttributeError, OSError):
            return QIcon()
    # Preserve an explicitly indexed resource from the shortcut. Empty
    # IconLocation shortcuts use the actual executable instead of Qt's fallback.
    return provider.icon(QFileInfo(str(path if explicit else artwork)))


def _wallpaper_path(system: str) -> Path | None:
    value = ""
    if system == "Windows":
        try:
            buffer = ctypes.create_unicode_buffer(32768)
            if ctypes.windll.user32.SystemParametersInfoW(0x0073, len(buffer), buffer, 0):
                value = buffer.value
        except (AttributeError, OSError):
            pass
    elif system == "Darwin":
        # Call AppKit locally through JXA, avoiding Apple Events sent to System
        # Events (which would otherwise request macOS Automation permission).
        value = _quiet_read(["osascript", "-l", "JavaScript", "-e", 'ObjC.import("AppKit"); ObjC.unwrap($.NSWorkspace.sharedWorkspace.desktopImageURLForScreen($.NSScreen.mainScreen).path)'])
    elif "gnome" in os.environ.get("XDG_CURRENT_DESKTOP", "").lower() or "cinnamon" in os.environ.get("XDG_CURRENT_DESKTOP", "").lower():
        schema = "org.cinnamon.desktop.background" if "cinnamon" in os.environ.get("XDG_CURRENT_DESKTOP", "").lower() else "org.gnome.desktop.background"
        value = _quiet_read(["gsettings", "get", schema, "picture-uri"]).strip("'\"")
        if not value and schema == "org.gnome.desktop.background":
            value = _quiet_read(["gsettings", "get", schema, "picture-uri-dark"]).strip("'\"")
    elif "xfce" in os.environ.get("XDG_CURRENT_DESKTOP", "").lower():
        props = _quiet_read(["xfconf-query", "-c", "xfce4-desktop", "-l"])
        candidate = next((line for line in props.splitlines() if line.endswith("/last-image")), "")
        if candidate:
            value = _quiet_read(["xfconf-query", "-c", "xfce4-desktop", "-p", candidate])
    if value.startswith("file:"):
        parsed = urlparse(value)
        if parsed.netloc not in ("", "localhost"):
            return None
        value = unquote(parsed.path)
    if not value or value.startswith("\\\\") or "://" in value:
        return None
    path = Path(value)
    return path if path.is_file() else None


def load_assets(demo: bool = False) -> NativeAssets:
    """Call after creating QApplication, from its GUI thread.

    Desktop entries are first. If there are fewer than 24, installed apps fill the
    collection. When artwork is unavailable, no fictional substitute is created.
    """
    if QApplication.instance() is None:
        raise RuntimeError("Create QApplication before reading native icons")
    system = platform.system()
    assets = NativeAssets(platform_label=platform_label())
    provider = QFileIconProvider()
    names_seen: set[str] = set()
    paths_seen: set[str] = set()

    def add_path(path: Path, source: str) -> None:
        if len(assets.icons) >= 80 or str(path).startswith("\\\\"):
            return
        if system == "Windows" and (_remote_windows_shortcut(path) or path.suffix.lower() == ".url"):
            return
        path_key = str(path).casefold() if system == "Windows" else str(path)
        if path_key in paths_seen:
            return
        paths_seen.add(path_key)
        name = path.stem if path.suffix.lower() in (".lnk", ".url", ".app", ".exe", ".desktop") else path.name
        if source == "application" and re.search(r"uninstall|remove|repair|readme|manual|documentation|help|卸载|自述|帮助", name, re.I):
            return
        if path.suffix.lower() == ".desktop":
            entry = parse_desktop_entry(path, "en_US" if demo else None)
            if entry is None:
                return
            name, icon = entry.name, _themed_icon(entry.icon)
        else:
            # Friendly names for actual executable artwork, not synthetic resources.
            if system == "Windows" and path.suffix.lower() == ".exe":
                name = _WINDOWS_EXE_NAMES.get(name.lower(), name)
            icon = _windows_artwork(path, provider) if system == "Windows" and path.suffix.lower() in (".lnk", ".exe") else provider.icon(QFileInfo(str(path)))
        if demo:
            name = safe_demo_name(name)
            if not name:
                return
        if not name or name.casefold() in names_seen or icon.isNull():
            return
        pixmap = icon.pixmap(96, 96)
        if pixmap.isNull():
            return
        names_seen.add(name.casefold())
        assets.icons.append(NativeIcon(name, pixmap, source))

    if not demo:
        for directory in desktop_directories():
            for path in _directory_entries(directory, budget=300):
                if len(assets.icons) >= 80:
                    break
                if system == "Windows":
                    try:
                        attributes = path.stat().st_file_attributes
                        if attributes & 6:  # FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM
                            continue
                    except (AttributeError, OSError):
                        pass
                add_path(path, "desktop")
    if len(assets.icons) < 24:
        for path in _application_paths(system):
            add_path(path, "application")
            if len(assets.icons) >= 24:
                break

    if len(assets.icons) < 6:
        if system in ("Windows", "Darwin"):
            # These are the OS's real standard icons, obtained through the same
            # native file icon provider; they are labelled as system resources.
            for kind, name in ((QFileIconProvider.IconType.Computer, "Computer"), (QFileIconProvider.IconType.Folder, "Folder"), (QFileIconProvider.IconType.File, "File"), (QFileIconProvider.IconType.Trashcan, "Trash")):
                icon = provider.icon(kind)
                pixmap = icon.pixmap(96, 96)
                if not pixmap.isNull() and name.casefold() not in names_seen:
                    assets.icons.append(NativeIcon(name, pixmap, "system"))
                    names_seen.add(name.casefold())
        else:
            for icon_name, name in (("computer", "Computer"), ("folder", "Folder"), ("user-trash", "Trash"), ("text-x-generic", "Text document")):
                pixmap = _themed_icon(icon_name).pixmap(96, 96)
                if not pixmap.isNull() and name.casefold() not in names_seen:
                    assets.icons.append(NativeIcon(name, pixmap, "system"))
                    names_seen.add(name.casefold())

    assets.desktop_count = sum(icon.source == "desktop" for icon in assets.icons)
    assets.application_count = sum(icon.source == "application" for icon in assets.icons)
    assets.system_count = sum(icon.source == "system" for icon in assets.icons)
    if not assets.icons:
        assets.notes.append("No local native icons were available. Install a desktop icon theme or add desktop shortcuts.")
    elif len(assets.icons) < 6:
        assets.notes.append("Only a few native icons were available; the game can reuse these authentic icons.")
    if demo:
        assets.notes.append("Public demo: installed application icons only; desktop names and wallpaper omitted.")
    else:
        path = _wallpaper_path(system)
        if path:
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                assets.wallpaper = pixmap
        if assets.wallpaper is None:
            assets.notes.append("Wallpaper unavailable; using the game's plain background.")
    return assets
