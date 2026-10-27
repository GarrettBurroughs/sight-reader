import CoreMIDI
import Foundation

/// One note event from the keyboard.
struct MIDINoteEvent {
    let isOn: Bool
    let note: UInt8
    let velocity: UInt8
    let timeMs: Double
}

/// Listens to every connected MIDI source and reports note-on / note-off events.
final class MIDIManager {
    var onNote: ((MIDINoteEvent) -> Void)?
    var onDevicesChanged: (([String]) -> Void)?

    private var client = MIDIClientRef()
    private var inputPort = MIDIPortRef()
    private var connected: [MIDIEndpointRef] = []
    private var runningStatus: UInt8 = 0
    private let timebase: mach_timebase_info_data_t = {
        var info = mach_timebase_info_data_t()
        mach_timebase_info(&info)
        return info
    }()

    func start() {
        MIDIClientCreateWithBlock("SightReader" as CFString, &client) { [weak self] notification in
            // Fires when a keyboard is plugged in, unplugged, or pairs over Bluetooth.
            if notification.pointee.messageID == .msgSetupChanged {
                DispatchQueue.main.async { self?.connectAllSources() }
            }
        }
        MIDIInputPortCreateWithBlock(client, "Input" as CFString, &inputPort) { [weak self] packetList, _ in
            self?.handle(packetList)
        }
        connectAllSources()
    }

    private func connectAllSources() {
        for source in connected { MIDIPortDisconnectSource(inputPort, source) }
        connected.removeAll()

        var names: [String] = []
        for i in 0..<MIDIGetNumberOfSources() {
            let source = MIDIGetSource(i)
            if MIDIPortConnectSource(inputPort, source, nil) == noErr {
                connected.append(source)
                names.append(displayName(of: source))
            }
        }
        onDevicesChanged?(names)
    }

    private func displayName(of endpoint: MIDIEndpointRef) -> String {
        var name: Unmanaged<CFString>?
        if MIDIObjectGetStringProperty(endpoint, kMIDIPropertyDisplayName, &name) == noErr,
           let value = name?.takeRetainedValue() {
            return value as String
        }
        return "Unknown device"
    }

    // MARK: - Parsing

    private func handle(_ list: UnsafePointer<MIDIPacketList>) {
        for packet in list.unsafeSequence() {
            let length = Int(packet.pointee.length)
            let bytes: [UInt8] = withUnsafeBytes(of: packet.pointee.data) { Array($0.prefix(length)) }
            let time = toMilliseconds(packet.pointee.timeStamp)
            parse(bytes, timeMs: time)
        }
    }

    /// Walks the bytes in a packet, handling running status and skipping messages we don't need.
    private func parse(_ bytes: [UInt8], timeMs: Double) {
        var i = 0
        while i < bytes.count {
            var status = bytes[i]

            if status >= 0xF8 { i += 1; continue }              // real-time (clock, active sensing)
            if status == 0xF0 {                                 // sysex: skip to its end
                while i < bytes.count && bytes[i] != 0xF7 { i += 1 }
                i += 1; continue
            }
            if status < 0x80 {                                  // running status: reuse last status byte
                status = runningStatus
            } else {
                runningStatus = status
                i += 1
            }

            let kind = status & 0xF0
            let dataLength = (kind == 0xC0 || kind == 0xD0) ? 1 : 2
            guard i + dataLength <= bytes.count else { return }

            if kind == 0x90 || kind == 0x80 {
                let note = bytes[i], velocity = bytes[i + 1]
                let isOn = kind == 0x90 && velocity > 0
                onNote?(MIDINoteEvent(isOn: isOn, note: note, velocity: velocity, timeMs: timeMs))
            }
            i += dataLength
        }
    }

    private func toMilliseconds(_ hostTime: MIDITimeStamp) -> Double {
        let t = hostTime == 0 ? mach_absolute_time() : hostTime
        return Double(t) * Double(timebase.numer) / Double(timebase.denom) / 1_000_000
    }
}
