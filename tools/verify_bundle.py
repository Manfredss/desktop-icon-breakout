"""Launch the bundled binary with its own Python/Qt and verify a real render."""
import json
from pathlib import Path
import platform
import subprocess

root = Path(__file__).resolve().parents[1]
system = platform.system()
if system == "Darwin":
    binary = root / "dist/DesktopIconBreakout.app/Contents/MacOS/DesktopIconBreakout"
else:
    binary = root / "dist/DesktopIconBreakout" / ("DesktopIconBreakout.exe" if system == "Windows" else "DesktopIconBreakout")
image = root / "build/bundle-smoke.png"
subprocess.run([str(binary), "--demo", "--lang", "en", "--smoke-test", str(image)], check=True, timeout=60)
data = json.loads(image.with_suffix(".json").read_text(encoding="utf-8"))
assert data["icons"] > 0 and data["desktop"] == 0
assert image.stat().st_size > 10000
print(f"Packaged app verified: {data['platform']}, {data['icons']} native icons.")
