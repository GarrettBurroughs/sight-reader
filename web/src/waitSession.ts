// Wait mode: the cursor waits on each step until the right notes are held.

import type { AttemptResult } from "./api";
import { noteName } from "./midi";
import { handOf, toMidi, type Hand, type Score, type Step } from "./score";
import { formatTime, OK_COLOR, SLIP_COLOR, type Session, type UI } from "./session";
import { WaitMatcher } from "./waitMode";

export class WaitSession implements Session {
  private matcher = new WaitMatcher();
  private step: Step | null = null;
  private stepSlipped = false;
  private mistakes = 0;
  private stepsDone = 0;
  private wrongBy: Record<Hand, number> = { right: 0, left: 0 };
  private startedAt: number | null = null;
  private finishedAt: number | null = null;
  private timer: number;

  constructor(
    private score: Score,
    private ui: UI,
    private onFinish: (result: AttemptResult) => void = () => {},
  ) {
    score.restart();
    ui.message(null);
    this.enterStep();
    this.timer = window.setInterval(() => {
      if (this.startedAt !== null && this.finishedAt === null) this.render();
    }, 250);
  }

  noteOn(note: number, t: number) {
    if (!this.step) return;
    this.startedAt ??= t;
    const result = this.matcher.noteOn(note);
    if (result === "wrong") {
      this.mistakes++;
      this.wrongBy[this.nearestHand(note)]++;
      this.stepSlipped = true;
      this.ui.wrong(note);
      this.render();
    } else if (result === "complete") {
      this.score.color(this.step.notes, this.stepSlipped ? SLIP_COLOR : OK_COLOR);
      this.stepsDone++;
      this.score.advance();
      this.enterStep();
    }
  }

  noteOff(note: number) {
    this.matcher.noteOff(note);
  }

  stop() {
    clearInterval(this.timer);
  }

  private enterStep() {
    this.step = this.score.current();
    this.stepSlipped = false;
    if (this.step) {
      this.matcher.setExpected(this.step.midi);
    } else {
      this.finishedAt = performance.now();
      const n = this.mistakes;
      this.ui.message(
        `Finished in ${formatTime(this.finishedAt - (this.startedAt ?? this.finishedAt))} ` +
          `with ${n} wrong note${n === 1 ? "" : "s"}.`,
        "ok",
      );
      this.onFinish({
        mode: "wait",
        hands: this.score.hands,
        wrong_right: this.wrongBy.right,
        wrong_left: this.wrongBy.left,
        steps: this.stepsDone,
        wrong: this.mistakes,
        duration_ms: Math.round(this.finishedAt - (this.startedAt ?? this.finishedAt)),
      });
    }
    this.render();
  }

  /** Whose slip was it? The hand of the expected note closest in pitch to the wrong one. */
  private nearestHand(note: number): Hand {
    const notes = this.step!.notes;
    const best = notes.reduce((a, b) => (Math.abs(toMidi(b) - note) < Math.abs(toMidi(a) - note) ? b : a));
    return handOf(best);
  }

  private render() {
    const { measure, total } = this.score.position();
    const end = this.finishedAt ?? performance.now();
    const items: [string, string][] = [
      ["Bar", this.step ? `${measure} of ${total}` : `all ${total}`],
      ["Wrong notes", String(this.mistakes)],
      ["Time", this.startedAt === null ? "0:00" : formatTime(end - this.startedAt)],
    ];
    // Only give the answer away after a wrong note on this step.
    if (this.step && this.stepSlipped) {
      items.push(["Hint", this.step.midi.slice().sort((a, b) => a - b).map(noteName).join(" ")]);
    }
    this.ui.stats(items);
  }
}
