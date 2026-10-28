// Thin wrapper around OpenSheetMusicDisplay: render a score and walk its cursor
// one playable step at a time, reporting which MIDI notes each step expects.

import { OpenSheetMusicDisplay, type Note, type VexFlowGraphicalNote } from "opensheetmusicdisplay";

export type Step = {
  midi: number[]; // notes that must be pressed, deduplicated
  notes: Note[]; // the OSMD notes behind them, for colouring
};

export class Score {
  private osmd: OpenSheetMusicDisplay;
  private colored: SVGElement[] = [];

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
    await this.osmd.load(url);
    this.osmd.render();
    this.osmd.cursor.show();
  }

  /** Back to the first note, with colours cleared. */
  restart() {
    for (const el of this.colored) setColor(el, null);
    this.colored = [];
    this.osmd.cursor.reset();
    this.osmd.cursor.show();
  }

  get finished() {
    return this.osmd.cursor.Iterator.EndReached;
  }

  /** The notes at the cursor, skipping steps with nothing to press (rests, tie continuations). */
  current(): Step | null {
    const cursor = this.osmd.cursor;
    while (!cursor.Iterator.EndReached) {
      const notes = cursor.NotesUnderCursor().filter(isPlayable);
      if (notes.length) return { notes, midi: [...new Set(notes.map(toMidi))] };
      cursor.next();
    }
    return null;
  }

  advance() {
    this.osmd.cursor.next();
  }

  /** Measure number at the cursor (1-based) and total measures. */
  position() {
    const it = this.osmd.cursor.Iterator;
    return { measure: it.CurrentMeasureIndex + 1, total: this.osmd.Sheet.SourceMeasures.length };
  }

  color(notes: Note[], color: string) {
    for (const n of notes) {
      const g = (this.osmd.EngravingRules.GNote(n) as VexFlowGraphicalNote | undefined)?.getSVGGElement();
      if (!g) continue;
      setColor(g, color);
      this.colored.push(g);
    }
  }
}

function isPlayable(n: Note) {
  if (n.isRest() || n.IsGraceNote || !n.PrintObject) return false;
  const tie = n.NoteTie;
  return !tie || tie.StartNote === n;
}

/** OSMD's halfTone counts from C0 at 0, MIDI counts from C-1, so MIDI is 12 higher. */
function toMidi(n: Note) {
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
