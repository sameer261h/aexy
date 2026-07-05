import SwiftUI
import WebKit

// Embeds the Aexy web app for deep features (full boards, planning, docs) that
// we don't re-implement natively.
//
// Auth is shared, NOT injected: this view and the sign-in LoginWebView use the
// default persistent WKWebsiteDataStore, so once the user has signed in on the
// web the embedded app is already authenticated with its real session. (Earlier
// this view re-injected the opaque API token into localStorage on every load,
// clobbering the web app's JWT and causing a "session expired" redirect loop.)
//
// Web origin: AEXY_WEB_URL env, else https://aexy.io (the backend lives at
// server.aexy.io; the web app is the apex domain).
struct AexyWebView: NSViewRepresentable {
    func makeNSView(context: Context) -> WKWebView {
        let webView = WKWebView()
        webView.load(URLRequest(url: AexyWeb.url))
        return webView
    }

    func updateNSView(_ nsView: WKWebView, context: Context) {}
}

enum AexyWebSession {
    /// Clear cookies + localStorage etc. for a true sign-out, so the embedded
    /// web view isn't left logged in after the native app signs out.
    static func clear(completion: @escaping () -> Void) {
        let store = WKWebsiteDataStore.default()
        let types = WKWebsiteDataStore.allWebsiteDataTypes()
        store.removeData(ofTypes: types, modifiedSince: .distantPast) {
            completion()
        }
    }
}
