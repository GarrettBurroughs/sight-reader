import SwiftUI
import WebKit

struct ContentView: View {
    @StateObject private var bridge = WebBridge()
    @AppStorage("serverAddress") private var address = "http://192.168.1.162:5173"
    @State private var showBar = true

    var body: some View {
        VStack(spacing: 0) {
            if showBar {
                HStack(spacing: 12) {
                    TextField("http://<pc-ip>:5173", text: $address)
                        .textFieldStyle(.roundedBorder)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .onSubmit { bridge.load(address) }
                    Button("Go") { bridge.load(address) }
                    Button { bridge.reload() } label: { Image(systemName: "arrow.clockwise") }
                    Text(bridge.devices.isEmpty ? "No keyboard" : bridge.devices.joined(separator: ", "))
                        .font(.caption)
                        .foregroundStyle(bridge.devices.isEmpty ? .secondary : .green)
                        .lineLimit(1)
                }
                .padding(.horizontal)
                .padding(.vertical, 8)
            }

            WebView(webView: bridge.webView, onLoaded: { bridge.sendDevices() })
                .ignoresSafeArea(edges: .bottom)
        }
        .overlay(alignment: .topTrailing) {
            // Small toggle to hide the address bar while practicing.
            Button { withAnimation { showBar.toggle() } } label: {
                Image(systemName: showBar ? "chevron.up" : "chevron.down")
                    .padding(8)
            }
            .offset(y: showBar ? 44 : 0)
        }
        .onAppear { bridge.load(address) }
    }
}

/// Wraps WKWebView for SwiftUI.
struct WebView: UIViewRepresentable {
    let webView: WKWebView
    let onLoaded: () -> Void

    func makeCoordinator() -> Coordinator { Coordinator(onLoaded: onLoaded) }

    func makeUIView(context: Context) -> WKWebView {
        webView.navigationDelegate = context.coordinator
        return webView
    }

    func updateUIView(_ uiView: WKWebView, context: Context) {}

    final class Coordinator: NSObject, WKNavigationDelegate {
        let onLoaded: () -> Void
        init(onLoaded: @escaping () -> Void) { self.onLoaded = onLoaded }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            onLoaded()
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            let message = error.localizedDescription.replacingOccurrences(of: "'", with: "\\'")
            webView.loadHTMLString(
                "<body style='font:17px -apple-system;padding:40px'><h2>Couldn't reach the PC</h2>"
                + "<p>\(message)</p><p>Check that <code>npm run dev</code> is running, the address is right, "
                + "and both devices are on the same Wi-Fi.</p></body>",
                baseURL: nil
            )
        }
    }
}
