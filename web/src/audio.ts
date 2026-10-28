// Metronome clicks synthesised with Web Audio, scheduled on the performance.now() clock.

let ctx: AudioContext | null = null;

/** Call from a tap/click handler: browsers only start audio after a user gesture. */
export function unlockAudio(): AudioContext {
  // Safari: play even when the iPad's silent switch is on.
  const session = (navigator as Navigator & { audioSession?: { type: string } }).audioSession;
  if (session) session.type = "playback";
  ctx ??= new AudioContext();
  if (ctx.state === "suspended") void ctx.resume();
  return ctx;
}

export class Clicks {
  private ctx = unlockAudio();
  private out = this.ctx.createGain();

  constructor() {
    this.out.connect(this.ctx.destination);
  }

  /** Schedule a click at `perfMs` on the performance.now() clock. Accented clicks are higher. */
  at(perfMs: number, accent = false) {
    const when = this.toContextTime(perfMs);
    if (when < this.ctx.currentTime) return;
    const osc = this.ctx.createOscillator();
    const env = this.ctx.createGain();
    osc.frequency.value = accent ? 1600 : 1000;
    env.gain.setValueAtTime(0.6, when);
    env.gain.exponentialRampToValueAtTime(0.001, when + 0.05);
    osc.connect(env).connect(this.out);
    osc.start(when);
    osc.stop(when + 0.06);
  }

  /**
   * Convert a performance.now() time to audio-context time. getOutputTimestamp() pairs the
   * two clocks at the speaker, so it includes output delay; currentTime alone can lag by a
   * render quantum or more, especially right after the context starts.
   */
  private toContextTime(perfMs: number) {
    const ts = this.ctx.getOutputTimestamp?.();
    if (ts?.contextTime && ts.performanceTime) {
      return ts.contextTime + (perfMs - ts.performanceTime) / 1000;
    }
    return this.ctx.currentTime + (perfMs - performance.now()) / 1000;
  }

  /** Silence every click scheduled so far. */
  stop() {
    this.out.disconnect();
  }
}
