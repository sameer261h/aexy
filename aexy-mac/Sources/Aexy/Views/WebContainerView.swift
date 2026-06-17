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
        currentPath = Self.stripQuery(UserDefaults.standard.string(forKey: Self.pathKey) ?? "")
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
                path: location.pathname,
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

    /// Drop any query string (raw "?" or a previously double-encoded "%3F") so
    /// stored/resumed paths stay clean and don't re-encode into the path segment.
    static func stripQuery(_ p: String) -> String {
        var s = p
        if let i = s.firstIndex(of: "?") { s = String(s[..<i]) }
        if let r = s.range(of: "%3F", options: .caseInsensitive) { s = String(s[..<r.lowerBound]) }
        return s
    }

    private static func url(for route: String) -> URL {
        let path = stripQuery(route).drop(while: { $0 == "/" })
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
            record(rawPath: (body["path"] as? String) ?? "", title: (body["title"] as? String) ?? "")
        }
    }

    private func record(rawPath: String, title: String) {
        let path = Self.stripQuery(rawPath)
        guard !path.isEmpty else { return }
        currentPath = path
        let name = Self.displayName(path: path, title: title)
        currentTitle = name
        UserDefaults.standard.set(path, forKey: Self.pathKey)

        // Auth pages aren't worth resuming/recents.
        if path.hasPrefix("/login") || path.hasPrefix("/auth") { return }
        var list = recents.filter { $0.path != path }
        list.insert(
            WebRecent(path: path, title: name, ts: Date().timeIntervalSince1970), at: 0
        )
        if list.count > Self.maxRecents { list = Array(list.prefix(Self.maxRecents)) }
        recents = list
        saveRecents()
    }

    /// A distinct, brand-free label for a page. The web app uses one constant
    /// `<title>` ("Aexy | AI Superapp for Companies") everywhere, so a brand-free
    /// title is preferred when present, otherwise we derive a name from the path.
    static func displayName(path: String, title: String) -> String {
        if let cleaned = cleanTitle(title) { return cleaned }
        return prettyName(path)
    }

    /// Strip brand/tagline segments ("Aexy", "… Superapp …"); nil if nothing
    /// meaningful remains (e.g. the constant brand title).
    static func cleanTitle(_ title: String) -> String? {
        let parts = title
            .components(separatedBy: CharacterSet(charactersIn: "|—–·"))
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
        func isBrand(_ s: String) -> Bool {
            let l = s.lowercased()
            return l.contains("aexy") || l.contains("superapp")
        }
        return parts.first(where: { !isBrand($0) })
    }

    /// Name from a path, e.g. "/crm" → "CRM", "/crm/deals" → "CRM · Deals".
    static func prettyName(_ path: String) -> String {
        let clean = path.split(separator: "?").first.map(String.init) ?? path
        let segs = clean.split(separator: "/").map(String.init).filter { !$0.isEmpty }
        guard !segs.isEmpty else { return "Home" }
        func cap(_ s: String) -> String {
            if s.count <= 3 { return s.uppercased() }   // crm → CRM, ai → AI
            return s.replacingOccurrences(of: "-", with: " ")
                .split(separator: " ").map { $0.capitalized }.joined(separator: " ")
        }
        if segs.count == 1 { return cap(segs[0]) }
        return cap(segs[0]) + " · " + cap(segs[segs.count - 1])
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
        // Migrate any pre-fix entries that captured the query string in the path.
        var seen = Set<String>()
        var out: [WebRecent] = []
        for r in list {
            let p = stripQuery(r.path)
            guard !p.isEmpty, !seen.contains(p) else { continue }
            seen.insert(p)
            let title = r.path == p ? r.title : prettyName(p)
            out.append(WebRecent(path: p, title: title, ts: r.ts))
        }
        return out
    }
}

/// Mounts the navigator's retained web view. Returning the shared instance keeps
/// the page alive across native↔web switches (no reload).
struct WebContainerView: NSViewRepresentable {
    let navigator: WebNavigator
    func makeNSView(context: Context) -> WKWebView { navigator.webView }
    func updateNSView(_ nsView: WKWebView, context: Context) {}
}
