import XCTest
@testable import AexyCore

// Unit tests for the PURE collector logic that needs no live UI / permissions:
// the `.git/HEAD` branch parser, the git-root directory walk, and the
// terminal/editor title heuristics (docs/aexy-tracker.md §2).

final class GitFileCollectorTests: XCTestCase {

    // MARK: - parseBranch (.git/HEAD)

    func testParseBranchSymbolicRef() {
        XCTAssertEqual(GitFileCollector.parseBranch(headContents: "ref: refs/heads/main"), "main")
    }

    func testParseBranchSymbolicRefWithSlashes() {
        XCTAssertEqual(
            GitFileCollector.parseBranch(headContents: "ref: refs/heads/feature/rich-collectors\n"),
            "feature/rich-collectors"
        )
    }

    func testParseBranchTrimsWhitespace() {
        XCTAssertEqual(GitFileCollector.parseBranch(headContents: "  ref: refs/heads/dev \n"), "dev")
    }

    func testParseBranchDetachedHeadShortSHA() {
        let sha = "9fceb02d0ae598e95dc970b74767f19372d61af8"
        XCTAssertEqual(GitFileCollector.parseBranch(headContents: sha), "9fceb02")
    }

    func testParseBranchEmptyOrNil() {
        XCTAssertNil(GitFileCollector.parseBranch(headContents: nil))
        XCTAssertNil(GitFileCollector.parseBranch(headContents: ""))
        XCTAssertNil(GitFileCollector.parseBranch(headContents: "   \n"))
    }

    func testParseBranchNonRefNonSHA() {
        XCTAssertNil(GitFileCollector.parseBranch(headContents: "not a ref or sha"))
    }

    // MARK: - gitRoot / gitInfo (directory walk)

    /// Build a temp tree: <root>/.git/HEAD + <root>/src/app.swift and assert the
    /// walk finds the root and derives repo + branch.
    func testGitRootAndInfoWalk() throws {
        let fm = FileManager.default
        let root = fm.temporaryDirectory
            .appendingPathComponent("aexy-git-\(UUID().uuidString)/myrepo", isDirectory: true)
        let gitDir = root.appendingPathComponent(".git", isDirectory: true)
        let srcDir = root.appendingPathComponent("src", isDirectory: true)
        try fm.createDirectory(at: gitDir, withIntermediateDirectories: true)
        try fm.createDirectory(at: srcDir, withIntermediateDirectories: true)
        try "ref: refs/heads/main\n".write(
            to: gitDir.appendingPathComponent("HEAD"), atomically: true, encoding: .utf8)
        let file = srcDir.appendingPathComponent("app.swift")
        try "// hi".write(to: file, atomically: true, encoding: .utf8)
        defer { try? fm.removeItem(at: root.deletingLastPathComponent()) }

        let foundRoot = GitFileCollector.gitRoot(forPath: file.path)
        XCTAssertEqual(foundRoot?.standardizedFileURL.path, root.standardizedFileURL.path)

        let info = GitFileCollector.gitInfo(forPath: file.path)
        XCTAssertEqual(info?.repo, "myrepo")
        XCTAssertEqual(info?.branch, "main")
    }

    func testGitRootNilWhenNoGit() throws {
        let fm = FileManager.default
        let dir = fm.temporaryDirectory
            .appendingPathComponent("aexy-nogit-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: dir, withIntermediateDirectories: true)
        let file = dir.appendingPathComponent("loose.txt")
        try "x".write(to: file, atomically: true, encoding: .utf8)
        defer { try? fm.removeItem(at: dir) }

        // Temp dir lives under a non-repo tree; no .git should be found within bound.
        XCTAssertNil(GitFileCollector.gitRoot(forPath: file.path))
    }

    func testFileContextNilWithoutPath() {
        XCTAssertNil(GitFileCollector.fileContext(forDocumentAt: nil))
        XCTAssertNil(GitFileCollector.fileContext(forDocumentAt: ""))
    }

    func testFileContextCarriesPath() {
        let ctx = GitFileCollector.fileContext(forDocumentAt: "/tmp/no/such/file.swift")
        XCTAssertEqual(ctx?.path, "/tmp/no/such/file.swift")
    }

    // MARK: - normalizeDocumentPath

    func testNormalizeFileURL() {
        XCTAssertEqual(
            GitFileCollector.normalizeDocumentPath("file:///Users/me/AEXY_TRACKER.md"),
            "/Users/me/AEXY_TRACKER.md"
        )
    }

    func testNormalizePlainPath() {
        XCTAssertEqual(GitFileCollector.normalizeDocumentPath("/Users/me/x.swift"), "/Users/me/x.swift")
    }

    func testNormalizeEmpty() {
        XCTAssertNil(GitFileCollector.normalizeDocumentPath("   "))
    }
}

final class DevContextCollectorTests: XCTestCase {

    func testTerminalTitleCwdAndCommand() {
        let parsed = DevContextCollector.parseTerminalTitle("~/code/aexy — git status — 120x30")
        XCTAssertEqual(parsed.cwd, "~/code/aexy")
        XCTAssertEqual(parsed.lastCommand, "git status")
    }

    func testTerminalTitleShellLeaderStripped() {
        let parsed = DevContextCollector.parseTerminalTitle("/Users/me/proj — -zsh")
        XCTAssertEqual(parsed.cwd, "/Users/me/proj")
        XCTAssertEqual(parsed.lastCommand, "zsh")
    }

    func testTerminalTitleEmpty() {
        let parsed = DevContextCollector.parseTerminalTitle("")
        XCTAssertNil(parsed.cwd)
        XCTAssertNil(parsed.lastCommand)
    }

    func testDevContextForTerminal() {
        let ctx = DevContextCollector.devContext(
            bundleId: "com.apple.Terminal",
            windowTitle: "~/code/aexy — git status",
            documentPath: nil
        )
        XCTAssertEqual(ctx?.terminalCwd, "~/code/aexy")
        XCTAssertEqual(ctx?.lastCommand, "git status")
        XCTAssertNil(ctx?.editorFile)
    }

    func testDevContextForEditorPrefersDocumentPath() {
        let ctx = DevContextCollector.devContext(
            bundleId: "com.microsoft.VSCode",
            windowTitle: "app.swift — myrepo",
            documentPath: "/Users/me/myrepo/app.swift"
        )
        XCTAssertEqual(ctx?.editorFile, "/Users/me/myrepo/app.swift")
        XCTAssertNil(ctx?.terminalCwd)
    }

    func testDevContextForEditorFallsBackToTitle() {
        let ctx = DevContextCollector.devContext(
            bundleId: "com.microsoft.VSCode",
            windowTitle: "● app.swift — myrepo",
            documentPath: nil
        )
        XCTAssertEqual(ctx?.editorFile, "app.swift")
    }

    func testDevContextNilForUnknownApp() {
        XCTAssertNil(DevContextCollector.devContext(
            bundleId: "com.tinyspeck.slackmacgap",
            windowTitle: "general",
            documentPath: nil
        ))
    }
}

final class BrowserCollectorTests: XCTestCase {
    func testSafariUsesWebKitDialect() {
        let s = BrowserCollector.appleScripts(forBundleId: "com.apple.Safari")
        XCTAssertNotNil(s)
        XCTAssertTrue(s!.url.contains("current tab of front window"))
        XCTAssertTrue(s!.title.contains("get name of current tab"))
        XCTAssertTrue(s!.url.contains("\"Safari\""))
    }

    func testChromeUsesChromiumDialect() {
        let s = BrowserCollector.appleScripts(forBundleId: "com.google.Chrome")
        XCTAssertNotNil(s)
        XCTAssertTrue(s!.url.contains("active tab of front window"))
        XCTAssertTrue(s!.title.contains("get title of active tab"))
        XCTAssertTrue(s!.url.contains("\"Google Chrome\""))
    }

    func testChromiumForksShareChromeDialect() {
        // Brave / Edge / Vivaldi / Chromium all speak the Chrome dictionary.
        for (bundle, appName) in [
            ("com.brave.Browser", "Brave Browser"),
            ("com.microsoft.edgemac", "Microsoft Edge"),
            ("com.vivaldi.Vivaldi", "Vivaldi"),
            ("org.chromium.Chromium", "Chromium"),
        ] {
            let s = BrowserCollector.appleScripts(forBundleId: bundle)
            XCTAssertNotNil(s, "missing \(bundle)")
            XCTAssertTrue(s!.url.contains("active tab of front window"))
            XCTAssertTrue(s!.url.contains("\"\(appName)\""))
        }
    }

    func testUnsupportedBrowserReturnsNil() {
        // Firefox is not scriptable for tab URL — relies on the AX window title.
        XCTAssertNil(BrowserCollector.appleScripts(forBundleId: "org.mozilla.firefox"))
        XCTAssertNil(BrowserCollector.appleScripts(forBundleId: "com.tinyspeck.slackmacgap"))
    }
}
