"""Pick passages from a solo piano score and cut them into standalone MusicXML.

Three lengths: 8-bar excerpts, 16-bar sections, and the full piece. Each is graded by its
hardest 8-bar passage (hardest()), so a long piece isn't rated easy for being mostly simple.
"""

from __future__ import annotations

import copy
import xml.etree.ElementTree as ET

import features
from musicxml import Measure, Score, ScoreError

EXCERPT_BARS = 8
MAX_PER_PIECE = 4
SECTION_BARS = 16
MAX_SECTIONS = 3
FULL_MAX_BARS = 160  # longer scores get slow to render on the iPad
HARDEST_STEP = 4  # hardest(): 8-bar windows every 4 bars
# Windows containing any of these are skipped: they'd need jumps or would read confusingly.
BLOCKING_FLAGS = {"ending", "segno", "multirest", "odd-meter", "meter-or-key-change"}


def check_piano(score: Score) -> None:
    """Raise ScoreError unless this looks like two-staff piano music played by both hands."""
    if not score.measures:
        raise ScoreError("no measures")
    first = score.measures[0].attrs
    if first.staves != 2:
        raise ScoreError(f"{first.staves} staves")
    for staff in (1, 2):
        sign = first.clefs.get(staff, ("G", 2))[0]
        if sign not in ("G", "F"):
            raise ScoreError(f"clef {sign} on staff {staff}")
    counts = {1: 0, 2: 0}
    for m in score.measures:
        for n in m.notes:
            if n.played:
                if n.staff not in counts:
                    raise ScoreError(f"note on staff {n.staff}")
                counts[n.staff] += 1
    total = counts[1] + counts[2]
    if total < 40:
        raise ScoreError("too few notes")
    if min(counts.values()) < 0.1 * total:
        raise ScoreError("one hand barely plays")


def first_full_bar(score: Score) -> int:
    """1 if the piece opens with a pickup (anacrusis), else 0."""
    m = score.measures[0] if score.measures else None
    return 1 if m and (m.implicit or m.length < m.attrs.bar_length - 1e-6) else 0


def windows(score: Score, bars: int = EXCERPT_BARS, limit: int = MAX_PER_PIECE) -> list[int]:
    """Start indexes (into score.measures) of usable `bars`-long windows, evenly spread."""
    ms = score.measures
    starts = []
    for start in range(first_full_bar(score), len(ms) - bars + 1, bars):
        if _usable(ms[start : start + bars]):
            starts.append(start)
    if len(starts) > limit:
        step = len(starts) / limit
        starts = [starts[int(i * step)] for i in range(limit)]
    return starts


def full_piece_ok(score: Score) -> bool:
    """Can the whole piece be played straight through? Plain repeat signs are fine (played once);
    first/second endings, D.S./coda jumps, multi-bar rests and meter changes are not."""
    ms = score.measures
    if not EXCERPT_BARS <= len(ms) <= FULL_MAX_BARS:
        return False
    meter = (ms[0].attrs.beats, ms[0].attrs.beat_type)
    for i, m in enumerate(ms):
        if m.flags & BLOCKING_FLAGS or (m.attrs.beats, m.attrs.beat_type) != meter:
            return False
        short = abs(m.length - m.attrs.bar_length) > 1e-6
        if short and not (i == 0 or i == len(ms) - 1):  # only a pickup and a matching last bar may be short
            return False
    return sum(1 for m in ms for n in m.notes if n.played) >= 2 * len(ms)


def hardest(score: Score, start: int, bars: int) -> tuple[float, dict]:
    """Difficulty of the hardest 8-bar passage in measures[start:start+bars], and its features.

    The features also say where that passage starts (hardest_from_bar) and how long the whole span is.
    """
    ms = score.measures
    first = max(start, first_full_bar(score))  # skip a pickup bar
    end = start + bars
    candidates = list(range(first, end - EXCERPT_BARS + 1, HARDEST_STEP)) or [first]
    if candidates[-1] != end - EXCERPT_BARS and end - EXCERPT_BARS > first:
        candidates.append(end - EXCERPT_BARS)  # always include the last bars
    best = None
    for s in candidates:
        window = ms[s : min(s + EXCERPT_BARS, end)]
        f = features.compute(window)
        d = features.difficulty(f)
        if best is None or d > best[0]:
            best = (d, f, s)
    d, f, s = best
    f = {**f, "hardest_from_bar": ms[s].element.get("number"), "span_bars": bars}
    return d, f


def _usable(window: list[Measure]) -> bool:
    for m in window:
        if m.flags & BLOCKING_FLAGS:
            return False
        if m.implicit or abs(m.length - m.attrs.bar_length) > 1e-6:
            return False  # pickups, cadenzas, or measures that don't add up
    # Needs music throughout: starts with notes, at most one silent bar, each hand
    # playing in at least half the bars, and enough notes overall.
    def plays(m: Measure, staff: int | None = None) -> bool:
        return any(n.played and (staff is None or n.staff == staff) for n in m.notes)

    if not plays(window[0]) or sum(not plays(m) for m in window) > len(window) // 8:
        return False
    if any(sum(plays(m, staff) for m in window) < len(window) / 2 for staff in (1, 2)):
        return False
    return sum(1 for m in window for n in m.notes if n.played) >= 2 * len(window)


def cut(score: Score, start: int, title: str, composer: str | None, bars: int = EXCERPT_BARS) -> ET.Element:
    """A standalone score of `bars` bars from `start`, with the clef/key/time it needs.
    A pickup bar at the very start of a full piece is kept as a pickup (numbered 0)."""
    window = score.measures[start : start + bars]
    pickup = start == 0 and first_full_bar(score) == 1
    root = ET.Element("score-partwise", version="4.0")
    work = ET.SubElement(root, "work")
    ET.SubElement(work, "work-title").text = title
    if composer:
        ident = ET.SubElement(root, "identification")
        ET.SubElement(ident, "creator", type="composer").text = composer
    part_list = ET.SubElement(root, "part-list")
    score_part = ET.SubElement(part_list, "score-part", id=score.part_id)
    ET.SubElement(score_part, "part-name").text = "Piano"
    part = ET.SubElement(root, "part", id=score.part_id)

    for i, m in enumerate(window):
        el = copy.deepcopy(m.element)
        el.set("number", str(i if pickup else i + 1))
        if not (pickup and i == 0):
            el.attrib.pop("implicit", None)
        else:
            el.set("implicit", "yes")
        el.attrib.pop("width", None)
        for p in el.findall("print"):
            el.remove(p)
        for barline in el.findall("barline"):
            if barline.find("repeat") is not None:
                el.remove(barline)  # played straight through: repeats once, no jumps
        if i == 0:
            _replace_leading_attributes(el, m)
            _drop_ties(el, "stop")
        if i == len(window) - 1:
            _drop_ties(el, "start")
            _final_barline(el)
        part.append(el)
    return root


def _replace_leading_attributes(el: ET.Element, m: Measure) -> None:
    """Swap the measure's leading <attributes> for a complete set (divisions, key, time, staves, clefs)."""
    for child in list(el):
        if child.tag in ("note", "backup", "forward"):
            break
        if child.tag == "attributes":
            el.remove(child)
    a = m.attrs
    attrs = ET.Element("attributes")
    ET.SubElement(attrs, "divisions").text = str(a.divisions)
    key = ET.SubElement(attrs, "key")
    ET.SubElement(key, "fifths").text = str(a.fifths)
    time = ET.SubElement(attrs, "time")
    ET.SubElement(time, "beats").text = str(a.beats)
    ET.SubElement(time, "beat-type").text = str(a.beat_type)
    ET.SubElement(attrs, "staves").text = str(a.staves)
    for staff in range(1, a.staves + 1):
        sign, line = a.clefs.get(staff, ("G", 2) if staff == 1 else ("F", 4))
        clef = ET.SubElement(attrs, "clef", number=str(staff))
        ET.SubElement(clef, "sign").text = sign
        ET.SubElement(clef, "line").text = str(line)
    el.insert(0, attrs)


def _drop_ties(el: ET.Element, kind: str) -> None:
    """Remove ties that would lead outside the excerpt."""
    for note in el.findall("note"):
        for tie in note.findall("tie"):
            if tie.get("type") == kind:
                note.remove(tie)
        for notations in note.findall("notations"):
            for tied in notations.findall("tied"):
                if tied.get("type") == kind:
                    notations.remove(tied)


def _final_barline(el: ET.Element) -> None:
    for barline in el.findall("barline"):
        if barline.get("location", "right") == "right":
            el.remove(barline)
    barline = ET.SubElement(el, "barline", location="right")
    ET.SubElement(barline, "bar-style").text = "light-heavy"
