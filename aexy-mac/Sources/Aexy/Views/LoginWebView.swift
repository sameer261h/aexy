import SwiftUI
import WebKit

// Web sign-in: load the Aexy web app; the user logs in normally (GitHub/Google/
// Microsoft on the web). The app stores its JWT in localStorage["token"]; we
// read it after navigations + on a short poll and hand it back via onToken.
struct LoginWebView: NSViewRepresentable {
    let webURL: URL
    let onToken: (String) -> Void

    func makeCoordinator() -> Coordinator { Coordinator(onToken: onToken) }

    func makeNSView(context: Context) -> WKWebView {
        let webView = WKWebView()
        webView.navigationDelegate = context.coordinator
        context.coordinator.attach(webView)
        webView.load(URLRequest(url: webURL))
        return webView
    }

    func updateNSView(_ nsView: WKWebView, context: Context) {}

    static func dismantleNSView(_ nsView: WKWebView, coordinator: Coordinator) {
        coordinator.stop()
    }

    final class Coordinator: NSObject, WKNavigationDelegate {
        private let onToken: (String) -> Void
        private weak var webView: WKWebView?
        private var timer: Timer?
        private var fired = false

        init(onToken: @escaping (String) -> Void) { self.onToken = onToken }

        func attach(_ webView: WKWebView) {
            self.webView = webView
            // SPA route changes don't always trigger didFinish — poll too.
            let t = Timer(timeInterval: 1.5, repeats: true) { [weak self] _ in
                Task { @MainActor in self?.checkToken() }
            }
            RunLoop.main.add(t, forMode: .common)
            timer = t
        }

        func stop() {
            timer?.invalidate()
            timer = nil
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            checkToken()
        }

        @MainActor private func checkToken() {
            guard !fired, let webView else { return }
            webView.evaluateJavaScript("window.localStorage.getItem('token')") { [weak self] result, _ in
                guard let self, !self.fired,
                      let token = result as? String, !token.isEmpty else { return }
                self.fired = true
                self.stop()
                self.onToken(token)
            }
        }
    }
}
