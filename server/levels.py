"""Player levels: score an attempt, nudge the level, and choose which grade to serve next.

A level is a decimal 1.0-9.0 per player, mode and hands setting, on the same scale as
excerpt grades. One-hand practice has its own levels so easy drills don't inflate the
hands-together level.

Players should get about TARGET of each excerpt right; doing better moves the level up,
doing worse moves it down. Steps are small so one bad run doesn't undo a week.

The whole part of a level is a grade and the fraction is how far through that grade's
difficulty range to aim: level 1.0 gets the easiest grade-1 material (generated
exercises), 1.9 the hardest grade-1 pieces.
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
EASIEST = 0.8  # difficulty of the easiest generated exercises, the bottom of grade 1
HARDEST_BAND = 6.0  # grade 9 has no upper cutoff; treat it as this wide
JITTER = 0.2  # how far either side of the level a pick may aim


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


def pick_target(level: float, rng: random.Random | None = None) -> tuple[list[int], float]:
    """Where to aim next: (grades to search, best first; difficulty score to get closest to).

    The level is nudged by up to JITTER either way for variety, so a 1.9 sometimes gets an
    easy grade-2 piece and a 1.0 a slightly easier or harder exercise, never a big jump.
    """
    rng = rng or random.Random()
    aim = max(MIN_LEVEL, min(MAX_LEVEL + 0.99, level + rng.uniform(-JITTER, JITTER)))
    grade = max(1, min(9, int(aim)))
    grades = sorted(range(1, 10), key=lambda g: (abs(g - grade), g))  # nearest grades as fallbacks
    return grades, aim


def target_difficulty(level: float, grade: int, cutoffs: tuple[float, ...]) -> float:
    """The difficulty score to aim for: `level`'s position within its grade, or, when falling
    back to another grade, that grade's edge nearest the level."""
    lo = cutoffs[grade - 2] if grade > 1 else EASIEST
    hi = cutoffs[grade - 1] if grade <= len(cutoffs) else cutoffs[-1] + HARDEST_BAND
    frac = level - grade if int(level) == grade else (0.0 if grade > level else 1.0)
    return lo + max(0.0, min(1.0, frac)) * (hi - lo)
