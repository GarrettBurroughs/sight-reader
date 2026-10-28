"""Difficulty features for a run of measures, a raw difficulty score, and a grade 1-9.

The score is a hand-tuned weighted sum. Grades cut it at fixed points chosen so that
well-known pieces land near their usual Henle level (see anchors.py). Staff 1 is the
right hand, staff 2 the left.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections import defaultdict

from musicxml import Measure

MAJOR_SCALE = (0, 2, 4, 5, 7, 9, 11)
DEFAULT_TEMPO = 100.0
# Difficulty at which each grade from 2 to 9 starts, fitted to anchors (median excerpt score):
# Ode to Joy 4.0, Minuet in G 4.9, Gymnopedie 1 6.0, Clementi op. 36/1 6.4, Mozart K545 8.8,
# Bach Invention 1 9.0, Bach Prelude in C 9.3, Moonlight 11.5, Chopin Etudes op. 10 13.2,
# La Campanella 17.3. The hard end is compressed: grades 6-8 are narrow bands.
GRADE_CUTOFFS = (4.5, 5.8, 7.8, 10.0, 11.8, 12.4, 13.0, 15.5)


def key_pitch_classes(fifths: int) -> set[int]:
    tonic = (7 * fifths) % 12
    return {(tonic + s) % 12 for s in MAJOR_SCALE}


def ledger(midi: int, clef: tuple[str, int]) -> bool:
    """Roughly: does this note need ledger lines on its staff?"""
    if clef[0] == "F":
        return midi < 41 or midi > 59  # below F2 / above B3
    return midi < 62 or midi > 79  # treble: below D4 / above G5


def compute(measures: list[Measure]) -> dict:
    a0 = measures[0].attrs
    beat_len = 4 / a0.beat_type
    if a0.beat_type == 8 and a0.beats % 3 == 0 and a0.beats > 3:
        beat_len = 1.5  # compound meter: dotted-quarter beats
    in_key = key_pitch_classes(a0.fifths)

    quarters = 0.0
    onsets: dict[int, dict[float, list[int]]] = {1: defaultdict(list), 2: defaultdict(list)}
    durations: list[float] = []
    voices: dict[int, set[str]] = {1: set(), 2: set()}
    out_of_key = ledgers = played = 0
    flags: set[str] = set()
    tempos = [m.tempo for m in measures if m.tempo]
    bar_rhythms = set()
    lengths: dict[float, float] = {}  # onset -> longest note starting there

    for m in measures:
        flags |= m.flags
        # Each bar's rhythm, both hands: where notes start within the bar.
        bar_rhythms.add(
            tuple(tuple(sorted({round(n.onset, 4) for n in m.notes if n.played and (n.staff == 1) == rh})) for rh in (True, False))
        )
        for n in m.notes:
            if not n.played:
                continue
            staff = 1 if n.staff == 1 else 2
            t = round(quarters + n.onset, 4)
            onsets[staff][t].append(n.midi)
            lengths[t] = max(lengths.get(t, 0.0), n.duration)
            voices[staff].add(n.voice)
            durations.append(n.duration)
            played += 1
            if n.midi % 12 not in in_key:
                out_of_key += 1
            if ledger(n.midi, m.attrs.clefs.get(n.staff, ("G", 2))):
                ledgers += 1
        quarters += m.attrs.bar_length

    bars = len(measures)
    hand = {}
    for staff in (1, 2):
        times = sorted(onsets[staff])
        chords = [sorted(onsets[staff][t]) for t in times]
        # The melody line a hand follows: top note in the right hand, bottom in the left.
        line = [c[-1] if staff == 1 else c[0] for c in chords]
        leaps = sorted(abs(b - a) for a, b in zip(line, line[1:]))
        pitches = [p for c in chords for p in c]
        hand[staff] = {
            "notes": len(pitches),
            "onsets": len(times),
            "chord_ratio": sum(len(c) > 1 for c in chords) / len(chords) if chords else 0.0,
            "max_chord": max((len(c) for c in chords), default=0),
            "max_span": max((c[-1] - c[0] for c in chords), default=0),
            "range": (max(pitches) - min(pitches)) if pitches else 0,
            "leap_p90": leaps[int(0.9 * (len(leaps) - 1))] if leaps else 0,
            "max_leap": leaps[-1] if leaps else 0,
            "voices": len(voices[staff]),
        }

    rh_times, lh_times = set(onsets[1]), set(onsets[2])
    all_times = rh_times | lh_times
    # Syncopation: a note that starts off the beat and is held across the next beat.
    syncopated = sum(
        1 for t in all_times if not _on_grid(t, beat_len) and t + lengths[t] > (math.floor(t / beat_len) + 1) * beat_len + 1e-6
    )
    shortest = min((d for d in durations if d > 0), default=1.0)
    tempo = tempos[0] if tempos else None

    return {
        "bars": bars,
        "beats": a0.beats,
        "beat_type": a0.beat_type,
        "key_fifths": a0.fifths,
        "tempo": tempo,
        "notes": played,
        "notes_per_quarter": played / quarters if quarters else 0.0,
        "onsets_per_quarter": len(all_times) / quarters if quarters else 0.0,
        "lh_notes_per_quarter": hand[2]["notes"] / quarters if quarters else 0.0,
        "rh": hand[1],
        "lh": hand[2],
        "independence": 1 - len(rh_times & lh_times) / len(all_times) if all_times else 0.0,
        "rhythm_variety": len(bar_rhythms) / bars,  # 1/bars when every bar has the same rhythm
        "shortest": shortest,
        "syncopation": syncopated / len(all_times) if all_times else 0.0,
        "out_of_key_per_bar": out_of_key / bars,
        "ledger_ratio": ledgers / played if played else 0.0,
        "tuplets": "tuplet" in flags,
        "clef_changes": "clef-change" in flags,
        "octave_shifts": "octave-shift" in flags,
        "rest_bars": sum(1 for m in measures if not any(n.played for n in m.notes)),
    }


def _on_grid(t: float, step: float) -> bool:
    r = (t / step) % 1
    return r < 1e-3 or r > 1 - 1e-3


def grade(difficulty: float) -> int:
    return 1 + bisect_right(GRADE_CUTOFFS, difficulty)


def difficulty(f: dict) -> float:
    """Raw difficulty: bigger is harder."""
    return round(sum(difficulty_terms(f).values()), 4)


def difficulty_terms(f: dict) -> dict[str, float]:
    """What difficulty() adds up, by name, for tuning."""
    tempo_factor = min(1.6, max(0.6, (f["tempo"] or DEFAULT_TEMPO) / DEFAULT_TEMPO))
    rh, lh = f["rh"], f["lh"]
    # Notes in a rhythm that repeats bar after bar (Alberti bass, broken chords) read far
    # more easily than the same number of notes in changing rhythms.
    pattern_factor = 0.55 + 0.45 * f["rhythm_variety"]
    return {
        "density": 1.2 * f["onsets_per_quarter"] * tempo_factor * pattern_factor,  # how busy the music is
        "left_hand": 0.6 * f["lh_notes_per_quarter"] * tempo_factor * pattern_factor,  # a busy left hand
        "chords": 1.2 * (rh["chord_ratio"] + lh["chord_ratio"]),  # chords to read
        "big_chords": 0.4 * max(0, max(rh["max_chord"], lh["max_chord"]) - 2),
        "stretch": 0.08 * max(0, max(rh["max_span"], lh["max_span"]) - 7),  # beyond a fifth
        "leaps": 0.05 * (rh["leap_p90"] + lh["leap_p90"]),  # jumping around
        "range": 0.02 * max(0, max(rh["range"], lh["range"]) - 12),  # moving out of position
        "short_notes": 0.6 * max(0.0, math.log2(1 / f["shortest"])),  # 8ths -> 0.6, 16ths -> 1.2
        "syncopation": 3.0 * f["syncopation"],
        "tuplets": 0.5 * f["tuplets"],
        "accidentals": 0.5 * min(4.0, f["out_of_key_per_bar"]),
        "key": 0.15 * abs(f["key_fifths"]) + 0.35 * max(0, abs(f["key_fifths"]) - 3),  # 4+ sharps/flats get hard fast
        "ledger": 1.5 * f["ledger_ratio"],
        "voices": 0.6 * (max(rh["voices"], lh["voices"]) > 1),  # several voices in one hand
        "independence": 0.3 * f["independence"],
        "clefs_ottava": 0.3 * f["clef_changes"] + 0.3 * f["octave_shifts"],
    }
