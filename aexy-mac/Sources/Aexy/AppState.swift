import Foundation
import Combine
import AexyCore

// Observable UI state for the Aexy main window. Owns auth (web sign-in →
// localStorage token) and wraps FlowClient for the native screens.
@MainActor
final class AppState: ObservableObject {
    @Published var config: TrackerConfig?
    @Published var workspaces: [FlowWorkspace] = []
    @Published var selectedWorkspaceId: String?
    @Published var tasks: [FlowTask] = []
    @Published var notifications: [FlowNotification] = []
    @Published var unreadCount: Int = 0
    @Published var isLoading = false
    @Published var errorMessage: String?

    let apiBaseURL: URL
    private let keychain: KeychainTokenStore

    /// Called when background activity capture becomes possible (device enrolled
    /// to a Tracker-enabled project). The AppController starts the capture loop.
    var onCaptureReady: ((TrackerConfig) -> Void)?

    init(apiBaseURL: URL, keychain: KeychainTokenStore, config: TrackerConfig?) {
        self.apiBaseURL = apiBaseURL
        self.keychain = keychain
        self.config = config
    }

    var isSignedIn: Bool { config != nil }

    private var client: FlowClient? { config.map { FlowClient(config: $0) } }

    // MARK: - Web sign-in

    /// The web app stores its JWT under `localStorage["token"]`. The login web
    /// view hands it here: persist it, light up the companion features, and
    /// best-effort enroll a device so background capture can run too.
    func completeWebLogin(token: String) async {
        // Exchange the short web JWT for a long-lived API token when possible.
        let onboarding = makeOnboarding()
        let bearer = (try? await onboarding.exchangeForApiToken(jwt: token)) ?? token

        // Companion credential (no project needed for tasks/time/etc.).
        _ = keychain.save(
            StoredCredential(token: bearer, projectId: "", apiBaseURL: apiBaseURL.absoluteString)
        )
        config = TrackerConfig(
            apiBaseURL: apiBaseURL,
            bearerToken: bearer,
            deviceId: PersistentDeviceID.load(),
            projectId: nil
        )
        await refresh()

        // Best-effort: enroll to a Tracker-enabled project so capture can run.
        if let captureConfig = try? await onboarding.enroll(usingToken: bearer) {
            config = captureConfig
            onCaptureReady?(captureConfig)
        }
    }

    func signOut() {
        _ = keychain.delete()
        config = nil
        workspaces = []
        tasks = []
        notifications = []
        unreadCount = 0
        // Clear the embedded web session too, so "Open in Aexy" isn't left
        // logged in after sign-out (true logout + clean session).
        AexyWebSession.clear {}
    }

    private func makeOnboarding() -> Onboarding {
        // The authenticator is unused on the token paths but the init requires it.
        let authBase = apiBaseURL.deletingLastPathComponent().deletingLastPathComponent()
        return Onboarding(
            apiBaseURL: apiBaseURL,
            authenticator: DeviceCodeAuthenticator(config: .aexy(authBase: authBase)),
            keychain: keychain
        )
    }

    // MARK: - Data

    func refresh() async {
        guard let client else { return }
        isLoading = true
        errorMessage = nil
        do {
            let ws = try await client.workspaces()
            let tk = try await client.assignedTasks(includeDone: false)
            let nt = try await client.notifications(unreadOnly: false)
            workspaces = ws
            tasks = tk
            notifications = nt.notifications
            unreadCount = nt.unreadCount ?? nt.notifications.filter { !$0.isRead }.count
            if selectedWorkspaceId == nil { selectedWorkspaceId = ws.first?.id }
        } catch {
            errorMessage = describe(error)
        }
        isLoading = false
    }

    func setStatus(_ task: FlowTask, _ status: String) async {
        guard let client, let ws = task.workspaceId ?? selectedWorkspaceId else { return }
        do {
            try await client.updateTaskStatus(workspaceId: ws, taskId: task.id, status: status)
            await refresh()
        } catch {
            errorMessage = describe(error)
        }
    }

    private func describe(_ error: Error) -> String {
        if let e = error as? FlowError {
            switch e {
            case .unauthorized: return "Session expired — sign in again."
            case .transport(let m): return "Network error: \(m)"
            case .unexpectedStatus(let s): return "Server error (\(s))."
            case .decode: return "Couldn't read the server response."
            }
        }
        return "\(error)"
    }
}
