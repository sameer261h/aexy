import AppKit
import AexyTrackerCore

// Menu-bar entry point. Runs as an accessory (no Dock icon), shows a status item,
// and drives the TrackerClient capture loop. On launch it prefers a Keychain
// credential from onboarding (AEXY_TRACKER.md §6); if none exists it runs the
// OAuth device-code onboarding flow and starts capture once it returns a config.

final class AppController: NSObject, NSApplicationDelegate {
    private var statusItem: NSStatusItem?
    private var client: TrackerClient?
    private var capturing = false
    private var onboarding = false
    private let keychain = KeychainTokenStore()

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        setupStatusItem()

        if let config = TrackerConfig.resolve(store: keychain) {
            startCapture(with: config)
        } else {
            beginOnboarding()
        }
    }

    // MARK: - Capture

    private func startCapture(with config: TrackerConfig) {
        let client = TrackerClient(config: config)
        self.client = client
        capturing = true
        updateTitle("● Aexy")
        Task { await client.start() }
    }

    // MARK: - Onboarding

    private func beginOnboarding() {
        guard !onboarding else { return }
        onboarding = true
        updateTitle("… Aexy")

        // OAuth endpoints live on the aexy.io auth surface (EXTERNAL dependency;
        // see Auth.swift). The auth base is configurable via env for the scaffold.
        let env = ProcessInfo.processInfo.environment
        let authBase = (env["AEXY_AUTH_URL"]).flatMap(URL.init(string:))
            ?? URL(string: "https://aexy.io")!
        let apiBase = (env["AEXY_API_URL"]).flatMap(URL.init(string:))
            ?? URL(string: "https://aexy.io/api/v1")!

        let authenticator = DeviceCodeAuthenticator(config: .aexy(authBase: authBase))
        let flow = Onboarding(
            apiBaseURL: apiBase,
            authenticator: authenticator,
            keychain: keychain,
            presentCode: { [weak self] code in
                // Surface the user_code / verification URI in the menu bar.
                Task { @MainActor in
                    self?.updateTitle("⌨ \(code.userCode)")
                    self?.setHeader("Sign in at \(code.verificationUri)")
                }
            }
        )

        Task { @MainActor in
            do {
                let config = try await flow.run()
                onboarding = false
                setHeader("Aexy Tracker")
                startCapture(with: config)
            } catch {
                onboarding = false
                updateTitle("⚠︎ Aexy")
                setHeader("Sign-in failed — retry from the menu")
                NSLog("Aexy Tracker: onboarding failed: \(error)")
            }
        }
    }

    // MARK: - Status item

    private func setupStatusItem() {
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        item.button?.title = "○ Aexy"

        let menu = NSMenu()
        menu.addItem(NSMenuItem(title: "Aexy Tracker", action: nil, keyEquivalent: ""))
        menu.addItem(.separator())
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

    /// Clear the Keychain credential, stop capture, and return to onboarding.
    @objc private func signOut() {
        Task {
            await client?.stop()
            client = nil
            capturing = false
            _ = keychain.delete()
            beginOnboarding()
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
