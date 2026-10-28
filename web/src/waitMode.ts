// Wait-mode matching: the score only moves on once every expected note has been
// pressed during this step and all of them are held together (chords in any order).
// Notes still held from earlier steps don't count, so repeated notes need a new press.

export type PressResult = "correct" | "wrong" | "complete";

export class WaitMatcher {
  private expected = new Set<number>();
  private pressed = new Set<number>(); // expected notes pressed this step and still held

  setExpected(notes: Iterable<number>) {
    this.expected = new Set(notes);
    this.pressed.clear();
  }

  noteOn(note: number): PressResult {
    if (!this.expected.has(note)) return "wrong";
    this.pressed.add(note);
    return this.pressed.size === this.expected.size ? "complete" : "correct";
  }

  noteOff(note: number) {
    this.pressed.delete(note);
  }
}
