# Sight-Reading Trainer

Personal app for learning to sight-read piano music. Runs on an iPad with a MIDI keyboard. Developed on a Windows PC inside WSL2 (Ubuntu), with mirrored networking so the iPad can reach the dev server.

Full design doc: https://claude.ai/code/artifact/a8d32fed-dbec-4b2d-97e0-8aba3e17401b

## Architecture (decided)

- **Web app + thin native shell.** Safari/WebKit on iPadOS has no Web MIDI API, so a small Swift Playgrounds app (`ipad/`) wraps a WKWebView and forwards CoreMIDI notes into the page by calling `window.onMidi({type, note, velocity, t})`. The shell should rarely change; all real work happens in `web/`.
- **Dev loop:** `npm run dev` in `web/` inside WSL (Vite, listens on all interfaces, port 5173). The iPad shell loads `http://<pc-ip>:5173`; saving a file reloads the iPad. Desktop Chrome supports Web MIDI, so the keyboard can also be tested on the PC directly.
- **MusicXML is the core format**, not MIDI (MIDI loses clefs, key signatures, hands, note spelling). MIDI is derived when needed.
- **Music source v1: PDMX** (250K public-domain MusicXML scores from MuseScore, on Zenodo). Use only the `no_license_conflict` subset. No web scraping.
- **PDF import is future work** (Audiveris OMR → MusicXML → same pipeline, with a manual review step).

## Planned components

- `pipeline/` (not yet built): Python + music21 batch job. Filter PDMX to solo piano, normalize to .mxl, cut 8–16 bar excerpts, compute difficulty features, grade 1–9 (Henle-style scale), export SQLite catalog + files. Also generates simple exercises for levels 1–3.
- `server/` (not yet built): FastAPI + SQLite, home network only. Endpoints: `/api/next`, `/api/excerpts/{id}`, `/scores/{id}.mxl`, `/api/sessions`, `/api/progress`, `/api/library`. Tracks a decimal player level per mode, nudged after each attempt.
- `web/`: TypeScript + Vite, renders with OpenSheetMusicDisplay (`score.ts`); wait-mode matching in `waitMode.ts` (vitest: `npm test`). All input arrives through `onNote` in `web/src/midi.ts` (iPad bridge, Web MIDI, or computer-keyboard fallback).
  - **Wait mode:** advance only when the held notes match the expected set (chords in any order).
  - **Tempo mode:** count-in, metronome, fixed BPM, ±100 ms timing window, separate note and timing scores, latency calibration.

## Milestones

1. ✅ MIDI proof: shell + page showing each note pressed (confirmed working on the iPad with the MIDI keyboard)
2. ✅ One MusicXML score rendered with OSMD, playable in wait mode (test score: `web/public/scores/minuet-in-g.musicxml`)
3. Tempo mode with scoring
4. Library pipeline v0 over PDMX
5. Adaptive practice (`/api/next`, saved attempts, moving levels)
6. Generated exercises for the lowest levels
7. Later: offline bundle in the shell, PDF import

## Constraints

- Free Apple account, Swift Playgrounds on the iPad (no Mac). Pure Swift only in `ipad/`, no C/C++ packages. Swift code can't be compiled on the PC; `ipad/package.sh` zips `ipad/SightReader.swiftpm` for the user to open in Swift Playgrounds, and they report errors back. Small fixes they can make by hand on the iPad.
- Dev happens in WSL2: give bash commands for project work. Use PowerShell only for Windows-side setup (`.wslconfig`, firewall).
- WSL must use `networkingMode=mirrored` in `%UserProfile%\.wslconfig`, plus a Hyper-V firewall rule for port 5173; otherwise Vite's Network address is a WSL-internal 172.x IP the iPad can't reach.
