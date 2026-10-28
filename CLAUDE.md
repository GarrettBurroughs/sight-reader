# Sight-Reading Trainer

Personal app for learning to sight-read piano music. Runs on an iPad with a MIDI keyboard. Developed on a Windows PC inside WSL2 (Ubuntu), with mirrored networking so the iPad can reach the dev server.

Full design doc: https://claude.ai/code/artifact/a8d32fed-dbec-4b2d-97e0-8aba3e17401b

## Architecture (decided)

- **Web app + thin native shell.** Safari/WebKit on iPadOS has no Web MIDI API, so a small Swift Playgrounds app (`ipad/`) wraps a WKWebView and forwards CoreMIDI notes into the page by calling `window.onMidi({type, note, velocity, t})`. The shell should rarely change; all real work happens in `web/`.
- **Dev loop:** `./dev.sh` inside WSL starts the API (127.0.0.1:8000) and Vite (all interfaces, port 5173, proxies `/api`). The iPad shell loads `http://<pc-ip>:5173`; saving a file reloads the iPad. Desktop Chrome supports Web MIDI, so the keyboard can also be tested on the PC directly.
- **MusicXML is the core format**, not MIDI (MIDI loses clefs, key signatures, hands, note spelling). MIDI is derived when needed.
- **Music source v1: PDMX** (250K public-domain MusicXML scores from MuseScore, on Zenodo). Process the whole dataset, but record each score's `no_license_conflict` flag in the catalog so it can be filtered on (pipeline option and library filter). No web scraping.
- **PDF import is future work** (Audiveris OMR → MusicXML → same pipeline, with a manual review step).

- **Cloud (GCP project `gburroughs`, us-east1):** Cloud Run services `sight-reader-staging` / `sight-reader-prod`, one image (Dockerfile) with web + API + library. Push to main deploys staging (`.github/workflows/staging.yml`); `deploy/promote.sh` sends staging's image digest to prod. Player DB: SQLite + Litestream to `gs://gburroughs-sight-reader-{staging,prod}`, max 1 instance, lock in the bucket for deploy handover (`server/persistence.py`). Password login (`server/auth.py`), secrets in Secret Manager. Library versions in `gs://gburroughs-sight-reader-library`, pinned by `library.version`. Names live in `deploy/config.sh`. CLIs are in `~/.local/bin` and `~/.local/google-cloud-sdk/bin` (add to PATH in commands).

## Planned components

- `pipeline/`: Python, **standard library only** (reads MusicXML with ElementTree; chosen over music21 for speed: the full PDMX build takes ~90 s on 16 cores, and excerpts copy the original measures verbatim). `catalog.py` filters PDMX to solo piano (one part, two G/F staves, both hands), cuts up to 4 clean 8-bar excerpts per piece, computes features (`features.py`), grades 1-9 by fixed `GRADE_CUTOFFS` fitted to well-known pieces (`anchors.py` prints the check), and writes `data/library/library.sqlite` + `.mxl` files. Data lives in `pipeline/data/` (git-ignored). Tests: `python3 -m unittest discover -s tests`. `generate.py` adds 6 stages of generated beginner exercises (all grade 1, difficulty ~0.8-3.7) as `pieces.source = 'generated'`. The catalog builds into `data/library.building/` and swaps it in, so the running server keeps working; PDMX excerpt ids are stable across rebuilds.
- `server/`: FastAPI + SQLite (`app.py`, factory `create_app`; level rules in `levels.py`). Player data in `server/data/app.sqlite`; the pipeline's library is ATTACHed read-only. Endpoints: `/api/players` (CRUD), `/api/players/{id}/attempts`, `/api/next`, `/api/attempts`, `/api/excerpts/{id}` and `/api/excerpts/{id}/score.mxl`, `/api/library`, `/api/admin/summary`. Decimal level per player, mode and hands (whole part = grade, fraction = where to aim within that grade's difficulty band, ±0.2 jitter) (`levels.level_key`: `wait`, `tempo:left`...), nudged toward 85% performance. Schema changes go through `ADDED_COLUMNS` (ALTER TABLE on startup), since the user's real practice data lives in `app.sqlite`. Tests: `server/.venv/bin/python -m pytest server/tests`. The venv was made with `--without-pip` + system `pip3 --python` (no ensurepip on this machine).
- **Admin panel:** `web/admin.html` + `src/admin.ts` (library browser with grade breakdowns, players and attempts).
- `web/`: TypeScript + Vite, renders with OpenSheetMusicDisplay (`score.ts`); sessions in `waitSession.ts` / `tempoSession.ts` / `calibrate.ts`, pure scoring logic in `waitMode.ts` / `tempoMode.ts` (vitest: `npm test`). All note times are on the `performance.now()` clock; metronome clicks are scheduled via `getOutputTimestamp()` in `audio.ts`. All input arrives through `onNote` in `web/src/midi.ts` (iPad bridge, Web MIDI, or computer-keyboard fallback).
  - **Wait mode:** advance only when the held notes match the expected set (chords in any order).
  - **Tempo mode:** count-in, metronome, fixed BPM, ±100 ms timing window, separate note and timing scores, latency calibration.

## Milestones

1. ✅ MIDI proof: shell + page showing each note pressed (confirmed working on the iPad with the MIDI keyboard)
2. ✅ One MusicXML score rendered with OSMD, playable in wait mode (test score: `web/public/scores/minuet-in-g.musicxml`)
3. ✅ Tempo mode with scoring (confirmed on the PC; iPad audio/latency not yet checked)
4. ✅ Library pipeline v0 over PDMX (16K pieces, 43K excerpts; grading is a first pass, to be tuned by playing)
5. ✅ Adaptive practice (`/api/next`, saved attempts, moving levels) + admin panel
6. ✅ Generated exercises for the lowest levels
7. Later: offline bundle in the shell, PDF import

## Constraints

- Free Apple account, Swift Playgrounds on the iPad (no Mac). Pure Swift only in `ipad/`, no C/C++ packages. Swift code can't be compiled on the PC; `ipad/package.sh` zips `ipad/SightReader.swiftpm` for the user to open in Swift Playgrounds, and they report errors back. Small fixes they can make by hand on the iPad.
- Dev happens in WSL2: give bash commands for project work. Use PowerShell only for Windows-side setup (`.wslconfig`, firewall).
- WSL must use `networkingMode=mirrored` in `%UserProfile%\.wslconfig`, plus a Hyper-V firewall rule for port 5173; otherwise Vite's Network address is a WSL-internal 172.x IP the iPad can't reach.
