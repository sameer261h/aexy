import Foundation

#if canImport(AppKit)
import AppKit
#endif
#if canImport(CoreGraphics)
import CoreGraphics
#endif

// Semantic-signal collectors (AEXY_TRACKER.md §2). Metadata-first: frontmost app,
// window title (best-effort via Accessibility), idle state, plus the richer
// attribution signals — file/git context, dev context (terminal/editor), and
// browser context. Everything here is best-effort and nil-safe: missing
// permissions or unavailable APIs degrade to nil rather than crashing.
// Screenshots are out of scope for v1 scaffold (optional evidence only).

public struct SampleContext: Sendable {
    public var activeApp: ActiveApp
    public var idleSeconds: Double
    public var system: SystemContext
    // Richer semantic signals (AEXY_TRACKER.md §2; ingest schema §4). All optional —
    // populated best-effort, nil when the source/permission is unavailable.
    public var fileContext: FileContext?
    public var devContext: DevContext?
    public var browser: BrowserContext?

    public init(
        activeApp: ActiveApp,
        idleSeconds: Double,
        system: SystemContext,
        fileContext: FileContext? = nil,
        devContext: DevContext? = nil,
        browser: BrowserContext? = nil
    ) {
        self.activeApp = activeApp
        self.idleSeconds = idleSeconds
        self.system = system
        self.fileContext = fileContext
        self.devContext = devContext
        self.browser = browser
    }
}

public protocol ActivityCollector: Sendable {
    func sample() -> SampleContext
}

/// Returns how long the user has been idle (no keyboard/mouse), in seconds.
public func systemIdleSeconds() -> Double {
    #if canImport(CoreGraphics)
    let t = CGEventSource.secondsSinceLastEventType(.combinedSessionState,
                                                    eventType: .init(rawValue: ~0)!)
    return t
    #else
    return 0
    #endif
}

public struct MacActivityCollector: ActivityCollector {
    public init() {}

    public func sample() -> SampleContext {
        let app = frontmostApp()
        let system = SystemContext(
            onBattery: nil,
            displays: displayCount(),
            online: true,
            network: nil
        )

        // Best-effort enrichment (AEXY_TRACKER.md §2). The focused document path
        // anchors file/git context; the window title feeds dev/browser parsing.
        let docPath = focusedDocumentPath()
        let fileContext = GitFileCollector.fileContext(forDocumentAt: docPath)
        let devContext = DevContextCollector.devContext(
            bundleId: app.bundleId,
            windowTitle: app.windowTitle,
            documentPath: docPath
        )
        let browser = BrowserCollector.browserContext(bundleId: app.bundleId)

        return SampleContext(
            activeApp: app,
            idleSeconds: systemIdleSeconds(),
            system: system,
            fileContext: fileContext,
            devContext: devContext,
            browser: browser
        )
    }

    private func frontmostApp() -> ActiveApp {
        #if canImport(AppKit)
        if let app = NSWorkspace.shared.frontmostApplication {
            return ActiveApp(
                name: app.localizedName ?? "Unknown",
                bundleId: app.bundleIdentifier ?? "unknown",
                windowTitle: focusedWindowTitle()
            )
        }
        #endif
        return ActiveApp(name: "Unknown", bundleId: "unknown", windowTitle: nil)
    }

    private func displayCount() -> Int {
        #if canImport(AppKit)
        return NSScreen.screens.count
        #else
        return 1
        #endif
    }

    /// Best-effort focused window title via the Accessibility API. Returns nil
    /// without the Accessibility permission (graceful — capture is metadata-first).
    private func focusedWindowTitle() -> String? {
        #if canImport(AppKit)
        guard AXIsProcessTrusted() else { return nil }
        guard let app = NSWorkspace.shared.frontmostApplication else { return nil }
        let appElement = AXUIElementCreateApplication(app.processIdentifier)
        var window: AnyObject?
        guard AXUIElementCopyAttributeValue(appElement, kAXFocusedWindowAttribute as CFString, &window) == .success,
              let windowElement = window else { return nil }
        var title: AnyObject?
        // swiftlint:disable:next force_cast
        guard AXUIElementCopyAttributeValue(windowElement as! AXUIElement, kAXTitleAttribute as CFString, &title) == .success else {
            return nil
        }
        return title as? String
        #else
        return nil
        #endif
    }

    /// Best-effort focused document path via the Accessibility API. Tries the
    /// focused window's `AXDocument` attribute (and the app-level `AXDocument`),
    /// which editors/document apps expose as a file URL. Returns nil without the
    /// Accessibility permission or when the frontmost app exposes no document.
    private func focusedDocumentPath() -> String? {
        #if canImport(AppKit)
        guard AXIsProcessTrusted() else { return nil }
        guard let app = NSWorkspace.shared.frontmostApplication else { return nil }
        let appElement = AXUIElementCreateApplication(app.processIdentifier)

        // App-level AXDocument (some apps expose it on the application element).
        if let path = documentPath(of: appElement) { return path }

        // Otherwise the focused window's AXDocument.
        var window: AnyObject?
        guard AXUIElementCopyAttributeValue(appElement, kAXFocusedWindowAttribute as CFString, &window) == .success,
              let windowElement = window else { return nil }
        // swiftlint:disable:next force_cast
        return documentPath(of: windowElement as! AXUIElement)
        #else
        return nil
        #endif
    }

    #if canImport(AppKit)
    /// Reads the `AXDocument` attribute of an element and normalizes it to a
    /// filesystem path. `AXDocument` is conventionally a `file://` URL string.
    private func documentPath(of element: AXUIElement) -> String? {
        var value: AnyObject?
        guard AXUIElementCopyAttributeValue(element, kAXDocumentAttribute as CFString, &value) == .success,
              let raw = value as? String else { return nil }
        return GitFileCollector.normalizeDocumentPath(raw)
    }
    #endif
}

// MARK: - File / git context (AEXY_TRACKER.md §2: "Document / file context")

/// Derives file + git context (path / repo / branch) for a focused document.
/// All filesystem IO is guarded; any failure degrades to a partial or nil result.
public enum GitFileCollector {

    /// Build a `FileContext` for a focused document path, walking up to the
    /// enclosing `.git` for repo + branch. Returns nil when there is no path.
    public static func fileContext(forDocumentAt path: String?) -> FileContext? {
        guard let path, !path.isEmpty else { return nil }
        var ctx = FileContext()
        ctx.path = path
        if let git = gitInfo(forPath: path) {
            ctx.repo = git.repo
            ctx.branch = git.branch
        }
        return ctx
    }

    /// `AXDocument` is conventionally a `file://` URL; normalize to a plain path.
    /// Falls back to the raw string when it isn't a URL.
    public static func normalizeDocumentPath(_ raw: String) -> String? {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        if trimmed.hasPrefix("file://"), let url = URL(string: trimmed) {
            return url.path
        }
        return trimmed
    }

    public struct GitInfo: Equatable, Sendable {
        public var repo: String?
        public var branch: String?
    }

    /// Walk up parent directories from `path` to find the enclosing `.git`,
    /// deriving the repo directory name and current branch. Nil if none found.
    public static func gitInfo(forPath path: String,
                               fileManager: FileManager = .default) -> GitInfo? {
        guard let root = gitRoot(forPath: path, fileManager: fileManager) else { return nil }
        let repo = root.lastPathComponent
        let head = root.appendingPathComponent(".git/HEAD")
        let branch = parseBranch(headContents: try? String(contentsOf: head, encoding: .utf8))
        return GitInfo(repo: repo.isEmpty ? nil : repo, branch: branch)
    }

    /// The repository working-directory URL containing `path`, found by walking
    /// up parents until a `.git` directory exists. Nil if none is found.
    public static func gitRoot(forPath path: String,
                               fileManager: FileManager = .default) -> URL? {
        var dir = URL(fileURLWithPath: path).standardizedFileURL
        // Start at the containing directory if `path` is a file (best-effort: we
        // walk up regardless, so checking is cheap and avoids a stat on each call).
        var isDir: ObjCBool = false
        if fileManager.fileExists(atPath: dir.path, isDirectory: &isDir), !isDir.boolValue {
            dir = dir.deletingLastPathComponent()
        } else if !fileManager.fileExists(atPath: dir.path) {
            // Path may be a file that no longer exists; still walk from its parent.
            dir = dir.deletingLastPathComponent()
        }

        // Bound the walk so a pathological path can never loop forever.
        var guardCount = 0
        while guardCount < 256 {
            let gitPath = dir.appendingPathComponent(".git")
            if fileManager.fileExists(atPath: gitPath.path) {
                return dir
            }
            let parent = dir.deletingLastPathComponent()
            // Reached the filesystem root (parent == self).
            if parent.path == dir.path { break }
            dir = parent
            guardCount += 1
        }
        return nil
    }

    /// Parse a branch name from `.git/HEAD` contents.
    /// `ref: refs/heads/<branch>` → `<branch>`; a detached SHA → short SHA.
    /// Returns nil for empty/unrecognized contents.
    public static func parseBranch(headContents: String?) -> String? {
        guard let raw = headContents?.trimmingCharacters(in: .whitespacesAndNewlines),
              !raw.isEmpty else { return nil }

        if raw.hasPrefix("ref:") {
            // e.g. "ref: refs/heads/feature/foo" → "feature/foo"
            let refValue = raw.dropFirst("ref:".count).trimmingCharacters(in: .whitespaces)
            let marker = "refs/heads/"
            if let range = refValue.range(of: marker) {
                let branch = String(refValue[range.upperBound...])
                return branch.isEmpty ? nil : branch
            }
            // Some other ref form (e.g. refs/tags/...) — return the last component.
            let last = refValue.split(separator: "/").last.map(String.init)
            return last?.isEmpty == false ? last : nil
        }

        // Detached HEAD: HEAD holds a raw 40-char (or 64 for SHA-256) commit SHA.
        let sha = raw.split(whereSeparator: { $0 == " " || $0 == "\n" }).first.map(String.init) ?? raw
        if isHexSHA(sha) {
            return String(sha.prefix(7))
        }
        return nil
    }

    private static func isHexSHA(_ s: String) -> Bool {
        guard s.count >= 7 else { return false }
        return s.allSatisfy { $0.isHexDigit }
    }
}

// MARK: - Dev context (AEXY_TRACKER.md §2: "Dev context")

/// Derives terminal cwd / last command (terminals) or editor file (editors) from
/// the frontmost app's window title + focused document. Best-effort and nil-safe:
/// terminal title formats vary, so parsing is heuristic and degrades to nil.
public enum DevContextCollector {

    public static let terminalBundleIds: Set<String> = [
        "com.apple.Terminal",
        "com.googlecode.iterm2"
    ]

    public static let editorBundleIds: Set<String> = [
        "com.microsoft.VSCode",
        "com.microsoft.VSCodeInsiders",
        "com.todesktop.230313mzl4w4u92",   // Cursor
        "com.sublimetext.4",
        "com.apple.dt.Xcode",
        "dev.zed.Zed"
    ]

    /// Build a `DevContext` for the frontmost app. Returns nil when the app is
    /// neither a known terminal nor a known editor, or nothing could be parsed.
    public static func devContext(bundleId: String,
                                  windowTitle: String?,
                                  documentPath: String?) -> DevContext? {
        if terminalBundleIds.contains(bundleId) {
            let parsed = parseTerminalTitle(windowTitle)
            guard parsed.cwd != nil || parsed.lastCommand != nil else { return nil }
            var ctx = DevContext()
            ctx.terminalCwd = parsed.cwd
            ctx.lastCommand = parsed.lastCommand
            return ctx
        }

        if editorBundleIds.contains(bundleId) {
            let file = editorFile(windowTitle: windowTitle, documentPath: documentPath)
            guard let file else { return nil }
            var ctx = DevContext()
            ctx.editorFile = file
            return ctx
        }

        return nil
    }

    public struct TerminalParse: Equatable, Sendable {
        public var cwd: String?
        public var lastCommand: String?
    }

    /// Best-effort parse of a terminal window title into cwd + last command.
    /// Terminal.app default title is often "<cwd> — <command> — NNxNN" or
    /// "<dir> — -zsh"; iTerm commonly shows "<cwd> — <command>". We split on the
    /// em dash / hyphen-with-spaces separators and classify the segments: a
    /// segment that looks like a path (starts with "/" or "~") is the cwd; a
    /// trailing non-path, non-geometry segment is treated as the last command.
    public static func parseTerminalTitle(_ title: String?) -> TerminalParse {
        guard let title = title?.trimmingCharacters(in: .whitespacesAndNewlines),
              !title.isEmpty else { return TerminalParse(cwd: nil, lastCommand: nil) }

        // Split on the common separators (em dash, en dash, " - ").
        let separators = [" — ", " – ", " - "]
        var segments = [title]
        for sep in separators {
            segments = segments.flatMap { $0.components(separatedBy: sep) }
        }
        let parts = segments
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }

        var cwd: String?
        var lastCommand: String?
        for part in parts {
            if looksLikePath(part) {
                if cwd == nil { cwd = part }
            } else if isWindowGeometry(part) {
                continue
            } else {
                // Last non-path, non-geometry segment wins as the command/process.
                lastCommand = stripShellLeader(part)
            }
        }
        return TerminalParse(cwd: cwd, lastCommand: lastCommand)
    }

    /// Editor file from the focused document path (preferred) or window title.
    /// VS Code-style titles look like "<file> — <folder>"; we take the leading
    /// segment as the file. Returns nil if nothing usable is present.
    public static func editorFile(windowTitle: String?, documentPath: String?) -> String? {
        if let documentPath, !documentPath.isEmpty {
            return documentPath
        }
        guard let title = windowTitle?.trimmingCharacters(in: .whitespacesAndNewlines),
              !title.isEmpty else { return nil }
        let separators = [" — ", " – ", " - "]
        var segments = [title]
        for sep in separators {
            segments = segments.flatMap { $0.components(separatedBy: sep) }
        }
        let first = segments
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .first { !$0.isEmpty }
        // Drop VS Code's "●" dirty-indicator prefix if present.
        return first.map { $0.replacingOccurrences(of: "● ", with: "").trimmingCharacters(in: .whitespaces) }
            .flatMap { $0.isEmpty ? nil : $0 }
    }

    private static func looksLikePath(_ s: String) -> Bool {
        s.hasPrefix("/") || s.hasPrefix("~")
    }

    /// Matches Terminal.app's "120x30" window-size suffix segment.
    private static func isWindowGeometry(_ s: String) -> Bool {
        let parts = s.lowercased().split(separator: "x")
        guard parts.count == 2 else { return false }
        return parts.allSatisfy { !$0.isEmpty && $0.allSatisfy(\.isNumber) }
    }

    /// Strip a leading shell process marker (e.g. "-zsh" → "zsh").
    private static func stripShellLeader(_ s: String) -> String {
        s.hasPrefix("-") ? String(s.dropFirst()) : s
    }
}

// MARK: - Browser context (AEXY_TRACKER.md §2: "Browser context")

/// Reads the active tab URL + title from the frontmost browser via AppleScript.
/// Requires the macOS Automation permission at runtime; any error (no permission,
/// browser not scriptable, no front window) degrades to nil — never crashes.
///
/// Coverage is a bundle-id table keyed by AppleScript dialect:
///   • WebKit/Safari dialect  — `current tab of front window`, `name`/`URL`
///   • Chromium dialect       — `active tab of front window`, `title`/`URL`
/// Every Chromium fork below shares Chrome's scripting dictionary, so one
/// template covers them all.
///
/// Firefox is intentionally absent: its AppleScript dictionary exposes no tab
/// URL/title, so it can't be scripted here. Firefox still yields a window title
/// through the Accessibility path (`activeApp.windowTitle`) — just no URL.
public enum BrowserCollector {

    public enum Dialect: Sendable { case safari, chromium }

    public struct Browser: Sendable {
        public let appName: String   // AppleScript application name
        public let dialect: Dialect
    }

    public static let safariBundleId = "com.apple.Safari"
    public static let chromeBundleId = "com.google.Chrome"

    /// bundle id → scriptable browser. Chromium forks share Chrome's dictionary.
    public static let browsers: [String: Browser] = [
        // WebKit / Safari dialect
        "com.apple.Safari": Browser(appName: "Safari", dialect: .safari),
        "com.apple.SafariTechnologyPreview": Browser(appName: "Safari Technology Preview", dialect: .safari),
        // Chromium dialect
        "com.google.Chrome": Browser(appName: "Google Chrome", dialect: .chromium),
        "com.google.Chrome.beta": Browser(appName: "Google Chrome Beta", dialect: .chromium),
        "com.google.Chrome.canary": Browser(appName: "Google Chrome Canary", dialect: .chromium),
        "org.chromium.Chromium": Browser(appName: "Chromium", dialect: .chromium),
        "com.brave.Browser": Browser(appName: "Brave Browser", dialect: .chromium),
        "com.brave.Browser.beta": Browser(appName: "Brave Browser Beta", dialect: .chromium),
        "com.brave.Browser.nightly": Browser(appName: "Brave Browser Nightly", dialect: .chromium),
        "com.microsoft.edgemac": Browser(appName: "Microsoft Edge", dialect: .chromium),
        "com.microsoft.edgemac.Beta": Browser(appName: "Microsoft Edge Beta", dialect: .chromium),
        "com.microsoft.edgemac.Dev": Browser(appName: "Microsoft Edge Dev", dialect: .chromium),
        "com.vivaldi.Vivaldi": Browser(appName: "Vivaldi", dialect: .chromium),
        // Best-effort: Arc/Opera expose a Chrome-like dictionary; if a build
        // differs the script simply errors and we fall back to nil (no URL).
        "company.thebrowser.Browser": Browser(appName: "Arc", dialect: .chromium),
        "com.operasoftware.Opera": Browser(appName: "Opera", dialect: .chromium),
    ]

    /// Pure, testable: build the (url, title) AppleScript pair for a bundle id,
    /// or nil if the app isn't a supported scriptable browser.
    public static func appleScripts(forBundleId bundleId: String) -> (url: String, title: String)? {
        guard let b = browsers[bundleId] else { return nil }
        switch b.dialect {
        case .safari:
            return (
                url: "tell application \"\(b.appName)\" to get URL of current tab of front window",
                title: "tell application \"\(b.appName)\" to get name of current tab of front window"
            )
        case .chromium:
            return (
                url: "tell application \"\(b.appName)\" to get URL of active tab of front window",
                title: "tell application \"\(b.appName)\" to get title of active tab of front window"
            )
        }
    }

    /// Returns the active tab's URL + title when the frontmost app is a supported
    /// browser, else nil. Each value is independently best-effort.
    public static func browserContext(bundleId: String) -> BrowserContext? {
        #if canImport(AppKit)
        guard let scripts = appleScripts(forBundleId: bundleId) else { return nil }

        let url = runAppleScriptString(scripts.url)
        let title = runAppleScriptString(scripts.title)
        guard url != nil || title != nil else { return nil }
        var ctx = BrowserContext()
        ctx.url = url
        ctx.title = title
        return ctx
        #else
        return nil
        #endif
    }

    #if canImport(AppKit)
    /// Run an AppleScript that returns a string. Returns nil on any error
    /// (missing Automation permission, scripting failure) or empty result.
    public static func runAppleScriptString(_ source: String) -> String? {
        guard let script = NSAppleScript(source: source) else { return nil }
        var error: NSDictionary?
        let descriptor = script.executeAndReturnError(&error)
        if error != nil { return nil }
        guard let value = descriptor.stringValue, !value.isEmpty else { return nil }
        return value
    }
    #endif
}
