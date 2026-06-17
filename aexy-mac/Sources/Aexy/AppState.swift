import Foundation
import Combine
import AexyCore

// Observable UI state for the Aexy main window. Owns auth (web sign-in →
// localStorage token) and wraps FlowClient for the native screens.
@MainActor
final class AppState: ObservableObject {
    @Published var config: TrackerConfig?
    @Published var workspaces: [FlowWorkspace] = []
    @Published var selectedWorkspaceId: String? {
        didSet { UserDefaults.standard.set(selectedWorkspaceId, forKey: Self.wsKey) }
    }
    @Published var tasks: [FlowTask] = []
    @Published var notifications: [FlowNotification] = []
    @Published var unreadCount: Int = 0
    @Published var isLoading = false
    @Published var errorMessage: String?

    // Board / project-switcher state.
    @Published var projects: [FlowProject] = []
    @Published var selectedProjectId: String? {
        didSet { UserDefaults.standard.set(selectedProjectId, forKey: Self.projKey) }
    }
    @Published var statuses: [FlowTaskStatus] = []
    @Published var board: [FlowTask] = []
    @Published var members: [FlowMember] = []
    @Published var boardLoading = false
    @Published var filterSearch = ""
    @Published var filterPriorities: Set<String> = []
    @Published var filterAssignees: Set<String> = []
    @Published var filterLabels: Set<String> = []
    @Published var sprints: [FlowSprint] = []
    @Published var filterSprintIds: Set<String> = []

    /// Distinct labels present on the current board (for the label filter).
    var availableLabels: [String] {
        Array(Set(board.flatMap { $0.labels ?? [] })).sorted()
    }

    /// Notifies observers (the embedded web view) to follow the selected project.
    var onProjectChanged: ((_ workspaceId: String, _ projectId: String) -> Void)?

    private static let wsKey = "aexy.selectedWorkspaceId"
    private static let projKey = "aexy.selectedProjectId"

    // Baseline timestamp for notification polling (nil ⇒ first tick only sets it).
    private var lastNotifPollSince: String?

    let apiBaseURL: URL
    private let keychain: KeychainTokenStore

    /// Called when background activity capture becomes possible (device enrolled
    /// to a Tracker-enabled project). The AppController starts the capture loop.
    var onCaptureReady: ((TrackerConfig) -> Void)?

    init(apiBaseURL: URL, keychain: KeychainTokenStore, config: TrackerConfig?) {
        self.apiBaseURL = apiBaseURL
        self.keychain = keychain
        self.config = config
        self.selectedWorkspaceId = UserDefaults.standard.string(forKey: Self.wsKey)
        self.selectedProjectId = UserDefaults.standard.string(forKey: Self.projKey)
    }

    /// Canonical column fallback when a project has no DB-driven statuses.
    static let canonicalStatuses: [(slug: String, name: String)] = [
        ("backlog", "Backlog"), ("todo", "To Do"), ("in_progress", "In Progress"),
        ("review", "Review"), ("done", "Done"),
    ]

    var isSignedIn: Bool { config != nil }

    private var client: FlowClient? { config.map { FlowClient(config: $0) } }

    /// Client for feature views (e.g. Docs) that build their own state.
    var flowClient: FlowClient? { client }

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
        // Wipe the encrypted offline doc cache on sign-out.
        DocCache().clear()
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

    /// Poll for new notifications and surface them as native macOS notifications.
    /// The first tick only establishes a baseline (no notifications fired).
    func pollNotificationsTick() async {
        guard let client else { return }
        let nowISO = ISO8601DateFormatter().string(from: Date())
        do {
            if let since = lastNotifPollSince {
                let resp = try await client.pollNotifications(since: since)
                for n in resp.notifications {
                    NativeNotifier.post(id: n.id, title: n.title, body: n.description ?? "", actionUrl: n.actionUrl)
                }
                if let c = resp.unreadCount { unreadCount = c }
            } else {
                let resp = try await client.notifications(unreadOnly: false)
                unreadCount = resp.unreadCount ?? resp.notifications.filter { !$0.isRead }.count
            }
            lastNotifPollSince = nowISO
        } catch {
            /* transient — try again next tick */
        }
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

    // MARK: - Board / projects

    /// Load the selected workspace's projects, then the board.
    func loadProjectsAndBoard() async {
        guard let client, let ws = selectedWorkspaceId else { return }
        members = (try? await client.workspaceMembers(workspaceId: ws)) ?? []
        do {
            let projs = try await client.projects(workspaceId: ws)
            projects = projs
            // Default to "All projects" (nil = workspace-wide, like the web's
            // "view all tasks"); only clear a selection that no longer exists.
            if let sel = selectedProjectId, !projs.contains(where: { $0.id == sel }) {
                selectedProjectId = nil
            }
            if selectedProjectId == nil { statuses = [] }
        } catch {
            errorMessage = describe(error)
        }
        await loadBoard()
    }

    func selectProject(_ id: String) {
        selectedProjectId = id
        if let ws = selectedWorkspaceId { onProjectChanged?(ws, id) }
        Task { await loadBoard() }
    }

    /// Workspace-wide board (all projects) — canonical columns, no project filter.
    func selectAllProjects() {
        selectedProjectId = nil
        statuses = []
        Task { await loadBoard() }
    }

    func loadBoard() async {
        guard let client, let ws = selectedWorkspaceId else { return }
        boardLoading = true
        if let pid = selectedProjectId {
            statuses = (try? await client.taskStatuses(workspaceId: ws, projectId: pid)) ?? []
            sprints = (try? await client.sprints(workspaceId: ws, teamId: pid)) ?? []
        } else {
            sprints = []
        }
        var filters = BoardTaskFilters()
        filters.search = filterSearch.isEmpty ? nil : filterSearch
        filters.priorities = Array(filterPriorities)
        filters.assigneeIds = Array(filterAssignees)
        filters.labels = Array(filterLabels)
        filters.sprintIds = Array(filterSprintIds)
        do {
            board = try await client.boardTasks(workspaceId: ws, filters: filters)
        } catch {
            errorMessage = describe(error)
        }
        boardLoading = false
    }

    /// Ordered (slug, name) columns: DB statuses if present, else canonical.
    var columns: [(slug: String, name: String)] {
        if statuses.isEmpty { return Self.canonicalStatuses }
        return statuses.sorted { ($0.position ?? 0) < ($1.position ?? 0) }
            .map { ($0.slug, $0.name) }
    }

    /// Board tasks for one column, narrowed to the selected project (best-effort)
    /// + client-side search/priority as a safety net over the server filter.
    func tasks(inColumn slug: String) -> [FlowTask] {
        board.filter { task in
            (task.status ?? "") == slug
                && matchesSelectedProject(task)
                && matchesFilters(task)
        }
    }

    private func matchesSelectedProject(_ task: FlowTask) -> Bool {
        guard let pid = selectedProjectId else { return true }
        // Tasks may carry projectId or teamId depending on origin; if neither is
        // present we don't hide it (workspace-wide board still shows the task).
        if let p = task.projectId { return p == pid }
        if let t = task.teamId { return t == pid }
        return true
    }

    private func matchesFilters(_ task: FlowTask) -> Bool {
        if !filterPriorities.isEmpty {
            guard let p = task.priority, filterPriorities.contains(p) else { return false }
        }
        if !filterAssignees.isEmpty {
            guard let a = task.assigneeId, filterAssignees.contains(a) else { return false }
        }
        if !filterLabels.isEmpty {
            let labels = Set(task.labels ?? [])
            guard !labels.isDisjoint(with: filterLabels) else { return false }
        }
        if !filterSprintIds.isEmpty {
            guard let s = task.sprintId, filterSprintIds.contains(s) else { return false }
        }
        if !filterSearch.isEmpty {
            return task.title.localizedCaseInsensitiveContains(filterSearch)
        }
        return true
    }

    /// Create a task in the selected project (team) with the given status.
    @discardableResult
    func createBoardTask(title: String, status: String) async -> FlowTask? {
        guard let client, let team = selectedProjectId, !title.isEmpty else { return nil }
        let task = try? await client.createTask(teamId: team, title: title, status: status)
        await loadBoard()
        return task
    }

    /// Explicitly unassign a task (clears assignee), then refresh.
    func unassign(_ task: FlowTask) async {
        guard let client else { return }
        do {
            try await client.unassignTask(sprintId: task.sprintId, teamId: task.teamId, taskId: task.id)
            await loadBoard()
        } catch {
            errorMessage = describe(error)
        }
    }

    /// Optimistic drag-to-move; reverts by reloading on failure.
    func moveTask(_ task: FlowTask, toStatus slug: String) async {
        guard let client, let ws = task.workspaceId ?? selectedWorkspaceId else { return }
        if let i = board.firstIndex(where: { $0.id == task.id }) { board[i].status = slug }
        do {
            try await client.updateTaskStatus(workspaceId: ws, taskId: task.id, status: slug)
        } catch {
            errorMessage = describe(error)
            await loadBoard()
        }
    }

    // MARK: - Task detail (comments / activity)

    /// True when the task supports comments (sprint- or team/project-scoped).
    func commentable(_ task: FlowTask) -> Bool {
        task.sprintId != nil || task.teamId != nil
    }

    /// Comments + activity for a task — sprint-scoped when in a sprint, else
    /// team/project-scoped (backlog tasks). Empty if neither scope is known.
    func loadActivities(_ task: FlowTask) async -> [FlowActivity] {
        guard let client else { return [] }
        do {
            if let sid = task.sprintId {
                return try await client.taskActivities(sprintId: sid, taskId: task.id)
            }
            if let tid = task.teamId {
                return try await client.projectTaskActivities(teamId: tid, taskId: task.id)
            }
        } catch {
            errorMessage = describe(error)
        }
        return []
    }

    /// Edit task fields (priority / story points / labels / etc.). Scope-resolved
    /// (sprint vs team); returns the updated task and patches it into the board.
    @discardableResult
    func updateTaskFields(_ task: FlowTask, _ fields: TaskUpdateFields) async -> FlowTask? {
        guard let client else { return nil }
        do {
            let updated: FlowTask
            if let sid = task.sprintId {
                updated = try await client.updateTask(sprintId: sid, taskId: task.id, fields: fields)
            } else if let tid = task.teamId {
                updated = try await client.updateProjectTask(teamId: tid, taskId: task.id, fields: fields)
            } else {
                return nil
            }
            if let i = board.firstIndex(where: { $0.id == task.id }) { board[i] = updated }
            return updated
        } catch {
            errorMessage = describe(error)
            return nil
        }
    }

    /// Whether a task's fields can be edited (needs a sprint or team scope).
    func editable(_ task: FlowTask) -> Bool { task.sprintId != nil || task.teamId != nil }

    func addComment(_ task: FlowTask, _ text: String) async {
        guard let client else { return }
        do {
            if let sid = task.sprintId {
                try await client.addComment(sprintId: sid, taskId: task.id, text: text)
            } else if let tid = task.teamId {
                try await client.addProjectTaskComment(teamId: tid, taskId: task.id, text: text)
            }
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
