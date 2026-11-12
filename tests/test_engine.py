"""Rule and gameplay regression tests; no display or third-party GUI required."""

import math

import pytest

from desktop_breakout.engine import (
    ARENA_LEFT, ARENA_RIGHT, Ball, Brick, GameEngine, Pickup, PlayState, build_level,
)


def make_game():
    game = GameEngine(42)
    game.start([Brick(500, 300, 100, 40)])
    return game


def test_fast_ball_cannot_tunnel_through_thin_brick():
    game = make_game()
    game.start([Brick(500, 300, 100, 4), Brick(800, 300, 100, 40)])
    game.launch()
    ball = game.balls[0]
    ball.x, ball.y, ball.vx, ball.vy = 550, 400, 0, -5000
    game.update(0.03)
    assert not game.bricks[0].alive
    assert ball.vy > 0
    assert game.remaining_bricks == 1


def test_last_brick_wins_and_bonus_is_awarded_once():
    game = make_game()
    game.launch()
    ball = game.balls[0]
    ball.x, ball.y, ball.vx, ball.vy = 550, 360, 0, -600
    game.update(0.04)
    assert game.state == PlayState.WON
    assert game.remaining_bricks == 0
    assert game.score == 100 + 3 * 250
    game.update(0.1)
    assert game.score == 850


def test_three_misses_exhaust_three_lives():
    game = make_game()
    for expected_lives in (2, 1, 0):
        game.launch()
        ball = game.balls[0]
        ball.x, ball.y, ball.vx, ball.vy = 50, 920, 0, 500
        game.update(0.02)
        assert game.lives == expected_lives
        assert game.state == (PlayState.READY if expected_lives else PlayState.GAME_OVER)


def test_pause_freezes_balls_paddle_effects_and_clock():
    game = make_game()
    game.launch()
    game.pickups.append(Pickup(game.paddle_x, 815, "wide"))
    game.update(0.02)
    game.toggle_pause()
    before = (game.balls[0].x, game.balls[0].y, game.paddle_x,
              game.elapsed, game.active_effect, game.notice_time)
    game.update(1)
    game.set_paddle(300)
    assert before == (game.balls[0].x, game.balls[0].y, game.paddle_x,
                      game.elapsed, game.active_effect, game.notice_time)
    game.toggle_pause()
    assert game.state == PlayState.PLAYING


def test_paddle_clamps_and_ready_ball_follows():
    game = make_game()
    game.set_paddle(-500)
    assert game.paddle_x - game.paddle_width / 2 == ARENA_LEFT
    assert game.balls[0].x == game.paddle_x
    game.set_paddle(9000)
    assert game.paddle_x + game.paddle_width / 2 == ARENA_RIGHT


def test_paddle_edge_changes_return_angle():
    game = make_game()
    game.launch()
    ball = game.balls[0]
    ball.x, ball.y, ball.vx, ball.vy = game.paddle_x + 50, 800, 0, 800
    game.update(0.05)
    assert ball.vy < 0
    assert ball.vx > 0
    assert game.lives == 3


def test_multiball_does_not_charge_life_until_all_balls_are_lost():
    game = make_game()
    game.launch()
    game.balls.append(Ball(70, 920, vy=500))
    game.update(0.02)
    assert game.lives == 3
    assert len(game.balls) == 1


def test_caught_powerups_apply_expire_and_do_not_stack_slow_multiplier():
    game = make_game()
    game.launch()
    game.pickups.append(Pickup(game.paddle_x, 815, "wide"))
    game.update(0.01)
    assert game.paddle_width > 200
    game.pickups.append(Pickup(game.paddle_x, 815, "multiball"))
    game.update(0.01)
    assert len(game.balls) == 3
    game.pickups.append(Pickup(game.paddle_x, 815, "slow"))
    game.update(0.01)
    initial_speed = math.hypot(game.balls[0].vx, game.balls[0].vy)
    game.pickups.append(Pickup(game.paddle_x, 815, "slow"))
    game.update(0.01)
    assert math.hypot(game.balls[0].vx, game.balls[0].vy) == pytest.approx(initial_speed)
    for ball in game.balls:
        ball.x, ball.y, ball.vx, ball.vy = 1200, 500, 0, 0
    for _ in range(142):
        game.update(0.1)
    assert game.paddle_width < 200
    assert "慢速" not in game.active_effect


def test_new_level_keeps_score_and_lives_but_restart_resets_them():
    game = make_game()
    game.launch()
    ball = game.balls[0]
    ball.x, ball.y, ball.vx, ball.vy = 550, 360, 0, -600
    game.update(0.04)
    score = game.score
    game.start([Brick(500, 300, 100, 40)], 2, False)
    assert (game.score, game.lives, game.level, game.state) == (score, 3, 2, PlayState.READY)
    game.start(build_level(4), reset_score=True)
    assert (game.score, game.lives, game.best_combo) == (0, 3, 0)


def test_corner_collision_reflects_and_separates_without_double_scoring():
    game = make_game()
    game.start([Brick(500, 300, 100, 40, hit_points=2), Brick(800, 300, 100, 40)])
    game.launch()
    ball = game.balls[0]
    ball.x, ball.y, ball.vx, ball.vy = 485, 285, 200, 200
    game.update(0.05)
    assert ball.vx < 0 and ball.vy < 0
    assert game.bricks[0].hit_points == 1
    assert game.score == 35


def test_empty_icon_library_never_creates_fake_icons():
    assert build_level(0) == []
    bricks = build_level(2)
    assert len(bricks) == 48
    assert {brick.icon_index for brick in bricks} == {0, 1}
    assert len(build_level(2, unique=True)) == 2


def test_invalid_time_and_paddle_inputs_do_not_corrupt_game():
    game = make_game()
    game.launch()
    before = (game.balls[0].x, game.balls[0].y, game.paddle_x, game.elapsed)
    for invalid in (float("nan"), float("inf"), -1, 0):
        game.update(invalid)
    game.set_paddle(float("nan"))
    assert before == (game.balls[0].x, game.balls[0].y, game.paddle_x, game.elapsed)


def aim_at_bricks(game):
    """Test player predicts a wall-folded landing and aims at a remaining brick."""
    descending = [ball for ball in game.balls if ball.vy > 0]
    if not descending:
        return
    ball = min(descending, key=lambda b: (game.paddle_y - b.radius - b.y) / b.vy)
    if ball.y >= game.paddle_y:
        return
    until_hit = max(0, (game.paddle_y - ball.radius - ball.y) / ball.vy)
    low, high = ARENA_LEFT + ball.radius, ARENA_RIGHT - ball.radius
    width = high - low
    folded = (ball.x + ball.vx * until_hit - low) % (2 * width)
    hit_x = low + (folded if folded <= width else 2 * width - folded)
    target = min((b for b in game.bricks if b.alive),
                 key=lambda b: abs(b.x + b.width / 2 - hit_x), default=None)
    angle = 0 if target is None else math.atan2(
        target.x + target.width / 2 - hit_x, game.paddle_y - target.y - target.height / 2)
    angle = max(-1, min(1, angle))
    game.set_paddle(hit_x - angle / 1.08 * (game.paddle_width / 2))


@pytest.mark.parametrize("level", (1, 3, 5, 7))
@pytest.mark.parametrize("seed", range(1, 11))
def test_complete_level_with_deterministic_player(level, seed):
    game = GameEngine(seed)
    game.start(build_level(16, level), level)
    dt = 1 / 120
    for _ in range(120 * 600):
        if game.state in (PlayState.WON, PlayState.GAME_OVER):
            break
        if game.state == PlayState.READY:
            game.launch()
        aim_at_bricks(game)
        game.update(dt)
        assert all(math.isfinite(v) for ball in game.balls for v in (ball.x, ball.y, ball.vx, ball.vy))
    assert game.state == PlayState.WON, (game.state, game.remaining_bricks, game.lives)
    assert game.lives > 0
