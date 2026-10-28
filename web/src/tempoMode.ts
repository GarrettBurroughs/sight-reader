// Tempo-mode scoring: match each key press to the nearest unplayed expected note of
// the same pitch, then judge its timing. Pitch and timing are scored separately.

export type Expected = {
  step: number; // index of the score step (chord) this note belongs to
  midi: number;
  time: number; // ms after the first beat of the piece
};

export type Judgement = "ontime" | "early" | "late" | "missed";

export type PressResult =
  | { kind: "hit"; note: Expected; offset: number; judgement: Judgement }
  | { kind: "wrong" };

export type Summary = {
  total: number;
  played: number;
  ontime: number;
  missed: number;
  wrong: number;
  notePct: number; // right notes as a share of expected notes plus wrong presses
  timingPct: number; // played notes that landed inside the timing window
  meanOffset: number; // ms, positive = late
};

export class TempoScorer {
  readonly results = new Map<Expected, { judgement: Judgement; offset?: number }>();
  private wrong = 0;

  /**
   * @param window presses within ±window ms of the beat count as on time
   * @param reach  presses further than this from any unplayed note of that pitch count as wrong
   */
  constructor(
    readonly expected: Expected[],
    readonly window = 100,
    readonly reach = 300,
  ) {}

  noteOn(midi: number, t: number): PressResult {
    let best: Expected | null = null;
    for (const e of this.expected) {
      if (e.midi !== midi || this.results.has(e) || Math.abs(t - e.time) > this.reach) continue;
      if (!best || Math.abs(t - e.time) < Math.abs(t - best.time)) best = e;
    }
    if (!best) {
      this.wrong++;
      return { kind: "wrong" };
    }
    const offset = t - best.time;
    const judgement: Judgement = Math.abs(offset) <= this.window ? "ontime" : offset < 0 ? "early" : "late";
    this.results.set(best, { judgement, offset });
    return { kind: "hit", note: best, offset, judgement };
  }

  /** Mark notes whose chance has passed by time `t` as missed, and return them. */
  expire(t: number): Expected[] {
    const out: Expected[] = [];
    for (const e of this.expected) {
      if (this.results.has(e) || t <= e.time + this.reach) continue;
      this.results.set(e, { judgement: "missed" });
      out.push(e);
    }
    return out;
  }

  summary(): Summary {
    let played = 0, ontime = 0, missed = 0, offsetSum = 0;
    for (const r of this.results.values()) {
      if (r.judgement === "missed") {
        missed++;
        continue;
      }
      played++;
      offsetSum += r.offset ?? 0;
      if (r.judgement === "ontime") ontime++;
    }
    const total = this.expected.length;
    return {
      total,
      played,
      ontime,
      missed,
      wrong: this.wrong,
      notePct: total + this.wrong ? (100 * played) / (total + this.wrong) : 0,
      timingPct: played ? (100 * ontime) / played : 0,
      meanOffset: played ? offsetSum / played : 0,
    };
  }
}
