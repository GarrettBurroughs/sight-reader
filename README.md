# Sight-Reading Trainer — MIDI Hello World

Milestone 1 from the design doc: prove that notes from your MIDI keyboard reach a web page running on the iPad, served live from your PC.

```
sight-reader/
  web/       Web client (Vite + TypeScript). Runs on your PC.
  pipeline/  Python (standard library only): builds the graded excerpt library from PDMX.
  ipad/   iPad shell: SightReader.swiftpm, a Swift Playgrounds app project.
```

## 1. Run the web page on your PC

Needs Node.js 20.19 or newer. Run it in WSL2:

```bash
cd ~/dev/sight-reader/web
npm install
npm run dev
```

Vite prints a **Network** address, e.g. `http://192.168.1.20:5173`. Write it down; the iPad needs it.

**WSL networking (one time):** WSL's default NAT mode gives it an internal `172.x` address the iPad can't reach. Create `%UserProfile%\.wslconfig` with:

```
[wsl2]
networkingMode=mirrored
```

then, in an admin PowerShell, run `wsl --shutdown` and allow the port through the Hyper-V firewall:

```powershell
New-NetFirewallHyperVRule -Name Vite5173 -DisplayName "Vite dev 5173" -Direction Inbound -VMCreatorId '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}' -Protocol TCP -LocalPorts 5173
```

Afterwards Vite lists your PC's Wi-Fi address (`192.168.x.x`) as a Network address.

Quick test without the iPad: open `http://localhost:5173` in Chrome on the PC. Plug the keyboard into the PC, or press A W S E D F T G Y H U J K on the computer keyboard.

**Windows firewall:** the first time, Windows asks whether Node.js may accept connections. Allow it on **Private networks**. If you missed the prompt, the iPad will fail to connect; fix it under Windows Security → Firewall → Allow an app → Node.js → tick Private.

## 2. Set up the iPad (one time)

1. Install **Swift Playgrounds** from the App Store (free; needs iPadOS 15.2 or newer, recent versions want newer).
2. On the PC, build the project zip and drop it in OneDrive:
   ```bash
   ipad/package.sh /mnt/c/Users/garre/OneDrive/SightReader
   ```
   (With no argument it writes `ipad/build/SightReader.swiftpm.zip`; email or AirDrop works too.)
3. On the iPad, open the **Files** app, find `SightReader.swiftpm.zip`, and tap it to unzip. Tap the resulting `SightReader` project to open it in Swift Playgrounds. The Local Network permission is already declared in `Package.swift`.
4. If Playgrounds asks you to sign in to set a team for the app, use your Apple account.
5. Connect the keyboard: USB-C (a USB-B to USB-C cable or adapter for most keyboards) or Bluetooth MIDI.
6. Tap **Run** (▶). When iPadOS asks to find devices on your local network, tap **Allow**.
7. The address bar at the top defaults to `http://192.168.1.162:5173`. If your PC's address differs, type the Network address from step 1 and tap **Go**.

Play a few notes. You should see the note names, the on-screen keyboard light up, and a log of events tagged `ipad`.

## 3. Day-to-day workflow

- Edit files in `web/` on your PC. Saving reloads the page on the iPad automatically.
- The Swift shell should rarely change. When it does, run `ipad/package.sh` again and reopen the new copy (delete the old one in Playgrounds first).
- The address you typed is remembered between launches.

## 4. Build the music library (pipeline)

Turns PDMX (public-domain MusicXML from MuseScore) into graded 8-bar piano excerpts. Python 3.10+, no packages to install. Everything lands in `pipeline/data/` (git-ignored).

```bash
cd ~/dev/sight-reader/pipeline
mkdir -p data/raw data/pdmx && cd data/raw
for f in PDMX.csv subset_paths.tar.gz mxl.tar.gz; do curl -L -C - -o "$f" "https://zenodo.org/api/records/15571083/files/$f/content"; done
tar xzf mxl.tar.gz -C ../pdmx && tar xzf subset_paths.tar.gz -C ../pdmx
cd ../..
python3 catalog.py                 # all solo piano scores; add --no-license-conflict-only to skip flagged ones
python3 export_web.py              # copy 30 excerpts per grade into web/public/library for the page's grade picker
python3 -m unittest discover -s tests
```

What `catalog.py` does:

1. **Selects** PDMX rows with one piano track, valid and deduplicated (PDMX keeps the best of many uploads of the same piece).
2. **Keeps solo piano** that really is: one part, two staves (treble/bass clefs), both hands playing.
3. **Cuts up to 4 excerpts of 8 bars** per piece, on 8-bar boundaries, skipping windows with volta endings, D.S./coda jumps, multi-bar rests, meter changes, mostly-empty bars, or bars that don't add up.
4. **Measures difficulty** (`features.py`): note density, left-hand busyness, chords and stretches, leaps, shortest note value, syncopation, tuplets, accidentals, key signature, ledger lines, voices per hand, tempo when marked.
5. **Grades 1–9** by where each excerpt's difficulty falls across the library (equal-sized bands), and writes `data/library/library.sqlite` plus one `.mxl` per excerpt. Each piece keeps its `no_license_conflict` flag for filtering.

## Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| "Couldn't reach the PC" | Dev server not running, wrong IP, different Wi-Fi network, Windows firewall, or Local Network permission denied (iPad Settings → Privacy & Security → Local Network) |
| Page loads, says "No keyboard" | Keyboard not powered or not class-compliant; try a different cable. Bluetooth keyboards may need pairing in a MIDI app first |
| Status says "Web MIDI ready" on the iPad | The page didn't detect the shell; make sure `WebBridge.swift` is the version from this folder |
| Page works in Chrome on the PC but not on the iPad | Almost always network: IP, firewall, or permission |
| Notes stick on after release | Report it; some keyboards send note-on with velocity 0, which is handled, but others may differ |

## How it fits together

- The shell (`MIDIManager.swift`) listens to every MIDI source with CoreMIDI and reconnects when a device is plugged in.
- `WebBridge.swift` turns each note into a call to `window.onMidi({type, note, velocity, t})` in the page.
- The page (`web/src/midi.ts`) accepts notes from that bridge, from Web MIDI in desktop browsers, or from the computer keyboard, and treats them all the same. Later milestones build on that one `onNote` handler.
