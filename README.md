# Sight-Reading Trainer

Personal app for learning to sight-read piano music on an iPad with a MIDI keyboard. Music comes from PDMX (public-domain MuseScore scores), cut into graded excerpts, sections and full pieces, plus generated beginner exercises. Your level moves up and down as you play.

## Links

| | Prod | Staging |
| --- | --- | --- |
| Practice | https://sight-reader-prod-2utjigd64a-ue.a.run.app | https://sight-reader-staging-2utjigd64a-ue.a.run.app |
| Admin panel | [/admin.html](https://sight-reader-prod-2utjigd64a-ue.a.run.app/admin.html) | [/admin.html](https://sight-reader-staging-2utjigd64a-ue.a.run.app/admin.html) |
| iPad app (Swift Playgrounds project) | [Download](https://sight-reader-prod-2utjigd64a-ue.a.run.app/api/ipad-app.zip) | [Download](https://sight-reader-staging-2utjigd64a-ue.a.run.app/api/ipad-app.zip) |
| Health | [/api/health](https://sight-reader-prod-2utjigd64a-ue.a.run.app/api/health) | [/api/health](https://sight-reader-staging-2utjigd64a-ue.a.run.app/api/health) |

Each environment has its own password and its own player data. Deploys: [GitHub Actions](https://github.com/GarrettBurroughs/sight-reader/actions) · Cloud Run console: [services](https://console.cloud.google.com/run?project=gburroughs)

```
sight-reader/
  web/       Practice page and admin panel (Vite + TypeScript, OpenSheetMusicDisplay)
  server/    API (FastAPI + SQLite): picks music, records attempts, tracks levels, login
  pipeline/  Builds the graded music library from PDMX (Python, standard library only)
  ipad/      iPad shell: SightReader.swiftpm, a Swift Playgrounds app that forwards MIDI into the page
  deploy/    GCP scripts (Cloud Run); .github/workflows/ runs them
  dev.sh     Local development: API + web dev server
```

## Set up an iPad

1. Install **Swift Playgrounds** from the App Store.
2. In **Safari** on the iPad, open the prod (or staging) site, log in, and tap **iPad app** at the top right. (Downloads don't work inside the iPad app itself, so use Safari.) The project you get is already set to open the site you downloaded it from.
3. Open the **Files** app → Downloads, tap `SightReader.swiftpm.zip` to unzip, then tap the `SightReader` project to open it in Swift Playgrounds.
4. If Playgrounds asks for a team, sign in with your Apple account.
5. Connect the keyboard (USB-C, or Bluetooth MIDI) and tap **Run** (▶). Log in once; the app remembers it for a year.

**Updating the app** (only needed when `ipad/` changes, which is rare): download it again the same way, delete the old project in Playgrounds, and open the new one. The address you last used is remembered either way; you can also type another one in the address bar at the top.

## Using it

- **Wait / Tempo.** Wait mode moves on when you hold the right notes (chords in any order). Tempo mode plays a count-in and metronome at the BPM you set and scores notes and timing (±100 ms) separately. Run **Calibrate** once per device to measure input and audio delay.
- **Music menu.** **Auto** picks something you haven't played near your level for the current mode. The whole part of a level is the grade and the fraction is how far into that grade's difficulty to aim; picks vary within ±0.2 and never repeat a piece from your last 15. You can also pick a fixed grade, or the built-in test piece (not saved).
- **Length: 8 bars / 16 bars / Full piece.** Longer music is graded by its hardest 8-bar passage. Levels are shared across lengths.
- **Hands: Both / Right / Left.** One-hand practice greys out the other staff and has its own levels (starting a grade above hands together), so drills don't inflate your main level. Hands-together runs record which hand slipped.
- **Levels.** Every finished run moves that mode's level toward getting about 85% right: up to +0.3 when you do better, down to −0.5 when you do worse.
- **Admin panel.** Browse and filter the library (by grade, length, source, license), open anything to see it rendered with a breakdown of why it got its grade, play it, and manage players: levels, attempt history, and which hand slips.

## Local development

Everything runs in WSL2. One-time setup:

```bash
cd ~/dev/sight-reader/web && npm install
cd ~/dev/sight-reader
python3 -m venv --without-pip server/.venv   # this system Python lacks ensurepip; borrow the system pip
pip3 --python server/.venv/bin/python install -r server/requirements-dev.txt
```

Then:

```bash
cd ~/dev/sight-reader && ./dev.sh
```

This starts the API on `127.0.0.1:8000` and Vite on port 5173, which forwards `/api` to the API. Open `http://localhost:5173` in Chrome (Web MIDI works with the keyboard plugged into the PC; or use the keys A W S E D F T G Y H U J K). There's no password locally, player data is in `server/data/app.sqlite`, and saving a file reloads the page. To try it on the iPad, type `http://<pc-ip>:5173` into the app's address bar (or download the app from that address, as above).

**Letting the iPad reach WSL (one time):** WSL's default NAT mode gives it an internal `172.x` address. Create `%UserProfile%\.wslconfig` with

```
[wsl2]
networkingMode=mirrored
```

then in an admin PowerShell run `wsl --shutdown` and open the port in the Hyper-V firewall:

```powershell
New-NetFirewallHyperVRule -Name Vite5173 -DisplayName "Vite dev 5173" -Direction Inbound -VMCreatorId '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}' -Protocol TCP -LocalPorts 5173
```

**Tests:**

```bash
cd ~/dev/sight-reader/web && npm test
cd ~/dev/sight-reader && server/.venv/bin/python -m pytest server/tests
cd ~/dev/sight-reader/pipeline && python3 -m unittest discover -s tests
```

## The music library (pipeline)

Built locally from PDMX into `pipeline/data/` (git-ignored); takes about 3.5 minutes on 16 cores.

```bash
cd ~/dev/sight-reader/pipeline
mkdir -p data/raw data/pdmx && cd data/raw
for f in PDMX.csv subset_paths.tar.gz mxl.tar.gz; do curl -L -C - -o "$f" "https://zenodo.org/api/records/15571083/files/$f/content"; done
tar xzf mxl.tar.gz -C ../pdmx && tar xzf subset_paths.tar.gz -C ../pdmx
cd ../..
python3 catalog.py      # add --no-license-conflict-only to skip scores PDMX flags
python3 anchors.py      # how well-known pieces grade, as a sanity check
```

What `catalog.py` does:

1. **Selects** PDMX rows with one piano track, valid and deduplicated (PDMX keeps the best of many uploads of the same piece).
2. **Keeps real solo piano:** one part, two staves (treble/bass clefs), both hands playing.
3. **Cuts** up to 4 **8-bar excerpts** and up to 3 **16-bar sections** per piece, skipping passages with first/second endings, D.S./coda jumps, multi-bar rests, meter changes, mostly-empty bars, or bars that don't add up. Keeps the **full piece** when it can be played straight through (up to 160 bars; repeat signs are played once).
4. **Measures difficulty** (`features.py`): note density, left-hand busyness, chords and stretches, leaps, shortest note value, syncopation, tuplets, accidentals, key signature, ledger lines, voices per hand, rhythmic variety, tempo when marked. Sections and full pieces take the score of their hardest 8-bar passage.
5. **Adds generated beginner exercises** (`generate.py`): six stages, from hands taking turns on steps to two-note left-hand chords, each following an I–IV–V plan in 4 + 4 bars, in a five-finger position with the starting finger marked. They all land in grade 1, below most PDMX music.
6. **Grades 1–9** with fixed cutoffs fitted so well-known pieces land near their usual Henle level, and writes `data/library/library.sqlite` plus one `.mxl` per item. It builds into a side folder and swaps it in, so a running server isn't disturbed. Ids stay the same across rebuilds, so saved attempts keep pointing at the same music.

To ship a rebuilt library: `deploy/publish-library.sh`, commit `library.version`, push (staging), then `deploy/promote.sh`.

## Deployment (GCP project `gburroughs`, us-east1)

```
 git push (main) ──► GitHub Actions: tests ─► build image ─► Artifact Registry ─► Cloud Run: sight-reader-staging
 deploy/promote.sh ──► the same image (by digest, no rebuild) ─────────────────► Cloud Run: sight-reader-prod
```

Day to day:

```bash
git push                     # tests, then deploy to staging (about 2.5 minutes; watch with: gh run watch)
deploy/promote.sh            # send staging's image to prod
```

- **One container per environment** serves the practice page, admin panel, API, iPad app download and the library (baked in). Cloud Run scales it to zero when idle, so the first request after a pause takes a few seconds.
- **Player data** is SQLite on the instance, replicated continuously to that environment's bucket by Litestream (`server/persistence.py`). Each service runs at most one instance. During a deploy the new instance waits on a lock in the bucket until the old one has done its final sync, so no saved run is lost; API calls are held (up to 25 s) meanwhile.
- **Login:** one password per environment (Secret Manager), remembered by a year-long cookie. `/api/health` stays open for checks.
- **The library** is a versioned tarball in `gs://gburroughs-sight-reader-library`, pinned by `library.version`, so promoting also promotes the library.
- **GitHub → GCP** uses Workload Identity Federation: only this repo's workflows can deploy, with no stored keys.
- **Rolling back:** pick a previous revision in the Cloud Run console, or re-run an older Staging workflow run and promote it.
- **First-time setup** (already done): `deploy/bootstrap.sh` creates the APIs, image repo, buckets, service accounts, secrets (it asks for the passwords), Workload Identity Federation and GitHub variables. It's safe to re-run. Names are in `deploy/config.sh`.

## Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| iPad app shows "Couldn't reach the PC" | Wrong address in the app's address bar, no internet, or (for local dev) `./dev.sh` not running / different Wi-Fi / firewall / Local Network permission denied (iPad Settings → Privacy & Security → Local Network) |
| Page loads, says "No keyboard" | Keyboard not powered or not class-compliant; try a different cable. Bluetooth keyboards may need pairing in a MIDI app first |
| Status says "Web MIDI ready" on the iPad | The page didn't detect the shell; download the iPad app again |
| First load after a while is slow | Cloud Run starting from zero; a few seconds |
| "Starting up; try again in a moment" | A deploy is handing over the database; wait a few seconds |
| Notes stick on after release | Report it; some keyboards send note-on with velocity 0, which is handled, but others may differ |

## How the pieces fit

- The iPad shell (`MIDIManager.swift`) listens to every MIDI source with CoreMIDI; `WebBridge.swift` turns each note into a call to `window.onMidi({type, note, velocity, t})` in the page.
- The page (`web/src/midi.ts`) accepts notes from that bridge, from Web MIDI in desktop browsers, or from the computer keyboard, and treats them all the same. `score.ts` renders MusicXML with OpenSheetMusicDisplay; `waitSession.ts` / `tempoSession.ts` run the two modes.
- The server picks music from the library by level and records each attempt; the pipeline builds that library offline.
