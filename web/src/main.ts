import "./style.css";
import { api, levelKey, type AttemptResult, type Excerpt, type Hands, type Length, type Player } from "./api";
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

const $ = <T extends Element>(sel: string) => document.querySelector<T>(sel)!;
const statusEl = $<HTMLDivElement>("#status");
const scoreEl = $<HTMLDivElement>("#score");
const pianoEl = $<HTMLDivElement>("#piano");
const statsEl = $<HTMLDivElement>("#stats");
const messageEl = $<HTMLDivElement>("#message");
const modeBtns = [...document.querySelectorAll<HTMLButtonElement>("[data-mode]")];
const handBtns = [...document.querySelectorAll<HTMLButtonElement>("[data-hands]")];
const bpmInput = $<HTMLInputElement>("#bpm");
const goBtn = $<HTMLButtonElement>("#go");
const calibrateBtn = $<HTMLButtonElement>("#calibrate");
const playerSel = $<HTMLSelectElement>("#player");
const gradeSel = $<HTMLSelectElement>("#grade");
const lengthSel = $<HTMLSelectElement>("#length");
const nextBtn = $<HTMLButtonElement>("#next");

const keyEls = new Map<number, HTMLDivElement>();
const score = new Score(scoreEl);

let mode: Mode = load("mode") === "tempo" ? "tempo" : "wait";
let hands: Hands = (["right", "left"] as const).find((h) => h === load("hands")) ?? "both";
let length: Length = (["section", "full"] as const).find((l) => l === load("length")) ?? "excerpt";
let latencyMs = Number(load("latencyMs") ?? 0) || 0;
let session: Session | null = null;
let tempoRunning = false;
let players: Player[] = [];
let player: Player | null = null;
let excerpt: Excerpt | null = null; // the library excerpt on screen, or null for the test piece
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
  renderMusicOptions();
  if (mode === "wait") session = new WaitSession(score, ui, saveAttempt);
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
    session = new WaitSession(score, ui, saveAttempt);
  } else if (tempoRunning) {
    stopSession();
    ui.message("Stopped.", "info");
  } else {
    stopSession();
    unlockAudio();
    bpmInput.value = String(bpm());
    save("bpm", bpmInput.value);
    tempoRunning = true;
    session = new TempoSession(score, ui, bpm(), latencyMs, (result) => {
      tempoRunning = false;
      renderControls();
      saveAttempt(result);
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

// ---- Players, music and results (via the API server) ----
async function loadPlayers() {
  try {
    players = await api.players();
    if (players.length === 0) players = [await api.createPlayer("Player 1")];
  } catch {
    players = []; // no server: only the test piece
  }
  playerSel.replaceChildren(...players.map((p) => new Option(p.name, String(p.id))));
  const saved = Number(load("player"));
  player = players.find((p) => p.id === saved) ?? players[0] ?? null;
  if (player) playerSel.value = String(player.id);
  playerSel.hidden = players.length < 2;
  renderMusicOptions();
}

function renderMusicOptions() {
  const value = gradeSel.value || load("music") || "auto";
  const options: [string, string][] = [];
  if (player) {
    options.push(["auto", `Auto (level ${player.levels[levelKey(mode, hands)].toFixed(1)})`]);
    for (let g = 1; g <= 9; g++) options.push([String(g), `Grade ${g}`]);
  }
  options.push(["test", "Test piece (Minuet)"]);
  gradeSel.replaceChildren(...options.map(([v, label]) => new Option(label, v)));
  gradeSel.value = options.some(([v]) => v === value) ? value : options[0][0];
  nextBtn.hidden = !player;
  lengthSel.hidden = !player || gradeSel.value === "test";
}

/** Ask the server for the next excerpt (by level, or a fixed grade), or open the test piece. */
async function pickPiece() {
  stopSession();
  if (!player || gradeSel.value === "test") return openScore(SCORE_URL, null);
  try {
    const grade = gradeSel.value === "auto" ? undefined : Number(gradeSel.value);
    const { excerpt: next } = await api.next(player.id, mode, hands, length, grade);
    await openScore(next.score_url, next);
  } catch (err) {
    ui.message(`Couldn't get a piece: ${err instanceof Error ? err.message : err}`);
  }
}

async function openScore(url: string, next: Excerpt | null) {
  stopSession();
  ui.message(null);
  excerpt = next;
  try {
    await score.load(url);
    setMode(mode);
  } catch (err) {
    ui.message(`Couldn't load ${url}: ${err}`);
  }
}

/** Record a finished run and show how the level moved. Test-piece runs aren't recorded. */
async function saveAttempt(result: AttemptResult) {
  if (!player || !excerpt) return;
  const finished = messageEl.textContent ?? "";
  try {
    const change = await api.recordAttempt(player.id, excerpt.id, result);
    player.levels[levelKey(result.mode, result.hands)] = change.level_after;
    const arrow = change.level_after > change.level_before ? "▲" : change.level_after < change.level_before ? "▼" : "→";
    const which = `${result.hands === "both" ? "" : result.hands === "right" ? "Right-hand " : "Left-hand "}${result.mode}`;
    ui.message(
      `${finished} ${which[0].toUpperCase()}${which.slice(1)} level ${change.level_before.toFixed(2)} ${arrow} ` +
        `${change.level_after.toFixed(2)} (grade ${excerpt.grade} piece, ${Math.round(change.performance * 100)}%).`,
      "ok",
    );
    renderMusicOptions();
  } catch (err) {
    ui.message(`${finished} (Not saved: ${err instanceof Error ? err.message : err})`, "ok");
  }
}

function renderHands() {
  for (const b of handBtns) b.setAttribute("aria-pressed", String(b.dataset.hands === hands));
}

for (const b of handBtns) {
  b.addEventListener("click", () => {
    b.blur();
    if (b.dataset.hands === hands) return;
    hands = b.dataset.hands as Hands;
    save("hands", hands);
    score.setHands(hands);
    renderHands();
    renderMusicOptions();
    pickPiece(); // one-hand practice needs a piece with enough for that hand to do
  });
}

playerSel.addEventListener("change", () => {
  playerSel.blur();
  player = players.find((p) => String(p.id) === playerSel.value) ?? null;
  if (player) save("player", String(player.id));
  renderMusicOptions();
  pickPiece();
});

lengthSel.addEventListener("change", () => {
  lengthSel.blur();
  length = lengthSel.value as Length;
  save("length", length);
  pickPiece();
});

gradeSel.addEventListener("change", () => {
  gradeSel.blur();
  save("music", gradeSel.value);
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
score.setHands(hands);
lengthSel.value = length;
renderHands();
renderControls();
startInput().then((msg) => {
  if (statusEl.textContent === "Loading…") statusEl.textContent = msg;
});
loadPlayers().then(async () => {
  // The admin panel's "Play this excerpt" links here with ?excerpt=<id>.
  const requested = new URLSearchParams(location.search).get("excerpt");
  if (requested && player) {
    history.replaceState(null, "", location.pathname);
    try {
      const ex = await api.excerpt(requested);
      return openScore(ex.score_url, ex);
    } catch {
      // fall through to a normal pick
    }
  }
  return pickPiece();
});
