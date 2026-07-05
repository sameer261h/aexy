import SwiftUI
import WebKit

// Loads an Aexy web route chromeless (?embed=true → the web hides its own
// sidebar). Shares the persistent session from sign-in, and pins the web to the
// natively-selected workspace by seeding localStorage before load. No token
// injection (that caused a redirect loop); auth rides the shared session.
struct EmbeddedWebView: NSViewRepresentable {
    let route: String          // e.g. "/crm"
    let workspaceId: String?

    func makeNSView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        var js = "try { localStorage.setItem('aexy_embed', '1');"
        if let ws = workspaceId {
            js += " localStorage.setItem('current_workspace_id', '\(ws)');"
        }
        js += " } catch (e) {}"
        configuration.userContentController.addUserScript(
            WKUserScript(source: js, injectionTime: .atDocumentStart, forMainFrameOnly: true)
        )
        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.load(URLRequest(url: url()))
        return webView
    }

    func updateNSView(_ nsView: WKWebView, context: Context) {}

    private func url() -> URL {
        let path = route.drop(while: { $0 == "/" })
        guard var comps = URLComponents(
            url: AexyWeb.url.appendingPathComponent(String(path)),
            resolvingAgainstBaseURL: false
        ) else { return AexyWeb.url }
        comps.queryItems = [URLQueryItem(name: "embed", value: "true")]
        return comps.url ?? AexyWeb.url
    }
}
