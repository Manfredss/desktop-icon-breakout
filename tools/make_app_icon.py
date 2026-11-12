"""Generate our own app badge, never replacement icons for installed software."""
from pathlib import Path
from PIL import Image, ImageDraw

root = Path(__file__).resolve().parents[1] / "assets"
root.mkdir(exist_ok=True)
im = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
d = ImageDraw.Draw(im)
d.rounded_rectangle((16, 16, 1008, 1008), radius=216, fill="#10192d")
for y, color in [(196, "#b09aff"), (384, "#5edfcb")]:
    for x in [160, 408, 656]:
        if y == 384 and x == 408:
            continue
        d.rounded_rectangle((x, y, x+204, y+136), radius=28, fill=color)
d.line((408, 720, 544, 548, 636, 648), fill="#8278b7", width=24)
d.ellipse((592, 604, 680, 692), fill="#f4f1ff")
d.rounded_rectangle((244, 820, 780, 880), radius=28, fill="#ae97ff")
im.save(root / "app.png")
im.save(root / "app.ico", sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
im.save(root / "app.icns")
