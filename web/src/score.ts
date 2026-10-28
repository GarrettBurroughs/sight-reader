// Thin wrapper around OpenSheetMusicDisplay: render a score and walk its cursor
// one playable step at a time, reporting which MIDI notes each step expects.

import { OpenSheetMusicDisplay, type Note, type VexFlowGraphicalNote } from "opensheetmusicdisplay";

export type Step = {
  midi: number[]; // notes that must be pressed, deduplicated
  notes: Note[]; // the OSMD notes behind them, for colouring
};

export type Hands = "both" | "right" | "left";
export type Hand = "right" | "left";

const DIM_COLOR = "#c4bfb5"; // the hand you're not playing

export type TimedStep = Step & {
  beat: number; // beats after the start, in the time signature's beat unit
};

export class Score {
  private osmd: OpenSheetMusicDisplay;
  private colored: SVGElement[] = [];
  private _hands: Hands = "both";

  constructor(container: HTMLElement) {
    this.osmd = new OpenSheetMusicDisplay(container, {
      backend: "svg",
      autoResize: true,
      drawTitle: true,
      drawComposer: true,
      drawPartNames: false,
      followCursor: true,
    });
  }

  async load(url: string) {
    this.colored = [];
    await this.osmd.load(url);
    this.osmd.render();
    this.osmd.cursor.show();
  }

  get hands() {
    return this._hands;
  }

  /** Play one hand only: the other hand's notes are greyed out and never expected. */
  setHands(hands: Hands) {
    this._hands = hands;
  }

  /** Back to the first note, with colours cleared (and the other hand greyed out). */
  restart() {
    for (const el of this.colored) setColor(el, null);
    this.colored = [];
    if (this._hands !== "both") this.color(this.allNotes().filter((n) => handOf(n) !== this._hands), DIM_COLOR);
    this.osmd.cursor.reset();
    this.osmd.cursor.show();
  }

  private allNotes(): Note[] {
    const it = this.osmd.Sheet.MusicPartManager.getIterator();
    const notes: Note[] = [];
    for (; !it.EndReached; it.moveToNext()) notes.push(...it.CurrentVoiceEntries.flatMap((v) => v.Notes));
    return notes.filter((n) => !n.isRest());
  }

  /** A note this session expects you to press. */
  private expects(n: Note) {
    return isPlayable(n) && (this._hands === "both" || handOf(n) === this._hands);
  }

  get finished() {
    return this.osmd.cursor.Iterator.EndReached;
  }

  /** The notes at the cursor, skipping steps with nothing to press (rests, tie continuations). */
  current(): Step | null {
    const cursor = this.osmd.cursor;
    while (!cursor.Iterator.EndReached) {
      const notes = cursor.NotesUnderCursor().filter((n) => this.expects(n));
      if (notes.length) return { notes, midi: [...new Set(notes.map(toMidi))] };
      cursor.next();
    }
    return null;
  }

  advance() {
    this.osmd.cursor.next();
  }

  /** Time signature of the first bar, e.g. { beats: 3, unit: 4 } for 3/4. */
  meter() {
    const ts = this.osmd.Sheet.SourceMeasures[0].ActiveTimeSignature;
    return { beats: ts.Numerator, unit: ts.Denominator };
  }

  /** Length of the whole piece in beats. */
  lengthInBeats() {
    const whole = this.osmd.Sheet.SourceMeasures.reduce((sum, m) => sum + m.Duration.RealValue, 0);
    return whole * this.meter().unit;
  }

  /** Every playable step with its start time, read without moving the visible cursor. */
  timeline(): TimedStep[] {
    const { unit } = this.meter();
    const it = this.osmd.Sheet.MusicPartManager.getIterator();
    const steps: TimedStep[] = [];
    while (!it.EndReached) {
      const notes = it.CurrentVoiceEntries.flatMap((v) => v.Notes).filter((n) => this.expects(n));
      if (notes.length) {
        steps.push({ notes, midi: [...new Set(notes.map(toMidi))], beat: it.currentTimeStamp.RealValue * unit });
      }
      it.moveToNext();
    }
    return steps;
  }

  /** Move the cursor forward to the first position at or after `beat`. */
  seek(beat: number) {
    const cursor = this.osmd.cursor;
    const { unit } = this.meter();
    while (!cursor.Iterator.EndReached && cursor.Iterator.currentTimeStamp.RealValue * unit < beat - 1e-6) {
      cursor.next();
    }
  }

  /** Measure number at the cursor (1-based) and total measures. */
  position() {
    const it = this.osmd.cursor.Iterator;
    return { measure: it.CurrentMeasureIndex + 1, total: this.osmd.Sheet.SourceMeasures.length };
  }

  /** Colour whole notes (head, stem, flag) of these notes' chords. */
  color(notes: Note[], color: string) {
    for (const n of notes) {
      const g = this.group(n);
      if (!g) continue;
      setColor(g, color);
      this.colored.push(g);
    }
  }

  /**
   * Colour each note on its own. A chord's stem and flag take the worst colour among its
   * notes once they are all judged; until then only the judged noteheads are coloured.
   * `color: null` means not judged yet.
   */
  colorEach(entries: { note: Note; color: string | null; severity: number }[]) {
    const groups = new Map<SVGGElement, typeof entries>();
    for (const e of entries) {
      const g = this.group(e.note);
      if (!g) continue;
      groups.set(g, [...(groups.get(g) ?? []), e]);
    }
    for (const [g, members] of groups) {
      if (members.every((m) => m.color !== null)) {
        const worst = members.reduce((a, b) => (b.severity > a.severity ? b : a));
        setColor(g, worst.color);
      }
      for (const m of members) {
        const head = m.color && this.head(m.note);
        if (head) setColor(head, m.color);
      }
      this.colored.push(g);
    }
  }

  private gnote(n: Note) {
    return this.osmd.EngravingRules.GNote(n) as VexFlowGraphicalNote | undefined;
  }

  private group(n: Note): SVGGElement | undefined {
    return this.gnote(n)?.getSVGGElement() ?? undefined;
  }

  /** The notehead of this note within its chord (VexFlow draws heads in chord-key order). */
  private head(n: Note): SVGElement | undefined {
    const g = this.gnote(n);
    return g?.getNoteheadSVGs()[g.vfnoteIndex] as SVGElement | undefined;
  }
}

/** Which hand plays a note: the top staff is the right hand, anything below it the left. */
export function handOf(n: Note): Hand {
  const staff = n.ParentStaff;
  return staff.ParentInstrument.Staves.indexOf(staff) === 0 ? "right" : "left";
}

function isPlayable(n: Note) {
  if (n.isRest() || n.IsGraceNote || !n.PrintObject) return false;
  const tie = n.NoteTie;
  return !tie || tie.StartNote === n;
}

/** OSMD's halfTone counts from C0 at 0, MIDI counts from C-1, so MIDI is 12 higher. */
export function toMidi(n: Note) {
  return n.halfTone + 12;
}

function setColor(el: SVGElement, color: string | null) {
  // VexFlow sets fill/stroke on each path, so colour the children rather than the group.
  for (const child of el.querySelectorAll<SVGElement>("path, rect")) {
    if (color === null) {
      child.style.removeProperty("fill");
      child.style.removeProperty("stroke");
    } else {
      child.style.fill = color;
      child.style.stroke = color;
    }
  }
}
