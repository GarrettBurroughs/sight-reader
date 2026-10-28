// What main.ts gives each practice session, and what it expects back.

export type UI = {
  /** Replace the stats line, e.g. [["Bar", "3 of 16"], ["Wrong notes", "2"]]. */
  stats(items: [label: string, value: string][]): void;
  /** Show a message banner, or hide it with null. */
  message(text: string | null, tone?: "ok" | "info"): void;
  /** Flash the score and the on-screen key for a wrong note. */
  wrong(note: number): void;
};

export interface Session {
  noteOn(note: number, t: number): void;
  noteOff(note: number): void;
  stop(): void;
}

export const OK_COLOR = "#2e8b57";
export const SLIP_COLOR = "#d9822b"; // right notes, but with a slip (wrong note or off the beat)
export const MISS_COLOR = "#d64545";

export function formatTime(ms: number) {
  const s = Math.floor(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
