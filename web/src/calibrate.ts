// Latency calibration: play steady clicks, the player taps any key along with them,
// and the median gap between click and key arrival becomes the latency correction.
// That covers audio output delay, MIDI/bridge delay and the player's own habit.

import { Clicks } from "./audio";
import type { Session, UI } from "./session";

const CLICKS = 12;
const INTERVAL_MS = 600;
const SKIP = 3; // ignore taps around the first clicks while the player locks in
const MIN_TAPS = 5;

export class Calibration implements Session {
  private clicks = new Clicks();
  private times: number[] = [];
  private offsets: number[] = [];
  private timeout: number;

  constructor(
    private ui: UI,
    private onDone: (latencyMs: number | null) => void,
  ) {
    const first = performance.now() + 1000;
    for (let i = 0; i < CLICKS; i++) {
      this.times.push(first + i * INTERVAL_MS);
      this.clicks.at(this.times[i], i === 0);
    }
    ui.message("Calibrating: tap any key in time with the clicks.", "info");
    ui.stats([["Taps", "0"]]);
    this.timeout = window.setTimeout(() => this.finish(), first + CLICKS * INTERVAL_MS + 300 - performance.now());
  }

  noteOn(_note: number, t: number) {
    const i = nearest(this.times, t);
    if (i < SKIP || Math.abs(t - this.times[i]) > INTERVAL_MS / 2) return;
    this.offsets[i] = t - this.times[i]; // one tap per click; a second tap replaces the first
    this.ui.stats([["Taps", String(this.offsets.filter((x) => x !== undefined).length)]]);
  }

  noteOff() {}

  stop() {
    clearTimeout(this.timeout);
    this.clicks.stop();
  }

  private finish() {
    this.stop();
    const offsets = this.offsets.filter((x) => x !== undefined).sort((a, b) => a - b);
    if (offsets.length < MIN_TAPS) {
      this.ui.message(`Only caught ${offsets.length} taps; calibration not changed. Try again.`, "info");
      this.onDone(null);
      return;
    }
    const latency = Math.round(offsets[Math.floor(offsets.length / 2)]);
    this.ui.message(`Latency set to ${latency} ms.`, "ok");
    this.onDone(latency);
  }
}

function nearest(times: number[], t: number) {
  let best = 0;
  for (let i = 1; i < times.length; i++) if (Math.abs(times[i] - t) < Math.abs(times[best] - t)) best = i;
  return best;
}
