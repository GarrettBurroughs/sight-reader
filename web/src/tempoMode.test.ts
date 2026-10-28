import { describe, expect, it } from "vitest";
import { TempoScorer, type Expected } from "./tempoMode";

const notes = (...xs: [number, number, number][]): Expected[] =>
  xs.map(([step, midi, time]) => ({ step, midi, time }));

describe("TempoScorer", () => {
  it("judges on-time, early and late presses", () => {
    const s = new TempoScorer(notes([0, 60, 0], [1, 62, 1000], [2, 64, 2000]), 100, 300);
    expect(s.noteOn(60, 40)).toMatchObject({ kind: "hit", judgement: "ontime", offset: 40 });
    expect(s.noteOn(62, 850)).toMatchObject({ kind: "hit", judgement: "early" });
    expect(s.noteOn(64, 2200)).toMatchObject({ kind: "hit", judgement: "late" });
  });

  it("counts a wrong pitch or a press far from any note as wrong", () => {
    const s = new TempoScorer(notes([0, 60, 0]), 100, 300);
    expect(s.noteOn(61, 0).kind).toBe("wrong");
    expect(s.noteOn(60, 500).kind).toBe("wrong");
  });

  it("matches a repeated pitch to the nearest unplayed note", () => {
    const s = new TempoScorer(notes([0, 67, 0], [1, 67, 500]), 100, 300);
    expect(s.noteOn(67, 480)).toMatchObject({ note: { step: 1 } });
    expect(s.noteOn(67, 20)).toMatchObject({ note: { step: 0 } });
  });

  it("expires notes once they can no longer be played", () => {
    const s = new TempoScorer(notes([0, 60, 0], [1, 62, 1000]), 100, 300);
    expect(s.expire(299)).toHaveLength(0);
    expect(s.expire(301).map((e) => e.midi)).toEqual([60]);
    expect(s.noteOn(60, 310).kind).toBe("wrong");
  });

  it("summarises note and timing accuracy separately", () => {
    const s = new TempoScorer(notes([0, 60, 0], [1, 62, 1000], [2, 64, 2000], [3, 65, 3000]), 100, 300);
    s.noteOn(60, 0); // on time
    s.noteOn(62, 1200); // late
    s.noteOn(70, 1500); // wrong
    s.noteOn(64, 2000); // on time
    s.expire(5000); // 65 missed
    expect(s.summary()).toMatchObject({
      total: 4, played: 3, ontime: 2, missed: 1, wrong: 1,
      notePct: 60, // 3 of (4 + 1)
    });
    expect(s.summary().timingPct).toBeCloseTo(66.67, 1);
    expect(s.summary().meanOffset).toBeCloseTo(66.67, 1);
  });
});
