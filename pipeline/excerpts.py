"""Pick excerpt windows from a solo piano score and cut them into standalone MusicXML."""

from __future__ import annotations

import copy
import xml.etree.ElementTree as ET

from musicxml import Measure, Score, ScoreError

EXCERPT_BARS = 8
MAX_PER_PIECE = 4
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


def windows(score: Score) -> list[int]:
    """Start indexes (into score.measures) of usable excerpt windows, evenly spread."""
    ms = score.measures
    first = 1 if ms and (ms[0].implicit or ms[0].length < ms[0].attrs.bar_length - 1e-6) else 0
    starts = []
    for start in range(first, len(ms) - EXCERPT_BARS + 1, EXCERPT_BARS):
        if _usable(ms[start : start + EXCERPT_BARS]):
            starts.append(start)
    if len(starts) > MAX_PER_PIECE:
        step = len(starts) / MAX_PER_PIECE
        starts = [starts[int(i * step)] for i in range(MAX_PER_PIECE)]
    return starts


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

    if not plays(window[0]) or sum(not plays(m) for m in window) > 1:
        return False
    if any(sum(plays(m, staff) for m in window) < len(window) / 2 for staff in (1, 2)):
        return False
    return sum(1 for m in window for n in m.notes if n.played) >= 2 * len(window)


def cut(score: Score, start: int, title: str, composer: str | None) -> ET.Element:
    """A standalone score of EXCERPT_BARS bars from `start`, with the clef/key/time it needs."""
    window = score.measures[start : start + EXCERPT_BARS]
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
        el.set("number", str(i + 1))
        el.attrib.pop("implicit", None)
        el.attrib.pop("width", None)
        for p in el.findall("print"):
            el.remove(p)
        for barline in el.findall("barline"):
            if barline.find("repeat") is not None:
                el.remove(barline)  # an excerpt is played straight through
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
