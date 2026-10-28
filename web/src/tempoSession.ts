// Tempo mode: one bar of count-in, then the metronome keeps going and the cursor
// moves at the set tempo whether or not you play. Notes and timing are scored separately.

import type { AttemptResult } from "./api";
import { Clicks } from "./audio";
import { toMidi, type Score, type TimedStep } from "./score";
import { MISS_COLOR, OK_COLOR, SLIP_COLOR, type Session, type UI } from "./session";
import { TempoScorer, type Expected, type Judgement } from "./tempoMode";

const TIMING_WINDOW_MS = 100;
const LEAD_IN_MS = 400;
const SEVERITY: Judgement[] = ["ontime", "early", "late", "missed"];
const COLORS: Record<Judgement, string> = { ontime: OK_COLOR, early: SLIP_COLOR, late: SLIP_COLOR, missed: MISS_COLOR }; // time to get the audio scheduled before the first count-in click

export class TempoSession implements Session {
  private steps: TimedStep[];
  private scorer: TempoScorer;
  private clicks = new Clicks();
  private beatMs: number;
  private start: number; // performance.now() time of the first beat of the piece
  private expectedBySteps: Expected[][]; // the scorer's notes, grouped by step
  private shownStep = -1;
  private raf = 0;
  private done = false;

  constructor(
    private score: Score,
    private ui: UI,
    private bpm: number,
    private latencyMs: number,
    private onFinish: (result: AttemptResult) => void,
  ) {
    this.beatMs = 60_000 / bpm;
    this.steps = score.timeline();
    const expected: Expected[] = this.steps.flatMap((s, step) =>
      s.midi.map((midi) => ({ step, midi, time: s.beat * this.beatMs })),
    );
    // A press can be matched up to half a beat away; beyond that it's a wrong note.
    this.scorer = new TempoScorer(expected, TIMING_WINDOW_MS, Math.min(this.beatMs / 2, 400));
    this.expectedBySteps = this.steps.map(() => []);
    for (const e of expected) this.expectedBySteps[e.step].push(e);

    score.restart();
    ui.message(null);
    const { beats } = score.meter();
    this.start = performance.now() + LEAD_IN_MS + beats * this.beatMs;
    const totalBeats = Math.ceil(score.lengthInBeats());
    for (let k = -beats; k < totalBeats; k++) {
      this.clicks.at(this.start + k * this.beatMs, ((k % beats) + beats) % beats === 0);
    }
    this.tick();
  }

  noteOn(note: number, t: number) {
    if (this.done) return;
    const result = this.scorer.noteOn(note, t - this.start - this.latencyMs);
    if (result.kind === "wrong") this.ui.wrong(note);
    else this.judged(result.note);
    this.render();
  }

  noteOff() {}

  stop() {
    cancelAnimationFrame(this.raf);
    this.clicks.stop();
    this.done = true;
  }

  private tick = () => {
    const now = performance.now() - this.start;
    // Move the cursor on the beat, in step with the clicks you hear.
    const reach = this.scorer.reach;
    let target = this.shownStep;
    while (target + 1 < this.steps.length && this.steps[target + 1].beat * this.beatMs <= now) target++;
    if (target > this.shownStep) {
      this.shownStep = target;
      this.score.seek(this.steps[target].beat);
    }

    for (const e of this.scorer.expire(now - this.latencyMs)) this.judged(e);
    this.render(now);

    const last = this.steps.at(-1);
    if (!last || now - this.latencyMs > last.beat * this.beatMs + reach + 200) this.finish();
    else this.raf = requestAnimationFrame(this.tick);
  };

  /** Recolour a step's notes, each by its own judgement (left and right hand are judged apart). */
  private judged(note: Expected) {
    const byMidi = new Map(this.expectedBySteps[note.step].map((e) => [e.midi, e]));
    this.score.colorEach(
      this.steps[note.step].notes.map((n) => {
        const r = this.scorer.results.get(byMidi.get(toMidi(n))!);
        return { note: n, color: r ? COLORS[r.judgement] : null, severity: r ? SEVERITY.indexOf(r.judgement) : -1 };
      }),
    );
  }

  private render(now = performance.now() - this.start) {
    const s = this.scorer.summary();
    if (now < 0) {
      const beatsLeft = Math.ceil(-now / this.beatMs);
      this.ui.stats([["Count-in", String(beatsLeft)]]);
      return;
    }
    const { measure, total } = this.score.position();
    const judged = s.played + s.missed + s.wrong;
    this.ui.stats([
      ["Bar", `${measure} of ${total}`],
      ["Notes", judged ? `${Math.round(s.notePct)}%` : "—"],
      ["On time", s.played ? `${Math.round(s.timingPct)}%` : "—"],
    ]);
  }

  private finish() {
    this.stop();
    const s = this.scorer.summary();
    const drift = Math.round(s.meanOffset);
    const tendency = Math.abs(drift) < 10 ? "right on the beat" : `${Math.abs(drift)} ms ${drift > 0 ? "late" : "early"}`;
    this.ui.message(
      `Notes ${Math.round(s.notePct)}% (${s.played} of ${s.total} played, ${s.missed} missed, ${s.wrong} wrong) · ` +
        `Timing ${Math.round(s.timingPct)}% within ±${TIMING_WINDOW_MS} ms, on average ${tendency}.`,
      "ok",
    );
    this.onFinish({
      mode: "tempo",
      bpm: this.bpm,
      duration_ms: Math.round(performance.now() - this.start),
      total: s.total,
      played: s.played,
      missed: s.missed,
      wrong: s.wrong,
      note_pct: Math.round(s.notePct * 10) / 10,
      timing_pct: Math.round(s.timingPct * 10) / 10,
      mean_offset_ms: Math.round(s.meanOffset),
    });
  }
}
