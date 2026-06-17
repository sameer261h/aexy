import AppKit
import SwiftUI
import AexyCore

// Menu-bar entry point for the Aexy companion app. Runs as an accessory; the
// main window (Open Aexy) hosts the SwiftUI app and handles web sign-in. The
// background activity-capture loop runs when a device is enrolled to a
// Tracker-enabled project.

@MainActor
final class AppController: NSObject, NSApplicationDelegate {
    private var statusItem: NSStatusItem?
    private var headerItem: NSMenuItem?
    private var client: TrackerClient?
    private var capturing = false
    private var onboarding = false
    private let keychain = KeychainTokenStore()
    private var appState: AppState?
    private var mainWindow: NSWindow?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        setupStatusItem()

        let stored = TrackerConfig.fromKeychain(store: keychain)
        let state = AppState(apiBaseURL: apiBaseURL(), keychain: keychain, config: stored)
        state.onCaptureReady = { [weak self] cfg in self?.startCapture(with: cfg) }
        appState = state

        if let cfg = stored, let pid = cfg.projectId, !pid.isEmpty {
            // Previously enrolled → resume background capture.
            startCapture(with: cfg)
        } else if let token = ProcessInfo.processInfo.environment["AEXY_TRACKER_TOKEN"],
                  !token.isEmpty {
            beginTokenEnrollment(token: token)
        } else if stored != nil {
            // Signed in (companion features) but capture not enrolled.
            updateTitle("○ Aexy")
            setHeader("Aexy")
        } else {
            showSignedOut()
        }
    }

    private func apiBaseURL() -> URL {
        (ProcessInfo.processInfo.environment["AEXY_API_URL"]).flatMap(URL.init(string:))
            ?? URL(string: "https://server.aexy.io/api/v1")!
    }

    private func makeOnboarding() -> Onboarding {
        let wantedProjectId = ProcessInfo.processInfo.environment["AEXY_PROJECT_ID"]
        let authenticator = DeviceCodeAuthenticator(
            config: .aexy(authBase: URL(string: "https://server.aexy.io")!)
        )
        return Onboarding(
            apiBaseURL: apiBaseURL(),
            authenticator: authenticator,
            keychain: keychain,
            selectProject: { projects in
                if let id = wantedProjectId {
                    return projects.first { $0.id == id } ?? projects.first
                }
                return projects.first
            }
        )
    }

    /// Headless/dev: enroll with an env-supplied token, then start capture.
    private func beginTokenEnrollment(token: String) {
        guard !onboarding else { return }
        onboarding = true
        updateTitle("… Aexy")
        let flow = makeOnboarding()
        Task { @MainActor in
            do {
                let config = try await flow.enroll(usingToken: token)
                onboarding = false
                startCapture(with: config)
            } catch {
                onboarding = false
                updateTitle("⚠︎ Aexy")
                setHeader("Enrollment failed — check token / project / tracker_enabled")
                NSLog("Aexy: token enrollment failed: \(error)")
            }
        }
    }

    private func showSignedOut() {
        updateTitle("○ Aexy")
        setHeader("Not signed in — Open Aexy to sign in")
    }

    // MARK: - Capture

    private func startCapture(with config: TrackerConfig) {
        client = TrackerClient(config: config)
        capturing = true
        updateTitle("● Aexy")
        setHeader("Aexy")
        appState?.config = config
        Task { await client?.start() }
    }

    // MARK: - Status item

    private func setupStatusItem() {
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        item.button?.title = "○ Aexy"

        let menu = NSMenu()
        menu.addItem(NSMenuItem(title: "Open Aexy", action: #selector(openMainWindow), keyEquivalent: "o"))
        menu.addItem(.separator())
        let header = NSMenuItem(title: "Aexy", action: nil, keyEquivalent: "")
        header.isEnabled = false
        menu.addItem(header)
        headerItem = header
        menu.addItem(.separator())
        menu.addItem(NSMenuItem(title: "Pause / Resume", action: #selector(togglePause), keyEquivalent: "p"))
        menu.addItem(NSMenuItem(title: "Flush now", action: #selector(flushNow), keyEquivalent: "f"))
        menu.addItem(NSMenuItem(title: "Sign out", action: #selector(signOut), keyEquivalent: ""))
        menu.addItem(.separator())
        menu.addItem(NSMenuItem(title: "Quit", action: #selector(quit), keyEquivalent: "q"))
        for menuItem in menu.items where menuItem.action != nil { menuItem.target = self }
        item.menu = menu
        statusItem = item
    }

    private func updateTitle(_ title: String) {
        statusItem?.button?.title = title
    }

    private func setHeader(_ text: String) {
        headerItem?.title = text
    }

    // MARK: - Window

    /// Open (or focus) the Aexy main window. Web sign-in happens inside it.
    @objc private func openMainWindow() {
        guard let appState else { return }
        if mainWindow == nil {
            let hosting = NSHostingController(rootView: MainView(state: appState))
            let window = NSWindow(contentViewController: hosting)
            window.title = "Aexy"
            window.styleMask = [.titled, .closable, .miniaturizable, .resizable]
            window.setContentSize(NSSize(width: 980, height: 640))
            window.isReleasedWhenClosed = false
            window.center()
            mainWindow = window
        }
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
        mainWindow?.makeKeyAndOrderFront(nil)
        if appState.isSignedIn { Task { await appState.refresh() } }
    }

    // MARK: - Menu actions

    @objc private func togglePause() {
        guard let client else { return }
        capturing.toggle()
        updateTitle(capturing ? "● Aexy" : "❚❚ Aexy")
        Task {
            if capturing { await client.start() } else { await client.stop() }
        }
    }

    @objc private func flushNow() {
        Task { await client?.flush() }
    }

    @objc private func signOut() {
        Task { @MainActor in
            await client?.stop()
            client = nil
            capturing = false
            appState?.signOut()
            showSignedOut()
        }
    }

    @objc private func quit() {
        NSApp.terminate(nil)
    }
}

let app = NSApplication.shared
// Top-level code is nonisolated; the controller is @MainActor. We're genuinely
// on the main thread at process start, so assert that isolation.
let controller = MainActor.assumeIsolated { AppController() }
app.delegate = controller
app.run()
