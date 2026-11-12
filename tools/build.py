"""Build on the target OS. The archive includes Python and the Qt runtime."""
from __future__ import annotations

import hashlib
import os
from importlib import metadata
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desktop_breakout import __version__


def main() -> None:
    system = platform.system()
    label = {"Windows": "windows", "Darwin": "macos", "Linux": "linux"}[system]
    arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"
    name = f"DesktopIconBreakout-v{__version__}-{label}-{arch}"
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--onedir",
               "--name", "DesktopIconBreakout", "--add-data", "assets:assets",
               "--exclude-module", "PIL", "--exclude-module", "pytest", "--exclude-module", "tkinter"]
    if system == "Windows":
        command += ["--icon", "assets/app.ico"]
    elif system == "Darwin":
        command += ["--icon", "assets/app.icns", "--osx-bundle-identifier", "io.github.manfredss.desktop-icon-breakout"]
    command += ["app.py"]
    environment = dict(os.environ)
    environment.setdefault("PYINSTALLER_CONFIG_DIR", str(ROOT / "build" / ".pyinstaller-cache"))
    subprocess.run(command, cwd=ROOT, env=environment, check=True)
    distribution = ROOT / "dist" / ("DesktopIconBreakout.app" if system == "Darwin" else "DesktopIconBreakout")
    ancillary = distribution / "Contents" / "Resources" if system == "Darwin" else distribution
    licenses = ancillary / "licenses"
    licenses.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT / "licenses", licenses, dirs_exist_ok=True)
    for package in ("PySide6-Essentials", "shiboken6", "PyInstaller"):
        dist = metadata.distribution(package)
        for entry in dist.files or []:
            if any(word in str(entry).lower() for word in ("license", "copying")) and entry.suffix.lower() in (".txt", ".md", ""):
                original = Path(dist.locate_file(entry))
                if original.is_file():
                    target = licenses / package / Path(str(entry)).name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(original, target)
    for path in (Path(sys.base_prefix) / "LICENSE.txt", Path(sys.base_prefix) / "LICENSE"):
        if path.is_file():
            shutil.copy2(path, licenses / "Python-LICENSE.txt")
            break
    for doc in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(ROOT / doc, ancillary / doc)
    shutil.copy2(ROOT / "docs" / "QUICKSTART.txt", ancillary / "START-HERE.txt")
    output = ROOT / "release"
    output.mkdir(exist_ok=True)
    if system == "Linux":
        archive = output / f"{name}.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(distribution, arcname="DesktopIconBreakout")
    elif system == "Darwin":
        archive = output / f"{name}.zip"
        # Adding notices after PyInstaller's BUNDLE invalidates its ad-hoc seal.
        subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(distribution)], check=True)
        subprocess.run(["codesign", "--verify", "--all-architectures", "--deep", "--strict", str(distribution)], check=True)
        subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(distribution), str(archive)], check=True)
    else:
        archive = output / f"{name}.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for path in sorted(distribution.rglob("*")):
                if path.is_file():
                    zf.write(path, Path("DesktopIconBreakout") / path.relative_to(distribution))
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(archive.suffix + ".sha256").write_text(f"{checksum}  {archive.name}\n", encoding="utf-8")
    print(f"Built {archive.name}: {archive.stat().st_size / 1024**2:.1f} MiB")


if __name__ == "__main__":
    main()
