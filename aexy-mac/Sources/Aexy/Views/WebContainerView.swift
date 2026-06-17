import SwiftUI
import WebKit
import AexyCore

// A single persistent embedded web view + a JS→native navigation bridge. Unlike
// EmbeddedWebView (recreated per route, no feedback), this retains one WKWebView
// for the whole session so page state survives native↔web switches, and reports
// the web router's location back to native — driving smart sidebar labels,
// resume-where-you-left-off, and the Recent list.

struct WebRecent: Codable, Identifiable, Equatable {
    var path: String
    var title: String
    var ts: Double
    var id: String { path }
}

@MainActor
final class WebNavigator: NSObject, ObservableObject, WKScriptMessageHandler {
    @Published var currentPath: String
    @Published var currentTitle: String = ""
    @Published var recents: [WebRecent]

    let webView: WKWebView

    private var workspaceId: String?
    private(set) var hasLoaded = false

    private static let pathKey = "aexy.web.lastPath"
    private static let recentsKey = "aexy.web.recents"
    private static let maxRecents = 8

    override init() {
        currentPath = UserDefaults.standard.string(forKey: Self.pathKey) ?? ""
        recents = Self.loadRecents()
        webView = WKWebView(frame: .zero, configuration: WKWebViewConfiguration())
        super.init()
        webView.configuration.userContentController.add(self, name: "aexyNav")
        installUserScripts()
    }

    // MARK: - Configuration / scripts

    func configure(workspaceId: String?) {
        guard workspaceId != self.workspaceId else { return }
        self.workspaceId = workspaceId
        installUserScripts()
    }

    private func installUserScripts() {
        let ucc = webView.configuration.userContentController
        ucc.removeAllUserScripts()
        let wsSeed = workspaceId.map { "localStorage.setItem('current_workspace_id','\($0)');" } ?? ""
        let src = """
        try { localStorage.setItem('aexy_embed','1'); \(wsSeed) } catch (e) {}
        (function () {
          function post() {
            try {
              window.webkit.messageHandlers.aexyNav.postMessage({
                path: location.pathname + location.search,
                title: document.title || ''
              });
            } catch (e) {}
          }
          var push = history.pushState;
          history.pushState = function () { push.apply(this, arguments); post(); };
          var replace = history.replaceState;
          history.replaceState = function () { replace.apply(this, arguments); post(); };
          window.addEventListener('popstate', post);
          window.addEventListener('load', post);
          document.addEventListener('DOMContentLoaded', function () {
            post();
            var t = document.querySelector('title');
            if (t) { new MutationObserver(post).observe(t, { childList: true }); }
          });
          setTimeout(post, 400);
        })();
        """
        ucc.addUserScript(
            WKUserScript(source: src, injectionTime: .atDocumentStart, forMainFrameOnly: true)
        )
    }

    // MARK: - Navigation

    func navigate(to route: String) {
        hasLoaded = true
        webView.load(URLRequest(url: Self.url(for: route)))
    }

    /// Re-seed the workspace and reload so the embedded app follows the native
    /// workspace switcher.
    func reloadForWorkspace(_ ws: String?) {
        configure(workspaceId: ws)
        if hasLoaded { webView.reload() }
    }

    private static func url(for route: String) -> URL {
        let path = route.drop(while: { $0 == "/" })
        guard var comps = URLComponents(
            url: AexyWeb.url.appendingPathComponent(String(path)),
            resolvingAgainstBaseURL: false
        ) else { return AexyWeb.url }
        var items = comps.queryItems ?? []
        if !items.contains(where: { $0.name == "embed" }) {
            items.append(URLQueryItem(name: "embed", value: "true"))
        }
        comps.queryItems = items
        return comps.url ?? AexyWeb.url
    }

    // MARK: - Bridge

    nonisolated func userContentController(
        _ controller: WKUserContentController, didReceive message: WKScriptMessage
    ) {
        // WKScriptMessageHandler callbacks are delivered on the main thread.
        MainActor.assumeIsolated {
            guard let body = message.body as? [String: Any] else { return }
            record(path: (body["path"] as? String) ?? "", title: (body["title"] as? String) ?? "")
        }
    }

    private func record(path: String, title: String) {
        guard !path.isEmpty else { return }
        currentPath = path
        if !title.isEmpty { currentTitle = title }
        UserDefaults.standard.set(path, forKey: Self.pathKey)

        // Auth pages aren't worth resuming/recents.
        if path.hasPrefix("/login") || path.hasPrefix("/auth") { return }
        let display = title.isEmpty ? Self.prettyName(path) : title
        var list = recents.filter { $0.path != path }
        list.insert(
            WebRecent(path: path, title: display, ts: Date().timeIntervalSince1970), at: 0
        )
        if list.count > Self.maxRecents { list = Array(list.prefix(Self.maxRecents)) }
        recents = list
        saveRecents()
    }

    /// Fallback label from a path, e.g. "/crm/deals" → "Deals".
    static func prettyName(_ path: String) -> String {
        let last = path.split(separator: "?").first.map(String.init) ?? path
        let seg = last.split(separator: "/").last.map(String.init) ?? "Page"
        return seg.replacingOccurrences(of: "-", with: " ").capitalized
    }

    // MARK: - Persistence

    private func saveRecents() {
        if let data = try? JSONEncoder().encode(recents) {
            UserDefaults.standard.set(data, forKey: Self.recentsKey)
        }
    }

    private static func loadRecents() -> [WebRecent] {
        guard let data = UserDefaults.standard.data(forKey: recentsKey),
              let list = try? JSONDecoder().decode([WebRecent].self, from: data)
        else { return [] }
        return list
    }
}

/// Mounts the navigator's retained web view. Returning the shared instance keeps
/// the page alive across native↔web switches (no reload).
struct WebContainerView: NSViewRepresentable {
    let navigator: WebNavigator
    func makeNSView(context: Context) -> WKWebView { navigator.webView }
    func updateNSView(_ nsView: WKWebView, context: Context) {}
}
