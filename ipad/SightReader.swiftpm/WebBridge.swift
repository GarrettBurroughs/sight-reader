import Foundation
import WebKit

/// Owns the web view and the MIDI manager, and passes every note into the page.
final class WebBridge: ObservableObject {
    @Published var devices: [String] = []

    let webView: WKWebView
    private let midi = MIDIManager()

    init() {
        let config = WKWebViewConfiguration()
        // Tell the page it is running inside the shell, before any page script runs.
        let flag = WKUserScript(
            source: "window.isSightReaderShell = true;",
            injectionTime: .atDocumentStart,
            forMainFrameOnly: true
        )
        config.userContentController.addUserScript(flag)
        config.allowsInlineMediaPlayback = true
        config.mediaTypesRequiringUserActionForPlayback = []

        webView = WKWebView(frame: .zero, configuration: config)
        if #available(iOS 16.4, *) {
            webView.isInspectable = true // lets Safari's Web Inspector attach, if you ever have a Mac
        }

        midi.onNote = { [weak self] event in
            DispatchQueue.main.async { self?.send(event) }
        }
        midi.onDevicesChanged = { [weak self] names in
            DispatchQueue.main.async {
                self?.devices = names
                self?.sendDevices()
            }
        }
        midi.start()
    }

    func load(_ address: String) {
        guard let url = URL(string: address) else { return }
        webView.load(URLRequest(url: url))
    }

    func reload() {
        webView.reload()
    }

    /// Re-send the device list once a page finishes loading, since the page starts with none.
    func sendDevices() {
        let json = (try? String(data: JSONEncoder().encode(devices), encoding: .utf8)) ?? "[]"
        webView.evaluateJavaScript("window.onMidiDevices && window.onMidiDevices(\(json))")
    }

    private func send(_ e: MIDINoteEvent) {
        let js = "window.onMidi && window.onMidi({type:'\(e.isOn ? "on" : "off")',"
            + "note:\(e.note),velocity:\(e.velocity),t:\(e.timeMs)})"
        webView.evaluateJavaScript(js)
    }
}
