"""Generate graded beginner sight-reading exercises (8 bars, both staves).

    python3 generate.py [--per-stage 250] [--out DIR]     # writes .mxl files and prints the grade spread

catalog.py calls build() so the exercises land in the library next to the PDMX excerpts.
Each exercise follows a harmony plan (I/IV/V), phrases as 4 + 4 bars with the opening
often repeated, stays in a five-finger position with the starting finger marked, and
ends on the tonic. Stages add one idea at a time; see STAGES.
"""

from __future__ import annotations

import argparse
import random
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

LETTERS = "CDEFGAB"
NATURAL = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
SCALES = {"major": (0, 2, 4, 5, 7, 9, 11), "minor": (0, 2, 3, 5, 7, 8, 10)}  # natural minor
# Key name -> (tonic letter, tonic pitch class, fifths, scale)
KEYS = {
    "C": ("C", 0, 0, "major"),
    "G": ("G", 7, 1, "major"),
    "F": ("F", 5, -1, "major"),
    "D": ("D", 2, 2, "major"),
    "Bb": ("B", 10, -2, "major"),
    "Am": ("A", 9, 0, "minor"),
    "Dm": ("D", 2, -1, "minor"),
    "Em": ("E", 4, 1, "minor"),
}
CHORDS = {"I": (0, 2, 4), "IV": (3, 5, 0), "V": (4, 6, 1)}  # scale degrees (i/iv/v in minor)
PLANS = [
    ["I", "I", "V", "I", "I", "IV", "V", "I"],
    ["I", "V", "I", "V", "I", "IV", "V", "I"],
    ["I", "IV", "I", "V", "I", "IV", "V", "I"],
    ["I", "I", "IV", "V", "I", "IV", "V", "I"],
]
TYPES = {0.5: ("eighth", False), 1: ("quarter", False), 1.5: ("quarter", True), 2: ("half", False), 3: ("half", True), 4: ("whole", False)}

# One-bar rhythm cells per meter, in quarter notes; negative = rest.
BASIC = {
    4: [[4], [2, 2], [2, 1, 1], [1, 1, 2], [1, 1, 1, 1], [3, 1]],
    3: [[3], [2, 1], [1, 2], [1, 1, 1]],
    2: [[2], [1, 1]],
}
WITH_RESTS = {4: [[1, 1, 1, -1], [2, 1, -1], [-1, 1, 2]], 3: [[2, -1], [1, 1, -1]], 2: [[1, -1]]}
EIGHTHS = {
    4: [[0.5, 0.5, 1, 2], [1, 0.5, 0.5, 2], [1.5, 0.5, 2], [1, 1, 0.5, 0.5, 1], [1.5, 0.5, 1, 1]],
    3: [[0.5, 0.5, 1, 1], [1.5, 0.5, 1], [1, 0.5, 0.5, 1]],
    2: [[0.5, 0.5, 1], [1.5, 0.5]],
}


@dataclass(frozen=True)
class Stage:
    number: int
    name: str
    keys: tuple[str, ...]
    meters: tuple[int, ...]  # beats per bar, x/4
    leaps: tuple[int, ...]  # allowed melodic moves in scale steps
    texture: str  # "turns", "held", "moving", "fifths"
    rests: bool = False
    eighths: bool = False
    tempo: int = 72


STAGES = [
    Stage(1, "Hands take turns, steps", ("C",), (4,), (0, 1), "turns", tempo=66),
    Stage(2, "Hands take turns, skips", ("C", "G"), (4, 3), (0, 1, 2), "turns", rests=True, tempo=72),
    Stage(3, "Melody over held notes", ("C", "G", "F"), (4, 3), (0, 1, 2), "held", tempo=72),
    Stage(4, "Moving left hand", ("C", "G", "F", "D", "Am"), (4, 3, 2), (0, 1, 2, 3), "moving", rests=True, tempo=76),
    Stage(5, "Eighth notes and dotted rhythms", ("C", "G", "F", "D", "Am", "Dm"), (4, 3, 2), (0, 1, 2, 3), "moving", eighths=True, tempo=80),
    Stage(6, "Two-note left hand", ("C", "G", "F", "D", "Bb", "Am", "Dm", "Em"), (4, 3), (0, 1, 2, 3, 4), "fifths", rests=True, eighths=True, tempo=80),
]


@dataclass
class Event:
    dur: float  # quarters
    degrees: tuple[int, ...] = ()  # empty = rest
    finger: int | None = None


class Key:
    def __init__(self, name: str):
        self.name = name
        self.letter, self.tonic_pc, self.fifths, self.mode = KEYS[name]
        self.scale = SCALES[self.mode]

    def pitch(self, degree: int, tonic_octave: int) -> tuple[str, int, int, int]:
        """(step, alter, octave, midi) of a scale degree counted from the tonic in tonic_octave."""
        letter_index = LETTERS.index(self.letter) + degree
        step = LETTERS[letter_index % 7]
        octave = tonic_octave + letter_index // 7
        midi = 12 * (tonic_octave + 1) + self.tonic_pc + self.scale[degree % 7] + 12 * (degree // 7)
        alter = midi - (12 * (octave + 1) + NATURAL[step])
        return step, alter, octave, midi

    def label(self) -> str:
        return f"{self.name[0]}{'♭' if 'b' in self.name else ''} {self.mode}"


def hand_octaves(key: Key) -> tuple[int, int]:
    """Tonic octaves for each hand's five-finger position, kept on or near the staff."""
    rh = 4
    lh = 3 if key.tonic_pc <= 4 else 2  # C3/D3/E3 positions, else F2..B2
    return rh, lh


def generate(stage: Stage, seed: int) -> tuple[ET.Element, str, Key]:
    """One exercise as a MusicXML score, with its title and key."""
    rng = random.Random(seed)
    key = Key(rng.choice(stage.keys))
    beats = rng.choice(stage.meters)
    plan = rng.choice(PLANS)

    rh_bars, lh_bars = [], []
    melody_hands = ["rh", "rh", "lh", "lh", "rh", "rh", "lh", "rh"] if stage.texture == "turns" else ["rh"] * 8
    if stage.texture == "turns" and rng.random() < 0.5:
        melody_hands = ["lh" if h == "rh" else "rh" for h in melody_hands[:7]] + ["rh"]

    prev = {"rh": rng.choice([0, 2, 4]), "lh": rng.choice([0, 2, 4])}
    for bar in range(8):
        chord = CHORDS[plan[bar]]
        last = bar == 7
        half_cadence = bar == 3
        hand = melody_hands[bar]
        melody = melody_bar(stage, beats, chord, prev, hand, last, half_cadence, rng)
        if stage.texture == "turns":
            rest = [Event(beats)]
            rh_bars.append(melody if hand == "rh" else rest)
            lh_bars.append(melody if hand == "lh" else rest)
        else:
            rh_bars.append(melody)
            lh_bars.append(accompaniment(stage, beats, plan[bar], last, rng))

    # Antecedent/consequent: often restate the opening two bars in bars 5-6.
    if rng.random() < 0.6:
        rh_bars[4:6] = [copy_bar(b) for b in rh_bars[0:2]]
        if stage.texture == "turns":
            lh_bars[4:6] = [copy_bar(b) for b in lh_bars[0:2]]

    mark_first_finger(rh_bars, "rh")
    mark_first_finger(lh_bars, "lh")
    title = f"Exercise {stage.number}.{seed % 10000}: {stage.name} ({key.label()})"
    return to_musicxml(key, beats, stage.tempo, rh_bars, lh_bars, title), title, key


def copy_bar(bar: list[Event]) -> list[Event]:
    """Fresh events, so marking a finger on the original doesn't mark the copy."""
    return [Event(e.dur, e.degrees) for e in bar]


def melody_bar(stage: Stage, beats: int, chord: tuple[int, ...], prev: dict, hand: str, last: bool,
               half_cadence: bool, rng: random.Random) -> list[Event]:
    if last:
        prev[hand] = 0
        return [Event(beats, (0,))]
    cells = list(BASIC[beats])
    if stage.rests:
        cells += WITH_RESTS[beats]
    if stage.eighths:
        cells += EIGHTHS[beats] * 2
    cell = rng.choice(cells)
    events = []
    for i, dur in enumerate(cell):
        if dur < 0:
            events.append(Event(-dur))
            continue
        cur = prev[hand]
        if i == 0:
            # Strong beat: a chord tone in the position, close to where the hand is.
            options = [d for d in range(0, 5) if d % 7 in chord] or [cur]
            target = min(options, key=lambda d: (abs(d - cur) > max(stage.leaps), rng.random()))
        elif half_cadence and i == len(cell) - 1:
            target = rng.choice([1, 4])  # end the first phrase on the dominant
        else:
            move = rng.choice([m for m in stage.leaps for _ in range(3 if m == 1 else 1)])  # mostly steps
            target = cur + rng.choice([-1, 1]) * move
            if not 0 <= target <= 4:
                target = cur - (target - cur)
            target = max(0, min(4, target))
        prev[hand] = target
        events.append(Event(dur, (target,)))
    return events


def accompaniment(stage: Stage, beats: int, chord_name: str, last: bool, rng: random.Random) -> list[Event]:
    """Left hand in a five-finger position: degrees 0-4 above the LH tonic."""
    root = {"I": 0, "IV": 3, "V": 4}[chord_name]
    fifth = {"I": 4, "IV": 0, "V": 1}[chord_name]  # the other chord tone that fits the position
    if last:
        return [Event(beats, (0, 4) if stage.texture == "fifths" else (0,))]
    if stage.texture == "held":
        return [Event(beats, (root,))]
    if stage.texture == "fifths":
        pair = tuple(sorted({root, fifth}))
        return [Event(beats, pair)] if beats == 3 or rng.random() < 0.5 else [Event(2, pair), Event(2, pair)]
    # "moving": a simple pattern on chord tones
    patterns = {
        4: [[(2, root), (2, fifth)], [(1, root), (1, fifth), (2, root)], [(4, root)], [(1, root), (1, fifth), (1, root), (1, fifth)]],
        3: [[(2, root), (1, fifth)], [(1, root), (1, fifth), (1, fifth)], [(3, root)]],
        2: [[(1, root), (1, fifth)], [(2, root)]],
    }
    return [Event(d, (deg,)) for d, deg in rng.choice(patterns[beats])]


def mark_first_finger(bars: list[list[Event]], hand: str) -> None:
    """Show which finger starts, so the hand position is clear (RH thumb / LH fifth finger on degree 0)."""
    for bar in bars:
        for e in bar:
            if e.degrees:
                d = e.degrees[0]
                e.finger = d + 1 if hand == "rh" else 5 - d
                return


def to_musicxml(key: Key, beats: int, tempo: int, rh: list[list[Event]], lh: list[list[Event]], title: str) -> ET.Element:
    rh_oct, lh_oct = hand_octaves(key)
    root = ET.Element("score-partwise", version="4.0")
    ET.SubElement(ET.SubElement(root, "work"), "work-title").text = title
    ident = ET.SubElement(root, "identification")
    ET.SubElement(ident, "creator", type="composer").text = "Generated exercise"
    part_list = ET.SubElement(root, "part-list")
    ET.SubElement(ET.SubElement(part_list, "score-part", id="P1"), "part-name").text = "Piano"
    part = ET.SubElement(root, "part", id="P1")

    for i in range(8):
        m = ET.SubElement(part, "measure", number=str(i + 1))
        if i == 0:
            attrs = ET.SubElement(m, "attributes")
            ET.SubElement(attrs, "divisions").text = "2"
            k = ET.SubElement(attrs, "key")
            ET.SubElement(k, "fifths").text = str(key.fifths)
            ET.SubElement(k, "mode").text = key.mode
            t = ET.SubElement(attrs, "time")
            ET.SubElement(t, "beats").text = str(beats)
            ET.SubElement(t, "beat-type").text = "4"
            ET.SubElement(attrs, "staves").text = "2"
            for n, (sign, line) in ((1, ("G", "2")), (2, ("F", "4"))):
                clef = ET.SubElement(attrs, "clef", number=str(n))
                ET.SubElement(clef, "sign").text = sign
                ET.SubElement(clef, "line").text = line
            d = ET.SubElement(m, "direction", placement="above")
            met = ET.SubElement(ET.SubElement(d, "direction-type"), "metronome")
            ET.SubElement(met, "beat-unit").text = "quarter"
            ET.SubElement(met, "per-minute").text = str(tempo)
            ET.SubElement(d, "staff").text = "1"
            ET.SubElement(d, "sound", tempo=str(tempo))
        write_voice(m, key, rh[i], rh_oct, staff=1, voice=1, beats=beats)
        ET.SubElement(ET.SubElement(m, "backup"), "duration").text = str(beats * 2)
        write_voice(m, key, lh[i], lh_oct, staff=2, voice=5, beats=beats)
        if i == 7:
            ET.SubElement(ET.SubElement(m, "barline", location="right"), "bar-style").text = "light-heavy"
    return root


def write_voice(m: ET.Element, key: Key, events: list[Event], tonic_octave: int, staff: int, voice: int, beats: int) -> None:
    pos = 0.0
    for idx, e in enumerate(events):
        whole_bar_rest = not e.degrees and e.dur == beats and len(events) == 1
        beam = _beam(events, idx, pos)
        for j, degree in enumerate(e.degrees or (None,)):
            n = ET.SubElement(m, "note")
            if j:
                ET.SubElement(n, "chord")
            if degree is None:
                ET.SubElement(n, "rest", measure="yes") if whole_bar_rest else ET.SubElement(n, "rest")
            else:
                step, alter, octave, _ = key.pitch(degree, tonic_octave)
                p = ET.SubElement(n, "pitch")
                ET.SubElement(p, "step").text = step
                if alter:
                    ET.SubElement(p, "alter").text = str(alter)
                ET.SubElement(p, "octave").text = str(octave)
            ET.SubElement(n, "duration").text = str(int(e.dur * 2))
            ET.SubElement(n, "voice").text = str(voice)
            if not whole_bar_rest:
                typ, dotted = TYPES[e.dur]
                ET.SubElement(n, "type").text = typ
                if dotted:
                    ET.SubElement(n, "dot")
            ET.SubElement(n, "staff").text = str(staff)
            if beam and j == 0:
                ET.SubElement(n, "beam", number="1").text = beam
            if e.finger and j == 0:
                technical = ET.SubElement(ET.SubElement(n, "notations"), "technical")
                ET.SubElement(technical, "fingering").text = str(e.finger)
        pos += e.dur


def _beam(events: list[Event], idx: int, pos: float) -> str | None:
    """Beam two eighths that share a beat."""
    e = events[idx]
    if e.dur != 0.5 or not e.degrees:
        return None
    if pos % 1 == 0 and idx + 1 < len(events) and events[idx + 1].dur == 0.5 and events[idx + 1].degrees:
        return "begin"
    if pos % 1 == 0.5 and idx > 0 and events[idx - 1].dur == 0.5 and events[idx - 1].degrees:
        return "end"
    return None


def build(out_dir: Path, per_stage: int = 250) -> list[tuple[str, str, Stage, Path]]:
    """Write every exercise under out_dir/exercises/. Returns (id, title, stage, path) per exercise."""
    from musicxml import write_mxl

    made = []
    for stage in STAGES:
        folder = out_dir / "exercises" / f"stage{stage.number}"
        folder.mkdir(parents=True, exist_ok=True)
        for n in range(per_stage):
            seed = stage.number * 100_000 + n
            root, title, _ = generate(stage, seed)
            ex_id = f"gen-{stage.number}-{n:04d}"
            path = folder / f"{ex_id}.mxl"
            write_mxl(root, str(path))
            made.append((ex_id, title, stage, path))
    return made


def main() -> None:
    import features
    from musicxml import parse, read_mxl

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--per-stage", type=int, default=250)
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "data" / "exercises-preview")
    args = ap.parse_args()
    spread: dict[int, dict[int, int]] = {}
    for _, _, stage, path in build(args.out, args.per_stage):
        f = features.compute(parse(read_mxl(str(path))).measures)
        g = features.grade(features.difficulty(f))
        spread.setdefault(stage.number, {}).setdefault(g, 0)
        spread[stage.number][g] += 1
    for stage in STAGES:
        row = spread[stage.number]
        print(f"stage {stage.number} {stage.name:34}", "  ".join(f"g{g}: {row[g]}" for g in sorted(row)))


if __name__ == "__main__":
    main()
