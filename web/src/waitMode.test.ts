import { describe, expect, it } from "vitest";
import { WaitMatcher } from "./waitMode";

describe("WaitMatcher", () => {
  it("completes a single note", () => {
    const m = new WaitMatcher();
    m.setExpected([60]);
    expect(m.noteOn(60)).toBe("complete");
  });

  it("completes a chord pressed in any order", () => {
    const m = new WaitMatcher();
    m.setExpected([55, 59, 62]);
    expect(m.noteOn(62)).toBe("correct");
    expect(m.noteOn(55)).toBe("correct");
    expect(m.noteOn(59)).toBe("complete");
  });

  it("requires chord notes to be held together", () => {
    const m = new WaitMatcher();
    m.setExpected([55, 59]);
    m.noteOn(55);
    m.noteOff(55);
    expect(m.noteOn(59)).toBe("correct");
    expect(m.noteOn(55)).toBe("complete");
  });

  it("flags notes that aren't expected without blocking the step", () => {
    const m = new WaitMatcher();
    m.setExpected([60]);
    expect(m.noteOn(61)).toBe("wrong");
    expect(m.noteOn(60)).toBe("complete");
  });

  it("needs a fresh press for a repeated note", () => {
    const m = new WaitMatcher();
    m.setExpected([67]);
    expect(m.noteOn(67)).toBe("complete");
    m.setExpected([67]); // next step, key still held
    m.noteOff(67);
    expect(m.noteOn(67)).toBe("complete");
  });
});
