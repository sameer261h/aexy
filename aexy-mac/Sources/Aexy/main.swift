import AppKit
import SwiftUI
import UserNotifications
import AexyCore
#if canImport(Sparkle)
import Sparkle
#endif

// Menu-bar entry point for the Aexy companion app. Runs as an accessory; the
// main window (Open Aexy) hosts the SwiftUI app and handles web sign-in. The
// background activity-capture loop runs when a device is enrolled to a
// Tracker-enabled project.

@MainActor
final class AppController: NSObject, NSApplicationDelegate, NSMenuDelegate {
    private var statusItem: NSStatusItem?
    private var headerItem: NSMenuItem?
    private var statusText = "Not signed in"
    private var client: TrackerClient?
    private var capturing = false
    private var onboarding = false
    private let keychain = KeychainTokenStore()
    private var appState: AppState?
    private var mainWindow: NSWindow?
    private var notifTimer: Timer?
    #if canImport(Sparkle)
    // Self-update via Sparkle 2. Feed URL + EdDSA key come from Info.plist
    // (SUFeedURL / SUPublicEDKey); automatic background checks start at launch.
    private var updaterController: SPUStandardUpdaterController?
    #endif

    private var updaterAvailable: Bool {
        #if canImport(Sparkle)
        return true
        #else
        return false
        #endif
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        setupStatusItem()

        #if canImport(Sparkle)
        updaterController = SPUStandardUpdaterController(
            startingUpdater: true, updaterDelegate: nil, userDriverDelegate: nil
        )
        #endif

        let stored = TrackerConfig.fromKeychain(store: keychain)
        let state = AppState(apiBaseURL: apiBaseURL(), keychain: keychain, config: stored)
        state.onCaptureReady = { [weak self] cfg in self?.startCapture(with: cfg) }
        appState = state

        // Native notifications: request auth + poll every 60s (no-op when signed out).
        NativeNotifier.requestAuthorization()
        notifTimer = Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { [weak self] _ in
            Task { @MainActor in await self?.appState?.pollNotificationsTick() }
        }

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
        setHeader("Checked in — tracking")
        appState?.config = config
        Task { await client?.start() }
        rebuildMenu()
    }

    // MARK: - Status item

    private func setupStatusItem() {
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        item.button?.title = "○ Aexy"
        let menu = NSMenu()
        menu.delegate = self        // rebuilt by state on every open (NSMenuDelegate)
        item.menu = menu
        statusItem = item
        rebuildMenu()
    }

    /// Rebuild the dropdown to match the current state. Signed out shows just
    /// Sign in / Quit; signed in shows the office check-in controls + updates.
    private func rebuildMenu() {
        guard let menu = statusItem?.menu else { return }
        menu.removeAllItems()
        let signedIn = appState?.isSignedIn ?? false

        if signedIn {
            menu.addItem(NSMenuItem(title: "Open Aexy", action: #selector(openMainWindow), keyEquivalent: "o"))
            menu.addItem(.separator())
            let header = NSMenuItem(title: statusText, action: nil, keyEquivalent: "")
            header.isEnabled = false
            menu.addItem(header)
            headerItem = header
            menu.addItem(.separator())
            // Capture controls only when a device is enrolled for tracking.
            if client != nil {
                let title = capturing ? "Check out" : "Check in"
                menu.addItem(NSMenuItem(title: title, action: #selector(toggleCheckIn), keyEquivalent: "i"))
            }
            menu.addItem(NSMenuItem(title: "Sign out", action: #selector(signOut), keyEquivalent: ""))
            if updaterAvailable {
                menu.addItem(.separator())
                menu.addItem(NSMenuItem(title: "Check for Updates…", action: #selector(checkForUpdates), keyEquivalent: ""))
            }
            menu.addItem(.separator())
            menu.addItem(NSMenuItem(title: "Quit", action: #selector(quit), keyEquivalent: "q"))
        } else {
            menu.addItem(NSMenuItem(title: "Sign in", action: #selector(openMainWindow), keyEquivalent: ""))
            menu.addItem(.separator())
            menu.addItem(NSMenuItem(title: "Quit", action: #selector(quit), keyEquivalent: "q"))
        }
        for menuItem in menu.items where menuItem.action != nil { menuItem.target = self }
    }

    nonisolated func menuNeedsUpdate(_ menu: NSMenu) {
        MainActor.assumeIsolated { rebuildMenu() }
    }

    private func updateTitle(_ title: String) {
        statusItem?.button?.title = title
    }

    private func setHeader(_ text: String) {
        statusText = text
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

    /// Check in (start tracking) / Check out (stop) — the office metaphor for
    /// the capture loop. Data syncs automatically; there is no manual flush.
    @objc private func toggleCheckIn() {
        guard let client else { return }
        capturing.toggle()
        updateTitle(capturing ? "● Aexy" : "○ Aexy")
        setHeader(capturing ? "Checked in — tracking" : "Checked out")
        Task {
            if capturing { await client.start() } else { await client.stop() }
        }
    }

    @objc private func signOut() {
        Task { @MainActor in
            await client?.stop()
            client = nil
            capturing = false
            appState?.signOut()
            showSignedOut()
            rebuildMenu()
        }
    }

    @objc private func checkForUpdates() {
        #if canImport(Sparkle)
        updaterController?.checkForUpdates(nil)
        #endif
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
