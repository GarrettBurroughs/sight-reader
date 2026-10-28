"""Player levels: score an attempt, nudge the level, and choose which grade to serve next.

A level is a decimal 1.0-9.0 per player, mode and hands setting, on the same scale as
excerpt grades. One-hand practice has its own levels so easy drills don't inflate the
hands-together level.

Players should get about TARGET of each excerpt right; doing better moves the level up,
doing worse moves it down. Steps are small so one bad run doesn't undo a week.
"""

from __future__ import annotations

import random

MODES = ("wait", "tempo")
HANDS = ("both", "right", "left")
START_LEVEL = 2.0
ONE_HAND_HEAD_START = 1.0  # a new one-hand level starts this far above the hands-together one
MIN_LEVEL, MAX_LEVEL = 1.0, 9.0
TARGET = 0.85  # performance that keeps the level where it is
GAIN = 2.0  # level change per unit of performance above/below target
MAX_UP, MAX_DOWN = 0.3, 0.5  # per attempt


def level_key(mode: str, hands: str = "both") -> str:
    """How a level is stored: "wait", "tempo", "wait:left", "tempo:right"..."""
    return mode if hands == "both" else f"{mode}:{hands}"


LEVEL_KEYS = tuple(level_key(m, h) for m in MODES for h in HANDS)


def performance(mode: str, *, steps: int | None = None, wrong: int = 0, note_pct: float | None = None,
                timing_pct: float | None = None) -> float:
    """0-1. Wait mode: share of key presses that were right. Tempo: notes weighted over timing."""
    if mode == "wait":
        steps = steps or 0
        return steps / (steps + wrong) if steps + wrong else 0.0
    return 0.6 * (note_pct or 0) / 100 + 0.4 * (timing_pct or 0) / 100


def update(level: float, perf: float, grade: int) -> float:
    """New level after an attempt at an excerpt of `grade`."""
    delta = max(-MAX_DOWN, min(MAX_UP, GAIN * (perf - TARGET)))
    # Acing something well below your level, or struggling with something well above it,
    # says less about you than the reverse.
    if (delta > 0 and grade < level - 0.5) or (delta < 0 and grade > level + 0.5):
        delta *= 0.5
    return round(max(MIN_LEVEL, min(MAX_LEVEL, level + delta)), 2)


def grade_preference(level: float, rng: random.Random | None = None) -> list[int]:
    """Grades to try, best first: usually the level's own grade, sometimes one either side."""
    rng = rng or random.Random()
    base = max(1, min(9, round(level)))
    roll = rng.random()
    first = base - 1 if roll < 0.15 else base + 1 if roll < 0.30 else base
    first = max(1, min(9, first))
    return sorted(range(1, 10), key=lambda g: (g != first, abs(g - first), g))
