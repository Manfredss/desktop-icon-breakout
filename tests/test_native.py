from pathlib import Path
import struct

import pytest

from desktop_breakout.native import parse_desktop_entry, safe_demo_name, _directory_entries, _remote_windows_shortcut, _application_priority, _shortcut_artwork


def write_entry(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "sample.desktop"
    path.write_text(text, encoding="utf-8")
    return path


def test_desktop_metadata_localization_and_exec_is_never_run(tmp_path):
    marker = tmp_path / "must-not-exist"
    entry = parse_desktop_entry(write_entry(tmp_path, f"[Desktop Entry]\nType=Application\nName=Editor\nName[zh_CN]=编辑器\nIcon=editor\nExec=touch {marker}\n"), "zh_CN")
    assert entry.name == "编辑器"
    assert entry.icon == "editor"
    assert not marker.exists()


@pytest.mark.parametrize("setting", ["Hidden=true", "NoDisplay=true", "Type=Link"])
def test_ineligible_entries_are_skipped(tmp_path, setting):
    path = write_entry(tmp_path, f"[Desktop Entry]\nName=Private\nIcon=private\n{setting}\n")
    assert parse_desktop_entry(path) is None


def test_metadata_requires_real_icon_reference(tmp_path):
    assert parse_desktop_entry(write_entry(tmp_path, "[Desktop Entry]\nName=No artwork\n")) is None


def test_malformed_entry_and_missing_file_are_safe(tmp_path):
    assert parse_desktop_entry(write_entry(tmp_path, "not an INI file")) is None
    assert parse_desktop_entry(tmp_path / "missing.desktop") is None


def test_language_falls_back_to_base_then_default(tmp_path):
    path = write_entry(tmp_path, "[Desktop Entry]\nName=Editor\nName[zh]=编辑器\nIcon=editor\n")
    assert parse_desktop_entry(path, "zh_TW").name == "编辑器"
    assert parse_desktop_entry(path, "fr_FR").name == "Editor"


def test_percent_placeholders_are_not_interpolated(tmp_path):
    path = write_entry(tmp_path, "[Desktop Entry]\nName=100% Editor\nIcon=editor\nExec=editor %U\n")
    assert parse_desktop_entry(path).name == "100% Editor"


def test_demo_does_not_publish_unrecognized_names_or_paths():
    assert safe_demo_name("Google Chrome") == "Google Chrome"
    assert safe_demo_name("Visual Studio Code (User)") == "Visual Studio Code"
    assert safe_demo_name("Quarterly payroll") is None
    assert safe_demo_name(r"C:\Users\private\Google Chrome") is None
    assert safe_demo_name("MyFirefoxDocument") is None


@pytest.mark.parametrize("name", [
    "Anaconda PowerShell Prompt", "Anaconda Prompt (Anaconda3)",
    "Visual Studio Code Command Prompt", "Developer Command Prompt for VS 2022",
    "Python Console", "Windows PowerShell ISE", "Git Shell",
])
def test_demo_does_not_relabel_auxiliary_shortcuts_as_main_apps(name):
    assert safe_demo_name(name) is None


def test_native_main_applications_come_before_auxiliary_shortcuts():
    candidates = [Path(name) for name in (
        "Anaconda PowerShell Prompt.lnk", "Visual Studio Code Command Prompt.lnk",
        "Anaconda Navigator.lnk", "Excel.lnk", "Google Chrome.lnk",
        "Visual Studio Code.lnk", "notepad.exe", "explorer.exe",
    )]
    assert [item.stem for item in sorted(candidates, key=_application_priority)] == [
        "Google Chrome", "Visual Studio Code", "Excel", "notepad", "explorer",
        "Anaconda Navigator", "Anaconda PowerShell Prompt", "Visual Studio Code Command Prompt",
    ]
    assert safe_demo_name("Command Prompt") == "Command Prompt"
    assert safe_demo_name("PowerShell 7 (x64)") == "PowerShell"


def test_traversal_does_not_descend_into_app_bundles(tmp_path):
    app = tmp_path / "Editor.app"
    app.mkdir()
    (app / "Private.app").mkdir()
    folder = tmp_path / "Utilities"
    folder.mkdir()
    (folder / "Terminal.app").mkdir()
    names = [path.name for path in _directory_entries(tmp_path, (".app",), depth=1)]
    assert names == ["Editor.app", "Terminal.app"]


def test_traversal_budget_is_enforced(tmp_path):
    for index in range(10):
        (tmp_path / f"{index}.desktop").touch()
    assert len(list(_directory_entries(tmp_path, (".desktop",), budget=3))) == 3


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16-le"])
def test_network_shortcut_resources_are_not_resolved(tmp_path, encoding):
    shortcut = tmp_path / "Network app.lnk"
    shortcut.write_bytes(r"\\server\share\app.exe".encode(encoding))
    assert _remote_windows_shortcut(shortcut)
    shortcut.write_bytes(r"C:\Apps\app.exe".encode(encoding))
    assert not _remote_windows_shortcut(shortcut)


def make_shortcut(path, target, explicit_icon=None):
    target_bytes = str(target).encode("utf-16-le") + b"\0\0"
    header = bytearray(76)
    struct.pack_into("<I", header, 0, 76)
    struct.pack_into("<I", header, 20, 2 | 128 | (64 if explicit_icon else 0))
    link_info = bytearray(36)
    struct.pack_into("<II", link_info, 0, 36 + len(target_bytes), 36)
    struct.pack_into("<I", link_info, 28, 36)
    data = bytes(header + link_info) + target_bytes
    if explicit_icon:
        icon_string = str(explicit_icon)
        data += struct.pack("<H", len(icon_string)) + icon_string.encode("utf-16-le")
    path.write_bytes(data)
    return path


def test_empty_icon_location_uses_real_target_artwork(tmp_path):
    target = tmp_path / "Code.exe"
    target.touch()
    shortcut = make_shortcut(tmp_path / "Visual Studio Code.lnk", target)
    assert _shortcut_artwork(shortcut) == (target, False)


def test_explicit_native_icon_is_preserved(tmp_path):
    target, artwork = tmp_path / "pythonw.exe", tmp_path / "navigator.ico"
    target.touch()
    artwork.touch()
    shortcut = make_shortcut(tmp_path / "Navigator.lnk", target, artwork)
    assert _shortcut_artwork(shortcut) == (artwork, True)


def test_broken_and_malformed_shortcuts_do_not_get_fake_application_artwork(tmp_path):
    shortcut = make_shortcut(tmp_path / "Missing.lnk", tmp_path / "missing.exe")
    assert _shortcut_artwork(shortcut)[0] is None
    shortcut.write_bytes(b"not a shell link")
    assert _shortcut_artwork(shortcut)[0] is None
