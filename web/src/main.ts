import "./style.css";
import { isBlackKey, noteName, onDevices, onNote, startInput } from "./midi";
import { Score, type Step } from "./score";
import { WaitMatcher } from "./waitMode";

const SCORE_URL = "/scores/minuet-in-g.musicxml";
const LOW = 36; // C2
const HIGH = 96; // C7
const OK_COLOR = "#2e8b57";
const SLIP_COLOR = "#d9822b"; // step finished, but with a wrong note along the way

const statusEl = document.querySelector<HTMLDivElement>("#status")!;
const scoreEl = document.querySelector<HTMLDivElement>("#score")!;
const pianoEl = document.querySelector<HTMLDivElement>("#piano")!;
const progressEl = document.querySelector<HTMLSpanElement>("#progress")!;
const mistakesEl = document.querySelector<HTMLSpanElement>("#mistakes")!;
const timeEl = document.querySelector<HTMLSpanElement>("#time")!;
const expectEl = document.querySelector<HTMLSpanElement>("#expect")!;
const doneEl = document.querySelector<HTMLDivElement>("#done")!;
const restartBtn = document.querySelector<HTMLButtonElement>("#restart")!;

const held = new Set<number>();
const keyEls = new Map<number, HTMLDivElement>();
const score = new Score(scoreEl);
const matcher = new WaitMatcher();

let step: Step | null = null;
let stepSlipped = false;
let mistakes = 0;
let startedAt: number | null = null;
let finishedAt: number | null = null;

// ---- On-screen piano ----
function buildPiano() {
  const whiteCount = range(LOW, HIGH).filter((n) => !isBlackKey(n)).length;
  pianoEl.style.setProperty("--whites", String(whiteCount));
  let whiteIndex = 0;
  for (const n of range(LOW, HIGH)) {
    const el = document.createElement("div");
    el.className = isBlackKey(n) ? "key black" : "key white";
    if (isBlackKey(n)) {
      el.style.left = `calc(${whiteIndex} * var(--w) - var(--bw) / 2)`;
    } else {
      el.style.left = `calc(${whiteIndex} * var(--w))`;
      whiteIndex++;
      if (n % 12 === 0) el.textContent = noteName(n);
    }
    pianoEl.appendChild(el);
    keyEls.set(n, el);
  }
}

function range(a: number, b: number) {
  return Array.from({ length: b - a + 1 }, (_, i) => a + i);
}

function flash(el: Element | undefined, cls: string) {
  if (!el) return;
  el.classList.remove(cls);
  void (el as HTMLElement).offsetWidth; // restart the animation
  el.classList.add(cls);
}

// ---- Practice state ----
function enterStep() {
  step = score.current();
  stepSlipped = false;
  if (step) {
    matcher.setExpected(step.midi);
  } else {
    finishedAt = performance.now();
    doneEl.hidden = false;
    doneEl.textContent =
      `Finished in ${formatTime(finishedAt - (startedAt ?? finishedAt))} with ` +
      `${mistakes} wrong note${mistakes === 1 ? "" : "s"}.`;
  }
  renderStats();
}

function restart() {
  score.restart();
  mistakes = 0;
  startedAt = finishedAt = null;
  doneEl.hidden = true;
  enterStep();
}

function renderStats() {
  const { measure, total } = score.position();
  progressEl.textContent = step ? `Bar ${measure} of ${total}` : `All ${total} bars`;
  mistakesEl.textContent = String(mistakes);
  expectEl.textContent = step ? step.midi.slice().sort((a, b) => a - b).map(noteName).join(" ") : "—";
  renderTime();
}

function renderTime() {
  const end = finishedAt ?? performance.now();
  timeEl.textContent = startedAt === null ? "0:00" : formatTime(end - startedAt);
}

function formatTime(ms: number) {
  const s = Math.floor(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

onNote((e) => {
  const key = keyEls.get(e.note);
  if (e.type === "off") {
    held.delete(e.note);
    key?.classList.remove("down");
    matcher.noteOff(e.note);
    return;
  }

  held.add(e.note);
  key?.classList.add("down");
  if (!step) return;
  startedAt ??= performance.now();

  const result = matcher.noteOn(e.note);
  if (result === "wrong") {
    mistakes++;
    stepSlipped = true;
    flash(key, "wrong");
    flash(scoreEl, "wrong");
    renderStats();
  } else if (result === "complete") {
    score.color(step.notes, stepSlipped ? SLIP_COLOR : OK_COLOR);
    score.advance();
    enterStep();
  }
});

onDevices((d) => {
  statusEl.textContent = d.names.length
    ? `Connected (${d.source}): ${d.names.join(", ")}`
    : `No MIDI device connected (${d.source})`;
  statusEl.classList.toggle("ok", d.names.length > 0);
});

restartBtn.addEventListener("click", () => {
  restartBtn.blur(); // keep the computer-keyboard fallback from "pressing" the button
  restart();
});

setInterval(() => {
  if (startedAt !== null && finishedAt === null) renderTime();
}, 250);

buildPiano();
startInput().then((msg) => {
  if (statusEl.textContent === "Loading…") statusEl.textContent = msg;
});
score
  .load(SCORE_URL)
  .then(enterStep)
  .catch((err) => {
    scoreEl.textContent = `Couldn't load ${SCORE_URL}: ${err}`;
  });
