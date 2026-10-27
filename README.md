# Sight-Reading Trainer — MIDI Hello World

Milestone 1 from the design doc: prove that notes from your MIDI keyboard reach a web page running on the iPad, served live from your PC.

```
sight-reader/
  web/    Web client (Vite + TypeScript). Runs on your PC.
  ipad/   Swift files for the iPad shell. Pasted into Swift Playgrounds.
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
2. Open it, tap **+ App** (under "New") to create a blank app. Name it `SightReader`.
3. Open the project. Replace the contents of `MyApp.swift` and `ContentView.swift` with the files in `ipad/`.
4. Add two new Swift files with the **+** button in the sidebar: `MIDIManager.swift` and `WebBridge.swift`, and paste in those files.
   - Easiest way to move the code: put the `ipad` folder in OneDrive, iCloud for Windows, or email it to yourself, then copy from the Files app.
5. Tap **App Settings** (the app icon in the sidebar) → **Capabilities** → **+** → **Local Network**. Give it a purpose string like "Load the practice app from my PC." This lets the app reach your PC over Wi-Fi.
6. Connect the keyboard: USB-C (a USB-B to USB-C cable or adapter for most keyboards) or Bluetooth MIDI.
7. Tap **Run** (▶). When iPadOS asks to find devices on your local network, tap **Allow**.
8. In the address bar at the top, type the Network address from step 1 and tap **Go**.

Play a few notes. You should see the note names, the on-screen keyboard light up, and a log of events tagged `ipad`.

## 3. Day-to-day workflow

- Edit files in `web/` on your PC. Saving reloads the page on the iPad automatically.
- The Swift shell should rarely change. When it does, paste the new file into Swift Playgrounds and run again.
- The address you typed is remembered between launches.

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
