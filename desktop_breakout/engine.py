"""Deterministic, renderer-independent breakout physics.

The simulation uses a 1440 x 900 logical playfield. Nothing here accesses the
filesystem, operating-system desktop, graphics toolkit, or network.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
import math
import random
from typing import Callable, Iterable


class PlayState(str, Enum):
    READY = "ready"
    PLAYING = "playing"
    PAUSED = "paused"
    WON = "won"
    GAME_OVER = "game_over"


@dataclass
class Brick:
    x: float
    y: float
    width: float
    height: float
    icon_index: int = 0
    color_index: int = 0
    hit_points: int = 1
    alive: bool = True


@dataclass
class Ball:
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    radius: float = 8.0
    trail: list[tuple[float, float]] = field(default_factory=list)


@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    life: float
    max_life: float
    color_index: int


@dataclass
class Pickup:
    x: float
    y: float
    kind: str = "wide"


ARENA_LEFT = 24.0
ARENA_RIGHT = 1416.0
ARENA_TOP = 110.0
ARENA_BOTTOM = 900.0
PADDLE_HEIGHT = 16.0


def clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


def build_level(icon_count: int, level: int = 1, unique: bool = False) -> list[Brick]:
    """Arrange existing icons; never invent an icon when the library is empty."""
    if icon_count <= 0:
        return []
    level = max(1, level)
    if unique:
        total = min(80, icon_count)
        columns = min(12, max(4, math.ceil(math.sqrt(total * 1.8))))
        return [
            Brick(720 - columns * 51 + (i % columns) * 102,
                  175 + (i // columns) * 76, 90, 60, i, i % 6)
            for i in range(total)
        ]
    rows = min(7, 4 + (level - 1) // 2)
    return [
        Brick(110 + column * 102, 170 + row * 76, 90, 60,
              (row * 12 + column + (level - 1) * 7) % icon_count,
              row % 6, 2 if level >= 3 and row == 0 else 1)
        for row in range(rows)
        for column in range(12)
        if not (level % 3 == 2 and row > 0 and (column + row) % 5 == 0)
    ]


class GameEngine:
    ARENA_LEFT = ARENA_LEFT
    ARENA_RIGHT = ARENA_RIGHT
    ARENA_TOP = ARENA_TOP
    ARENA_BOTTOM = ARENA_BOTTOM
    PADDLE_HEIGHT = PADDLE_HEIGHT
    NORMAL_PADDLE_WIDTH = 154.0

    def __init__(self, seed: int | None = None):
        self.random = random.Random(seed)
        self.score = 0
        self.lives = 3
        self.level = 1
        self.combo = 0
        self.best_combo = 0
        self.state = PlayState.READY
        self.bricks: list[Brick] = []
        self.balls: list[Ball] = []
        self.particles: list[Particle] = []
        self.pickups: list[Pickup] = []
        self.paddle_x = 720.0
        self.paddle_width = self.NORMAL_PADDLE_WIDTH
        self.paddle_y = 830.0
        self.elapsed = 0.0
        self.language = "zh"
        self.notice_code = "ready"
        self.notice_time = 3.0
        self.sound: Callable[[str], None] | None = None
        self._before_pause = PlayState.READY
        self._wide_remaining = 0.0
        self._slow_remaining = 0.0
        self._combo_remaining = 0.0
        self._assist = False

    @property
    def remaining_bricks(self) -> int:
        return sum(brick.alive for brick in self.bricks)

    @property
    def starting_speed(self) -> float:
        return min(680, 470 + (self.level - 1) * 32)

    @property
    def active_effect(self) -> str:
        english = self.language.startswith("en")
        effects = []
        if self._wide_remaining > 0:
            effects.append(f"{'Wide' if english else '加宽'} {math.ceil(self._wide_remaining)}s")
        if self._slow_remaining > 0:
            effects.append(f"{'Slow' if english else '慢速'} {math.ceil(self._slow_remaining)}s")
        if len(self.balls) > 1:
            effects.append(f"{len(self.balls)} {'balls' if english else '球齐发'}")
        return " · ".join(effects)

    @property
    def notice(self) -> str:
        messages = {
            "ready": ("点击鼠标或按空格发球", "Click or press Space to launch"),
            "combo": (f"{self.combo} 连击！", f"{self.combo} HIT COMBO!"),
            "won": ("全部击破 · 漂亮！", "All icons cleared. Excellent work."),
            "game_over": ("再来一局，打破纪录", "One more round. One less excuse."),
            "life": (f"还剩 {self.lives} 条命 · 点击继续", f"{self.lives} lives left · click to launch"),
            "wide": ("加宽挡板 · 14 秒", "Wide paddle · 14 seconds"),
            "slow": ("慢速时间 · 10 秒", "Slow motion · 10 seconds"),
            "multiball": ("多球齐发！", "MULTIBALL!"),
        }
        return messages.get(self.notice_code, ("", ""))[self.language.startswith("en")]

    def start(self, bricks: Iterable[Brick], level: int = 1, reset_score: bool = True) -> None:
        if reset_score:
            self.score = 0
            self.lives = 3
            self.best_combo = 0
            self.elapsed = 0.0
        self.level = max(1, level)
        self.combo = 0
        self._combo_remaining = self._wide_remaining = self._slow_remaining = 0.0
        self.paddle_width = self.NORMAL_PADDLE_WIDTH
        self.paddle_x = 720.0
        self.particles.clear()
        self.pickups.clear()
        self.bricks = [
            replace(brick, alive=True, hit_points=max(1, brick.hit_points))
            for brick in bricks
            if all(math.isfinite(v) for v in (brick.x, brick.y, brick.width, brick.height))
            and brick.width > 0 and brick.height > 0
        ]
        self._reset_ball()
        self.state = PlayState.READY if self.bricks else PlayState.WON
        self._announce("ready", 3)

    def set_paddle(self, center: float) -> None:
        if not math.isfinite(center) or self.state == PlayState.PAUSED:
            return
        self.paddle_x = clamp(center, ARENA_LEFT + self.paddle_width / 2,
                              ARENA_RIGHT - self.paddle_width / 2)
        if self.state == PlayState.READY and self.balls:
            self.balls[0].x = self.paddle_x
            self.balls[0].y = self.paddle_y - self.balls[0].radius - 2

    def move_paddle(self, dx: float) -> None:
        self.set_paddle(self.paddle_x + dx)

    def set_assist(self, enabled: bool) -> None:
        self._assist = enabled

    def launch(self) -> None:
        if self.state != PlayState.READY or not self.balls:
            return
        ball = self.balls[0]
        angle = (self.random.random() - 0.5) * 0.55
        ball.vx = math.sin(angle) * self.starting_speed
        ball.vy = -math.cos(angle) * self.starting_speed
        self.state = PlayState.PLAYING
        self.notice_time = 0.0
        self._play("launch")

    def toggle_pause(self) -> None:
        if self.state == PlayState.PAUSED:
            self.state = self._before_pause
        elif self.state in (PlayState.PLAYING, PlayState.READY):
            self._before_pause = self.state
            self.state = PlayState.PAUSED

    def update(self, seconds: float) -> None:
        if self.state == PlayState.PAUSED or not math.isfinite(seconds) or seconds <= 0:
            return
        # Ignore suspended-window time instead of catching up with an unfair death.
        dt = min(seconds, 0.1)
        self._advance_particles(dt)
        self.notice_time = max(0.0, self.notice_time - dt)
        if self.state != PlayState.PLAYING:
            return
        self.elapsed += dt
        self._advance_effects(dt)
        if self._assist:
            descending = [b for b in self.balls if b.vy > 0]
            if descending:
                target = max(descending, key=lambda b: b.y)
                self.set_paddle(self.paddle_x + clamp(target.x - self.paddle_x, -980 * dt, 980 * dt))
        # At most 45% of the smallest radius per step, including very fast balls.
        max_speed = max((math.hypot(b.vx, b.vy) for b in self.balls), default=1.0)
        min_radius = min((max(1.0, b.radius) for b in self.balls), default=8.0)
        steps = max(1, math.ceil(max_speed * dt / (min_radius * 0.45)))
        step = dt / steps
        for _ in range(steps):
            if self.state != PlayState.PLAYING:
                break
            for ball in self.balls[:]:
                ball.x += ball.vx * step
                ball.y += ball.vy * step
                self._hit_walls(ball)
                self._hit_paddle(ball)
                self._hit_bricks(ball)
                if self.state != PlayState.PLAYING:
                    break
                if ball.y - ball.radius > ARENA_BOTTOM:
                    self.balls.remove(ball)
            if self.state == PlayState.PLAYING and not self.balls:
                self._lose_life()
        for ball in self.balls:
            ball.trail.insert(0, (ball.x, ball.y))
            del ball.trail[10:]
        if self.state == PlayState.PLAYING:
            self._advance_pickups(dt)

    def _reset_ball(self) -> None:
        self.balls = [Ball(self.paddle_x, self.paddle_y - 10)]

    def _hit_walls(self, ball: Ball) -> None:
        hit = False
        if ball.x - ball.radius < ARENA_LEFT:
            ball.x = ARENA_LEFT + ball.radius
            ball.vx = abs(ball.vx)
            hit = True
        elif ball.x + ball.radius > ARENA_RIGHT:
            ball.x = ARENA_RIGHT - ball.radius
            ball.vx = -abs(ball.vx)
            hit = True
        if ball.y - ball.radius < ARENA_TOP:
            ball.y = ARENA_TOP + ball.radius
            ball.vy = abs(ball.vy)
            hit = True
        if hit:
            self._play("wall")

    def _hit_paddle(self, ball: Ball) -> None:
        if ball.vy <= 0 or ball.y > self.paddle_y + PADDLE_HEIGHT / 2:
            return
        if self._circle_rectangle(ball, self.paddle_x - self.paddle_width / 2,
                                  self.paddle_y, self.paddle_width, PADDLE_HEIGHT) is None:
            return
        speed = max(self.starting_speed * (0.68 if self._slow_remaining > 0 else 1),
                    math.hypot(ball.vx, ball.vy))
        hit = clamp((ball.x - self.paddle_x) / (self.paddle_width / 2), -1, 1)
        ball.vx = math.sin(hit * 1.08) * speed
        # A slight center bias prevents endlessly retracing a vertical line.
        if abs(ball.vx) < 28:
            ball.vx = -28 if hit < 0 else 28
        ball.vy = -math.sqrt(max(1, speed * speed - ball.vx * ball.vx))
        ball.y = self.paddle_y - ball.radius - 0.05
        self._play("paddle")
        self._burst(ball.x, self.paddle_y, 4, 7)

    def _hit_bricks(self, ball: Ball) -> None:
        for brick in self.bricks:
            if not brick.alive:
                continue
            # Cheap broad phase keeps hundreds of micro-steps affordable.
            if (ball.x + ball.radius < brick.x or ball.x - ball.radius > brick.x + brick.width
                    or ball.y + ball.radius < brick.y or ball.y - ball.radius > brick.y + brick.height):
                continue
            contact = self._circle_rectangle(ball, brick.x, brick.y, brick.width, brick.height)
            if contact is None:
                continue
            nx, ny, penetration = contact
            inward = ball.vx * nx + ball.vy * ny
            ball.x += nx * (penetration + 0.05)
            ball.y += ny * (penetration + 0.05)
            if inward >= 0:
                continue
            ball.vx -= 2 * inward * nx
            ball.vy -= 2 * inward * ny
            self._keep_trajectory_playable(ball)
            brick.hit_points -= 1
            if brick.hit_points <= 0:
                brick.alive = False
                self.combo += 1
                self.best_combo = max(self.best_combo, self.combo)
                self._combo_remaining = 3.5
                self.score += 100 * self.level + min(self.combo - 1, 15) * 25
                self._burst(brick.x + brick.width / 2, brick.y + brick.height / 2, brick.color_index, 24)
                if self.combo >= 3:
                    self._announce("combo", 1.1)
                if self.random.random() < 0.19:
                    self.pickups.append(Pickup(brick.x + brick.width / 2, brick.y + brick.height / 2,
                                               self.random.choice(("wide", "slow", "multiball"))))
                self._play("break")
                if not self.remaining_bricks:
                    self.state = PlayState.WON
                    self.score += self.lives * 250
                    self._announce("won", 5)
                    self._play("win")
            else:
                self.score += 35
                self._burst(ball.x, ball.y, brick.color_index, 8)
                self._play("hit")
            speed = math.hypot(ball.vx, ball.vy)
            maximum = 860 * (0.68 if self._slow_remaining > 0 else 1)
            if 0 < speed < maximum:
                factor = min(maximum, speed + 5) / speed
                ball.vx *= factor
                ball.vy *= factor
            break

    @staticmethod
    def _circle_rectangle(ball: Ball, x: float, y: float, width: float,
                          height: float) -> tuple[float, float, float] | None:
        """Return the outward normal and penetration, including rounded corners."""
        dx = ball.x - clamp(ball.x, x, x + width)
        dy = ball.y - clamp(ball.y, y, y + height)
        distance_squared = dx * dx + dy * dy
        if distance_squared > ball.radius * ball.radius:
            return None
        if distance_squared > 0.000001:
            distance = math.sqrt(distance_squared)
            return dx / distance, dy / distance, ball.radius - distance
        left, right = ball.x - x, x + width - ball.x
        top, bottom = ball.y - y, y + height - ball.y
        minimum = min(left, right, top, bottom)
        if minimum == top:
            nx, ny = 0.0, -1.0
        elif minimum == bottom:
            nx, ny = 0.0, 1.0
        elif minimum == left:
            nx, ny = -1.0, 0.0
        else:
            nx, ny = 1.0, 0.0
        return nx, ny, ball.radius + minimum

    @staticmethod
    def _keep_trajectory_playable(ball: Ball) -> None:
        speed = math.hypot(ball.vx, ball.vy)
        if speed > 0 and abs(ball.vy) < speed * 0.24:
            ball.vy = (-1 if ball.vy < 0 else 1) * speed * 0.24
            ball.vx = (-1 if ball.vx < 0 else 1) * math.sqrt(speed * speed - ball.vy * ball.vy)

    def _lose_life(self) -> None:
        self.lives -= 1
        self.combo = 0
        self._combo_remaining = self._wide_remaining = self._slow_remaining = 0.0
        self.paddle_width = self.NORMAL_PADDLE_WIDTH
        self.pickups.clear()
        self._play("lose")
        if self.lives <= 0:
            self.state = PlayState.GAME_OVER
            self._announce("game_over", 6)
        else:
            self._reset_ball()
            self.state = PlayState.READY
            self._announce("life", 4)

    def _advance_effects(self, dt: float) -> None:
        self._combo_remaining = max(0.0, self._combo_remaining - dt)
        if self._combo_remaining == 0:
            self.combo = 0
        if self._wide_remaining > 0:
            self._wide_remaining = max(0.0, self._wide_remaining - dt)
            if self._wide_remaining == 0:
                self.paddle_width = self.NORMAL_PADDLE_WIDTH
                self.set_paddle(self.paddle_x)
        if self._slow_remaining > 0:
            self._slow_remaining = max(0.0, self._slow_remaining - dt)
            if self._slow_remaining == 0:
                for ball in self.balls:
                    ball.vx /= 0.68
                    ball.vy /= 0.68

    def _advance_pickups(self, dt: float) -> None:
        for pickup in self.pickups[:]:
            pickup.y += 170 * dt
            if (pickup.y + 14 >= self.paddle_y and pickup.y - 14 <= self.paddle_y + PADDLE_HEIGHT
                    and abs(pickup.x - self.paddle_x) <= self.paddle_width / 2 + 14):
                self._apply_pickup(pickup.kind)
                self.pickups.remove(pickup)
            elif pickup.y > ARENA_BOTTOM + 24:
                self.pickups.remove(pickup)

    def _apply_pickup(self, kind: str) -> None:
        if kind == "wide":
            self._wide_remaining = 14.0
            self.paddle_width = 236.0
            self.set_paddle(self.paddle_x)
            self._announce("wide", 2)
        elif kind == "slow":
            if self._slow_remaining <= 0:
                for ball in self.balls:
                    ball.vx *= 0.68
                    ball.vy *= 0.68
            self._slow_remaining = 10.0
            self._announce("slow", 2)
        elif kind == "multiball" and self.balls:
            original = self.balls[0]
            for direction in (-1, 1):
                if len(self.balls) >= 5:
                    break
                angle = 0.38 * direction
                cosine, sine = math.cos(angle), math.sin(angle)
                ball = Ball(original.x, original.y,
                            original.vx * cosine - original.vy * sine,
                            original.vx * sine + original.vy * cosine)
                self._keep_trajectory_playable(ball)
                self.balls.append(ball)
            self._announce("multiball", 2)
        else:
            return
        self.score += 50
        self._play("powerup")

    def _announce(self, code: str, seconds: float) -> None:
        self.notice_code = code
        self.notice_time = float(seconds)

    def _play(self, name: str) -> None:
        if self.sound is not None:
            self.sound(name)

    def _burst(self, x: float, y: float, color: int, count: int) -> None:
        for _ in range(count):
            angle = self.random.random() * math.tau
            speed = 70 + self.random.random() * 240
            life = 0.35 + self.random.random() * 0.45
            self.particles.append(Particle(x, y, math.cos(angle) * speed,
                                           math.sin(angle) * speed, life, life, color))
        del self.particles[:-600]

    def _advance_particles(self, dt: float) -> None:
        for particle in self.particles:
            particle.life -= dt
            particle.x += particle.vx * dt
            particle.y += particle.vy * dt
            particle.vy += 190 * dt
        self.particles = [particle for particle in self.particles if particle.life > 0]
