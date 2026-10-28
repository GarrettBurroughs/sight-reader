"""Read MusicXML (.mxl or plain) into a simple per-measure note model, and write .mxl.

Only what the pipeline needs: pitches, onsets, durations, staves, voices, and the
attributes (divisions, key, time, clefs) in force at each measure. Times are in
quarter notes.
"""

from __future__ import annotations

import copy
import io
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field

STEP_SEMITONES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


class ScoreError(Exception):
    """The file can't be used (wrong shape, malformed, not solo piano...)."""


@dataclass
class Note:
    onset: float  # quarters from the start of the measure
    duration: float  # quarters (0 for grace notes)
    midi: int | None  # None for rests
    staff: int
    voice: str
    grace: bool = False
    tie_stop: bool = False  # continues a tied note, so it isn't played again

    @property
    def played(self) -> bool:
        """A key press: not a rest, grace note or tie continuation."""
        return self.midi is not None and not self.grace and not self.tie_stop


@dataclass
class Attributes:
    divisions: int = 1
    fifths: int = 0
    beats: int = 4
    beat_type: int = 4
    staves: int = 1
    clefs: dict[int, tuple[str, int]] = field(default_factory=dict)  # staff -> (sign, line)

    @property
    def bar_length(self) -> float:
        return self.beats * 4 / self.beat_type


@dataclass
class Measure:
    element: ET.Element  # the original <measure>, for cutting excerpts
    attrs: Attributes  # in force at the start of the measure (after its leading attributes)
    notes: list[Note]
    length: float  # quarters actually filled
    implicit: bool  # pickup or other measure not counted in the numbering
    flags: set[str]  # e.g. "ending", "segno", "multirest", "clef-change", "octave-shift", "tuplet"
    tempo: float | None  # <sound tempo> if marked here


@dataclass
class Score:
    root: ET.Element
    part_id: str
    measures: list[Measure]


def read_mxl(path: str) -> ET.Element:
    """Parse a compressed .mxl (or a plain .musicxml/.xml) file."""
    if not zipfile.is_zipfile(path):
        return ET.parse(path).getroot()
    with zipfile.ZipFile(path) as z:
        name = None
        if "META-INF/container.xml" in z.namelist():
            container = ET.fromstring(z.read("META-INF/container.xml"))
            # (Elements without children are falsy, so no `or` chaining here.)
            rootfile = container.find(".//{*}rootfile")
            if rootfile is None:
                rootfile = container.find(".//rootfile")
            if rootfile is not None:
                name = rootfile.get("full-path")
        if name is None:
            name = next(n for n in z.namelist() if n.endswith((".xml", ".musicxml")) and not n.startswith("META-INF"))
        return ET.fromstring(z.read(name))


def write_mxl(root: ET.Element, path: str, inner_name: str = "score.musicxml") -> None:
    xml = io.BytesIO()
    ET.ElementTree(root).write(xml, encoding="UTF-8", xml_declaration=True)
    container = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<container><rootfiles><rootfile full-path="%s" media-type="application/vnd.recordare.musicxml+xml"/>'
        "</rootfiles></container>" % inner_name
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("mimetype", "application/vnd.recordare.musicxml", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", container)
        z.writestr(inner_name, xml.getvalue())


def parse(root: ET.Element) -> Score:
    if root.tag != "score-partwise":
        raise ScoreError(f"unsupported root <{root.tag}>")
    parts = root.findall("part")
    if len(parts) != 1:
        raise ScoreError(f"{len(parts)} parts")
    part = parts[0]

    attrs = Attributes()
    measures: list[Measure] = []
    for m in part.findall("measure"):
        flags: set[str] = set()
        notes: list[Note] = []
        tempo = None
        cursor = 0.0
        longest = 0.0
        last_onset = 0.0
        seen_content = False
        start_attrs: Attributes | None = None

        for el in m:
            tag = el.tag
            if tag == "attributes":
                if seen_content:
                    if el.find("clef") is not None:
                        flags.add("clef-change")
                    if el.find("time") is not None or el.find("key") is not None:
                        flags.add("meter-or-key-change")
                attrs = _apply_attributes(attrs, el, flags)
                continue
            if not seen_content and tag in ("note", "backup", "forward"):
                seen_content = True
                start_attrs = copy.deepcopy(attrs)
            if tag == "note":
                note = _read_note(el, attrs, cursor, last_onset, flags)
                if note.grace:
                    notes.append(note)
                    continue
                if el.find("chord") is None:
                    last_onset = cursor
                    cursor += note.duration
                notes.append(note)
            elif tag == "backup":
                cursor -= _dur(el, attrs)
            elif tag == "forward":
                cursor += _dur(el, attrs)
            elif tag == "barline":
                if el.find("ending") is not None:
                    flags.add("ending")
                if el.find("repeat") is not None:
                    flags.add("repeat")
            elif tag == "direction":
                if el.find(".//segno") is not None or el.find(".//coda") is not None:
                    flags.add("segno")
                if el.find(".//octave-shift") is not None:
                    flags.add("octave-shift")
                sound = el.find("sound")
                if sound is not None:
                    if any(sound.get(k) for k in ("dacapo", "dalsegno", "segno", "coda", "tocoda", "fine")):
                        flags.add("segno")
                    if sound.get("tempo"):
                        try:
                            tempo = float(sound.get("tempo"))
                        except ValueError:
                            pass
            elif tag == "sound" and el.get("tempo"):
                try:
                    tempo = float(el.get("tempo"))
                except ValueError:
                    pass
            longest = max(longest, cursor)

        measures.append(
            Measure(
                element=m,
                attrs=start_attrs or copy.deepcopy(attrs),
                notes=notes,
                length=longest,
                implicit=m.get("implicit") == "yes",
                flags=flags,
                tempo=tempo,
            )
        )
    return Score(root=root, part_id=part.get("id", "P1"), measures=measures)


def _apply_attributes(prev: Attributes, el: ET.Element, flags: set[str]) -> Attributes:
    a = copy.deepcopy(prev)
    if (d := el.findtext("divisions")) is not None:
        a.divisions = max(1, int(float(d)))
    if (f := el.findtext("key/fifths")) is not None:
        a.fifths = int(f)
    time = el.find("time")
    if time is not None and time.findtext("beats") is not None:
        try:
            a.beats = int(time.findtext("beats"))
            a.beat_type = int(time.findtext("beat-type"))
        except (TypeError, ValueError):
            flags.add("odd-meter")  # e.g. "3+2" composite meters
    if (s := el.findtext("staves")) is not None:
        a.staves = int(s)
    for clef in el.findall("clef"):
        staff = int(clef.get("number", "1"))
        a.clefs[staff] = (clef.findtext("sign", ""), int(clef.findtext("line", "0") or 0))
    if el.find("measure-style/multiple-rest") is not None:
        flags.add("multirest")
    return a


def _dur(el: ET.Element, attrs: Attributes) -> float:
    return float(el.findtext("duration", "0")) / attrs.divisions


def _read_note(el: ET.Element, attrs: Attributes, cursor: float, last_onset: float, flags: set[str]) -> Note:
    grace = el.find("grace") is not None
    chord = el.find("chord") is not None
    onset = last_onset if chord else cursor
    duration = 0.0 if grace else _dur(el, attrs)
    midi = None
    pitch = el.find("pitch")
    if pitch is not None:
        alter = float(pitch.findtext("alter", "0") or 0)
        midi = STEP_SEMITONES[pitch.findtext("step")] + round(alter) + 12 * (int(pitch.findtext("octave")) + 1)
    elif el.find("unpitched") is not None:
        raise ScoreError("unpitched (percussion) notes")
    if el.find("time-modification") is not None:
        flags.add("tuplet")
    tie_stop = any(t.get("type") == "stop" for t in el.findall("tie"))
    return Note(
        onset=onset,
        duration=duration,
        midi=midi,
        staff=int(el.findtext("staff", "1")),
        voice=el.findtext("voice", "1"),
        grace=grace or el.find("cue") is not None,
        tie_stop=tie_stop,
    )
