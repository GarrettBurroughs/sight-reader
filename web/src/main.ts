import "./style.css";
import { unlockAudio } from "./audio";
import { Calibration } from "./calibrate";
import { isBlackKey, noteName, onDevices, onNote, startInput } from "./midi";
import { Score } from "./score";
import type { Session, UI } from "./session";
import { TempoSession } from "./tempoSession";
import { WaitSession } from "./waitSession";

const SCORE_URL = "/scores/minuet-in-g.musicxml";
const LOW = 36; // C2
const HIGH = 96; // C7

type Mode = "wait" | "tempo";
/** One excerpt exported by pipeline/export_web.py. */
type LibraryEntry = { id: string; grade: number; title: string; composer: string | null; file: string };

const $ = <T extends Element>(sel: string) => document.querySelector<T>(sel)!;
const statusEl = $<HTMLDivElement>("#status");
const scoreEl = $<HTMLDivElement>("#score");
const pianoEl = $<HTMLDivElement>("#piano");
const statsEl = $<HTMLDivElement>("#stats");
const messageEl = $<HTMLDivElement>("#message");
const modeBtns = [...document.querySelectorAll<HTMLButtonElement>("[data-mode]")];
const bpmInput = $<HTMLInputElement>("#bpm");
const goBtn = $<HTMLButtonElement>("#go");
const calibrateBtn = $<HTMLButtonElement>("#calibrate");
const libraryEl = $<HTMLSpanElement>("#library");
const gradeSel = $<HTMLSelectElement>("#grade");
const nextBtn = $<HTMLButtonElement>("#next");

const keyEls = new Map<number, HTMLDivElement>();
const score = new Score(scoreEl);

let mode: Mode = load("mode") === "tempo" ? "tempo" : "wait";
let latencyMs = Number(load("latencyMs") ?? 0) || 0;
let session: Session | null = null;
let tempoRunning = false;
let library: LibraryEntry[] = [];
let currentUrl = SCORE_URL;
bpmInput.value = load("bpm") ?? "60";

// ---- Saved settings (best effort: storage can be unavailable) ----
function load(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function save(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    // not saved; fine
  }
}

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

// ---- What sessions can do to the page ----
const ui: UI = {
  stats(items) {
    statsEl.replaceChildren(
      ...items.map(([label, value]) => {
        const span = document.createElement("span");
        const strong = document.createElement("strong");
        strong.textContent = value;
        span.append(`${label}: `, strong);
        return span;
      }),
    );
  },
  message(text, tone = "info") {
    messageEl.hidden = text === null;
    messageEl.textContent = text ?? "";
    messageEl.className = tone;
  },
  wrong(note) {
    flash(keyEls.get(note), "wrong");
    flash(scoreEl, "wrong");
  },
};

// ---- Modes and controls ----
function setMode(next: Mode) {
  mode = next;
  save("mode", mode);
  document.body.dataset.mode = mode;
  for (const b of modeBtns) b.setAttribute("aria-pressed", String(b.dataset.mode === mode));
  stopSession();
  if (mode === "wait") session = new WaitSession(score, ui);
  else {
    score.restart();
    ui.message(null);
    ui.stats([["Tempo", `${bpm()} BPM`], ["Latency", `${latencyMs} ms`]]);
  }
  renderControls();
}

function stopSession() {
  session?.stop();
  session = null;
  tempoRunning = false;
}

function bpm() {
  const value = Math.round(Number(bpmInput.value));
  return Math.min(200, Math.max(30, Number.isFinite(value) && value > 0 ? value : 60));
}

function renderControls() {
  goBtn.textContent = mode === "wait" ? "Restart" : tempoRunning ? "Stop" : "Start";
  bpmInput.disabled = tempoRunning;
  calibrateBtn.textContent = `Calibrate (${latencyMs} ms)`;
}

goBtn.addEventListener("click", () => {
  goBtn.blur(); // keep the computer-keyboard fallback from "pressing" the button
  if (mode === "wait") {
    stopSession();
    session = new WaitSession(score, ui);
  } else if (tempoRunning) {
    stopSession();
    ui.message("Stopped.", "info");
  } else {
    stopSession();
    unlockAudio();
    bpmInput.value = String(bpm());
    save("bpm", bpmInput.value);
    tempoRunning = true;
    session = new TempoSession(score, ui, bpm(), latencyMs, () => {
      tempoRunning = false;
      renderControls();
    });
  }
  renderControls();
});

calibrateBtn.addEventListener("click", () => {
  calibrateBtn.blur();
  stopSession();
  unlockAudio();
  session = new Calibration(ui, (result) => {
    if (result !== null) {
      latencyMs = result;
      save("latencyMs", String(latencyMs));
    }
    session = null;
    renderControls();
  });
  renderControls();
});

for (const b of modeBtns) {
  b.addEventListener("click", () => {
    b.blur();
    if (b.dataset.mode !== mode) setMode(b.dataset.mode as Mode);
  });
}

// ---- Music: the built-in test piece, or excerpts exported from the pipeline ----
async function loadLibrary() {
  try {
    const res = await fetch("/library/index.json");
    if (res.ok) library = await res.json();
  } catch {
    // no library exported yet; the test piece still works
  }
  const options: [string, string][] = [["test", "Test piece (Minuet)"]];
  for (const g of [...new Set(library.map((e) => e.grade))].sort((a, b) => a - b)) options.push([String(g), `Grade ${g}`]);
  gradeSel.replaceChildren(...options.map(([value, label]) => new Option(label, value)));
  const saved = load("grade");
  gradeSel.value = saved && options.some(([v]) => v === saved) ? saved : "test";
  libraryEl.hidden = library.length === 0;
}

/** Open a random excerpt of the chosen grade (not the one already open), or the test piece. */
function pickPiece() {
  const pool = library.filter((e) => String(e.grade) === gradeSel.value && `/${e.file}` !== currentUrl);
  const entry = pool[Math.floor(Math.random() * pool.length)];
  return openScore(entry ? `/${entry.file}` : SCORE_URL);
}

async function openScore(url: string) {
  stopSession();
  ui.message(null);
  currentUrl = url;
  try {
    await score.load(url);
    setMode(mode);
  } catch (err) {
    ui.message(`Couldn't load ${url}: ${err}`);
  }
}

gradeSel.addEventListener("change", () => {
  gradeSel.blur();
  save("grade", gradeSel.value);
  pickPiece();
});

nextBtn.addEventListener("click", () => {
  nextBtn.blur();
  pickPiece();
});

// ---- Input ----
onNote((e) => {
  const key = keyEls.get(e.note);
  if (e.type === "on") {
    key?.classList.add("down");
    session?.noteOn(e.note, e.t);
  } else {
    key?.classList.remove("down");
    session?.noteOff(e.note);
  }
});

onDevices((d) => {
  statusEl.textContent = d.names.length
    ? `Connected (${d.source}): ${d.names.join(", ")}`
    : `No MIDI device connected (${d.source})`;
  statusEl.classList.toggle("ok", d.names.length > 0);
});

buildPiano();
renderControls();
startInput().then((msg) => {
  if (statusEl.textContent === "Loading…") statusEl.textContent = msg;
});
loadLibrary().then(() => pickPiece());
