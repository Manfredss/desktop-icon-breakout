"""Small original arcade tones. Windows audio is optional and fails quietly."""
from __future__ import annotations

import math
import os
import struct
import tempfile
import time
import wave
from pathlib import Path


class ArcadeAudio:
    def __init__(self) -> None:
        self.available = os.name == "nt"
        self._temporary = None
        self._sounds: dict[str, str] = {}
        self._last = 0.0
        if not self.available:
            return
        try:
            import winsound
            self._winsound = winsound
            self._temporary = tempfile.TemporaryDirectory(prefix="desktop-breakout-audio-")
            tones = {"brick": (760, .065), "paddle": (380, .045), "wall": (240, .025),
                     "launch": (540, .08), "pickup": (1060, .13), "lose": (140, .22),
                     "win": (1350, .25), "gameover": (110, .32)}
            for name, (frequency, duration) in tones.items():
                path = Path(self._temporary.name) / f"{name}.wav"
                rate = 22050
                count = int(rate * duration)
                frames = bytearray()
                for i in range(count):
                    t = i / rate
                    envelope = min(1, i / 100) * (1 - i / count) ** 2
                    value = math.sin(2 * math.pi * frequency * t * (1 + t * .9))
                    frames.extend(struct.pack("<h", int(value * envelope * 4500)))
                with wave.open(str(path), "wb") as output:
                    output.setnchannels(1)
                    output.setsampwidth(2)
                    output.setframerate(rate)
                    output.writeframes(frames)
                self._sounds[name] = str(path)
        except (ImportError, OSError, RuntimeError):
            self.available = False

    def play(self, name: str) -> None:
        if not self.available:
            return
        name = {"break": "brick", "hit": "brick", "powerup": "pickup"}.get(name, name)
        now = time.monotonic()
        if now - self._last < .035 and name not in {"win", "lose", "gameover"}:
            return
        if name not in self._sounds:
            return
        try:
            self._winsound.PlaySound(self._sounds[name], self._winsound.SND_FILENAME |
                                    self._winsound.SND_ASYNC | self._winsound.SND_NODEFAULT)
            self._last = now
        except (OSError, RuntimeError):
            pass

    def close(self) -> None:
        if self.available:
            try:
                self._winsound.PlaySound(None, 0)
            except (OSError, RuntimeError):
                pass
        if self._temporary:
            try:
                self._temporary.cleanup()
            except OSError:
                pass
