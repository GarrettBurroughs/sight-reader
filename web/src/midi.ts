// Input adapters: every source of notes ends up calling the same handler,
// so the rest of the app never cares where a note came from.

export type NoteEvent = {
  type: "on" | "off";
  note: number; // MIDI note number, 60 = middle C
  velocity: number; // 0-127
  t: number; // milliseconds on the source's clock
  source: "ipad" | "webmidi" | "keyboard";
};

export type DeviceInfo = { source: NoteEvent["source"]; names: string[] };

type Listener = (e: NoteEvent) => void;
type DeviceListener = (d: DeviceInfo) => void;

const listeners: Listener[] = [];
const deviceListeners: DeviceListener[] = [];

export function onNote(fn: Listener) {
  listeners.push(fn);
}

export function onDevices(fn: DeviceListener) {
  deviceListeners.push(fn);
}

function emit(e: NoteEvent) {
  for (const fn of listeners) fn(e);
}

function emitDevices(d: DeviceInfo) {
  for (const fn of deviceListeners) fn(d);
}

// ---------- 1. iPad shell ----------
// The Swift app calls these globals from evaluateJavaScript.

declare global {
  interface Window {
    onMidi?: (e: { type: "on" | "off"; note: number; velocity: number; t: number }) => void;
    onMidiDevices?: (names: string[]) => void;
    isSightReaderShell?: boolean;
  }
}

function installShellBridge() {
  window.onMidi = (e) => emit({ ...e, source: "ipad" });
  window.onMidiDevices = (names) => emitDevices({ source: "ipad", names });
}

// ---------- 2. Web MIDI (desktop Chrome, Edge, Firefox) ----------

async function installWebMidi() {
  if (!("requestMIDIAccess" in navigator)) return false;
  try {
    const access = await navigator.requestMIDIAccess();
    const wire = () => {
      const names: string[] = [];
      access.inputs.forEach((input) => {
        names.push(input.name ?? "Unknown device");
        input.onmidimessage = (msg) => handleBytes(msg.data, msg.timeStamp);
      });
      emitDevices({ source: "webmidi", names });
    };
    access.onstatechange = wire;
    wire();
    return true;
  } catch {
    return false;
  }
}

function handleBytes(data: Uint8Array | null, t: number) {
  if (!data || data.length < 3) return;
  const kind = data[0] & 0xf0;
  const note = data[1];
  const velocity = data[2];
  if (kind === 0x90 && velocity > 0) emit({ type: "on", note, velocity, t, source: "webmidi" });
  else if (kind === 0x80 || (kind === 0x90 && velocity === 0))
    emit({ type: "off", note, velocity, t, source: "webmidi" });
}

// ---------- 3. Computer keyboard fallback ----------
// Piano-style layout starting at middle C: A=C, W=C#, S=D ... K=C (next octave).

const KEY_MAP: Record<string, number> = {
  a: 60, w: 61, s: 62, e: 63, d: 64, f: 65, t: 66,
  g: 67, y: 68, h: 69, u: 70, j: 71, k: 72,
};

function installKeyboard() {
  const down = new Set<string>();
  window.addEventListener("keydown", (ev) => {
    const note = KEY_MAP[ev.key.toLowerCase()];
    if (note === undefined || down.has(ev.key)) return;
    down.add(ev.key);
    emit({ type: "on", note, velocity: 80, t: performance.now(), source: "keyboard" });
  });
  window.addEventListener("keyup", (ev) => {
    const note = KEY_MAP[ev.key.toLowerCase()];
    if (note === undefined) return;
    down.delete(ev.key);
    emit({ type: "off", note, velocity: 0, t: performance.now(), source: "keyboard" });
  });
}

export async function startInput(): Promise<string> {
  installShellBridge();
  installKeyboard();
  if (window.isSightReaderShell) return "Running in the iPad shell";
  const webMidi = await installWebMidi();
  return webMidi ? "Web MIDI ready" : "No Web MIDI here; computer keyboard only";
}

// ---------- Helpers ----------

const NAMES = ["C", "C♯", "D", "D♯", "E", "F", "F♯", "G", "G♯", "A", "A♯", "B"];

export function noteName(n: number): string {
  return `${NAMES[n % 12]}${Math.floor(n / 12) - 1}`;
}

export function isBlackKey(n: number): boolean {
  return [1, 3, 6, 8, 10].includes(n % 12);
}
