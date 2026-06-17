import AppKit
import AexyTrackerCore

// Menu-bar entry point. Runs as an accessory (no Dock icon), shows a status item,
// and drives the TrackerClient capture loop. On launch it prefers a Keychain
// credential (docs/aexy-tracker.md); otherwise the user signs in via the browser
// (Sign in → GitHub/Google/Microsoft), which captures a token on a loopback
// listener and starts capture.

final class AppController: NSObject, NSApplicationDelegate {
    private var statusItem: NSStatusItem?
    private var client: TrackerClient?
    private var capturing = false
    private var onboarding = false
    private let keychain = KeychainTokenStore()

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        setupStatusItem()

        // 1. Persisted credential from a prior sign-in/enrollment.
        if let config = TrackerConfig.fromKeychain(store: keychain) {
            startCapture(with: config)
        // 2. Token supplied via env (headless/dev): enroll with it, then capture.
        } else if let token = ProcessInfo.processInfo.environment["AEXY_TRACKER_TOKEN"],
                  !token.isEmpty {
            beginTokenEnrollment(token: token)
        // 3. Not configured — wait for the user to sign in via the menu.
        } else {
            showSignedOut()
        }
    }

    private func apiBaseURL() -> URL {
        (ProcessInfo.processInfo.environment["AEXY_API_URL"]).flatMap(URL.init(string:))
            ?? URL(string: "https://server.aexy.io/api/v1")!
    }

    /// Build an Onboarding flow. `authenticator` is required by the initializer
    /// but unused by the browser / env-token paths.
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

    // MARK: - Sign in (browser OAuth)

    @objc private func signIn(_ sender: NSMenuItem) {
        guard let provider = sender.representedObject as? String else { return }
        beginBrowserLogin(provider: provider)
    }

    /// Open the browser to sign in, capture the token on a loopback listener,
    /// exchange it for a long-lived API token, enroll, and start capture.
    private func beginBrowserLogin(provider: String) {
        guard !onboarding else { return }
        onboarding = true
        updateTitle("… Aexy")
        setHeader("Opening browser to sign in…")

        let flow = makeOnboarding()
        Task { @MainActor in
            do {
                let config = try await flow.signInViaBrowser(provider: provider)
                onboarding = false
                setHeader("Aexy Tracker")
                startCapture(with: config)
            } catch OnboardingError.noTrackerProjects {
                onboarding = false
                updateTitle("⚠︎ Aexy")
                setHeader("No Tracker-enabled project — enable Tracker on a project in Aexy")
                NSLog("Aexy Tracker: signed in, but no Tracker-enabled project for this account")
            } catch {
                onboarding = false
                updateTitle("⚠︎ Aexy")
                setHeader("Sign-in failed — try again from Sign in")
                NSLog("Aexy Tracker: browser sign-in failed: \(error)")
            }
        }
    }

    /// Enroll using a token from the environment (skips browser sign-in), then
    /// start capture. Picks `AEXY_PROJECT_ID` if set, else the first project.
    private func beginTokenEnrollment(token: String) {
        guard !onboarding else { return }
        onboarding = true
        updateTitle("… Aexy")

        let flow = makeOnboarding()
        Task { @MainActor in
            do {
                let config = try await flow.enroll(usingToken: token)
                onboarding = false
                setHeader("Aexy Tracker")
                startCapture(with: config)
            } catch {
                onboarding = false
                updateTitle("⚠︎ Aexy")
                setHeader("Enrollment failed — check token / project / tracker_enabled")
                NSLog("Aexy Tracker: token enrollment failed: \(error)")
            }
        }
    }

    private func showSignedOut() {
        updateTitle("⚠︎ Aexy")
        setHeader("Not signed in — use Sign in")
    }

    // MARK: - Capture

    private func startCapture(with config: TrackerConfig) {
        let client = TrackerClient(config: config)
        self.client = client
        capturing = true
        updateTitle("● Aexy")
        Task { await client.start() }
    }

    // MARK: - Status item

    private func setupStatusItem() {
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        item.button?.title = "○ Aexy"

        let menu = NSMenu()
        menu.addItem(NSMenuItem(title: "Aexy Tracker", action: nil, keyEquivalent: ""))
        menu.addItem(.separator())

        // Sign in → provider chooser.
        let signInMenu = NSMenu()
        for (label, provider) in [("GitHub", "github"), ("Google", "google"), ("Microsoft", "microsoft")] {
            let mi = NSMenuItem(title: label, action: #selector(signIn(_:)), keyEquivalent: "")
            mi.representedObject = provider
            mi.target = self
            signInMenu.addItem(mi)
        }
        let signInItem = NSMenuItem(title: "Sign in", action: nil, keyEquivalent: "")
        signInItem.submenu = signInMenu
        menu.addItem(signInItem)

        menu.addItem(NSMenuItem(title: "Pause / Resume", action: #selector(togglePause), keyEquivalent: "p"))
        menu.addItem(NSMenuItem(title: "Flush now", action: #selector(flushNow), keyEquivalent: "f"))
        menu.addItem(NSMenuItem(title: "Sign out", action: #selector(signOut), keyEquivalent: ""))
        menu.addItem(.separator())
        menu.addItem(NSMenuItem(title: "Quit", action: #selector(quit), keyEquivalent: "q"))
        for item in menu.items where item.action != nil { item.target = self }
        item.menu = menu
        self.statusItem = item
    }

    private func updateTitle(_ title: String) {
        statusItem?.button?.title = title
    }

    /// Update the (non-interactive) header item that shows status text.
    private func setHeader(_ text: String) {
        statusItem?.menu?.items.first?.title = text
    }

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

    /// Clear the Keychain credential, stop capture, and return to signed-out.
    @objc private func signOut() {
        Task { @MainActor in
            await client?.stop()
            client = nil
            capturing = false
            _ = keychain.delete()
            showSignedOut()
        }
    }

    @objc private func quit() {
        NSApp.terminate(nil)
    }
}

let app = NSApplication.shared
let controller = AppController()
app.delegate = controller
app.run()
