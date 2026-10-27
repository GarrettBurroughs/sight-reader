import "./style.css";
import { isBlackKey, noteName, onDevices, onNote, startInput, type NoteEvent } from "./midi";

const LOW = 36; // C2
const HIGH = 96; // C7

const statusEl = document.querySelector<HTMLDivElement>("#status")!;
const heldEl = document.querySelector<HTMLDivElement>("#held")!;
const pianoEl = document.querySelector<HTMLDivElement>("#piano")!;
const logEl = document.querySelector<HTMLOListElement>("#log")!;

const held = new Map<number, number>(); // note -> velocity
const keyEls = new Map<number, HTMLDivElement>();

// ---- Build the on-screen piano ----
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

// ---- React to notes ----
function render() {
  const notes = [...held.keys()].sort((a, b) => a - b);
  heldEl.textContent = notes.length ? notes.map(noteName).join("  ") : "—";
  for (const [n, el] of keyEls) el.classList.toggle("down", held.has(n));
}

function log(e: NoteEvent) {
  const li = document.createElement("li");
  li.className = e.type;
  li.textContent =
    `${e.type === "on" ? "▼" : "▲"} ${noteName(e.note).padEnd(4)} ` +
    `#${e.note} vel ${e.velocity}  ·  ${e.source}`;
  logEl.prepend(li);
  while (logEl.children.length > 30) logEl.lastElementChild?.remove();
}

onNote((e) => {
  if (e.type === "on") held.set(e.note, e.velocity);
  else held.delete(e.note);
  render();
  log(e);
});

onDevices((d) => {
  statusEl.textContent = d.names.length
    ? `Connected (${d.source}): ${d.names.join(", ")}`
    : `No MIDI device connected (${d.source})`;
  statusEl.classList.toggle("ok", d.names.length > 0);
});

buildPiano();
render();
startInput().then((msg) => {
  if (statusEl.textContent === "Waiting for input…") statusEl.textContent = msg;
});
