import Foundation

#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

// Aexy Flow — typed REST client for the companion app's core features.
// All endpoints are behind the standard Bearer auth (an `aexy_` API token or a
// developer JWT); the same token the capture engine + sign-in already use.
//
// Timestamps are decoded as ISO strings (not Date) so the client never breaks
// on the API's fractional-second / timezone variations — the UI formats them.

public enum FlowError: Error, Sendable, Equatable {
    case transport(String)
    case unauthorized
    case unexpectedStatus(Int)
    case decode
}

// MARK: - Wire models

public struct FlowWorkspace: Codable, Sendable, Identifiable, Equatable {
    public let id: String
    public let name: String
    public var slug: String?
}

public struct FlowTask: Codable, Sendable, Identifiable, Equatable {
    public let id: String
    public let title: String
    public var status: String?
    public var statusId: String?
    public var priority: String?
    public var projectId: String?
    public var workspaceId: String?
    public var teamId: String?
    public var sprintId: String?
    public var epicId: String?
    public var assigneeId: String?
    public var assigneeName: String?
    public var assigneeAvatarUrl: String?
    public var storyPoints: Int?
    public var labels: [String]?
    public var description: String?
    public var endDate: String?
    public var dueDate: String?
    public var identifier: String?
}

public struct FlowTimeEntry: Codable, Sendable, Identifiable, Equatable {
    public let id: String
    public var taskId: String?
    public var durationMinutes: Int
    public var description: String?
    public var entryDate: String?
}

public struct FlowTimeEntries: Codable, Sendable, Equatable {
    public var entries: [FlowTimeEntry]
    public var total: Int
    public var totalMinutes: Int
}

public struct FlowTargetHours: Codable, Sendable, Equatable {
    public var targetHoursPerDay: Double
    /// "developer" | "project" | "workspace" | "default".
    public var source: String
}

public struct FlowChatInboxTopic: Codable, Sendable, Equatable {
    public var unreadCount: Int?
}

public struct FlowChatInbox: Codable, Sendable, Equatable {
    public var topics: [FlowChatInboxTopic]
}

public struct FlowNotification: Codable, Sendable, Identifiable, Equatable {
    public let id: String
    public var eventType: String?
    public var title: String
    public var description: String?
    public var isRead: Bool
    public var actionUrl: String?
    public var createdAt: String?
}

public struct FlowSprint: Codable, Sendable, Identifiable, Equatable {
    public let id: String
    public let name: String
    public var status: String?
}

public struct FlowStandup: Codable, Sendable, Identifiable, Equatable {
    public let id: String
    public var standupDate: String?
    public var yesterdaySummary: String?
    public var todayPlan: String?
    public var blockersSummary: String?
    public var submittedAt: String?
}

struct FlowStandupsResponse: Codable { let standups: [FlowStandup] }
struct FlowQAResponse: Codable { let answer: String }

public struct FlowMember: Codable, Sendable, Identifiable, Equatable {
    public var id: String { developerId }
    public let developerId: String
    public var developerName: String?
    public var developerEmail: String?
    public var developerAvatarUrl: String?
    public var role: String?
    public var status: String?

    public var displayName: String { developerName ?? developerEmail ?? developerId }
}

// MARK: Docs

public struct DocSpace: Codable, Sendable, Identifiable, Equatable {
    public let id: String
    public let name: String
    public var icon: String?
    public var color: String?
    public var isDefault: Bool?
}

public struct DocNode: Codable, Sendable, Identifiable, Equatable {
    public let id: String
    public let title: String
    public var icon: String?
    public var parentId: String?
    public var spaceId: String?
    public var position: Int?
    public var visibility: String?
    public var isFavorited: Bool?
    public var hasChildren: Bool?
    public var children: [DocNode]?
}

public struct DocListItem: Codable, Sendable, Identifiable, Equatable {
    public let id: String
    public let title: String
    public var icon: String?
    public var parentId: String?
}

/// Document detail for native offline read — the rich `content` (TipTap JSON)
/// is intentionally not modelled; the embedded web editor renders it online and
/// `contentText` is cached for offline viewing.
public struct DocDetail: Codable, Sendable, Identifiable, Equatable {
    public let id: String
    public let title: String
    public var icon: String?
    public var contentText: String?
    public var visibility: String?
    public var spaceId: String?
    public var updatedAt: String?

    public init(
        id: String, title: String, icon: String? = nil, contentText: String? = nil,
        visibility: String? = nil, spaceId: String? = nil, updatedAt: String? = nil
    ) {
        self.id = id; self.title = title; self.icon = icon; self.contentText = contentText
        self.visibility = visibility; self.spaceId = spaceId; self.updatedAt = updatedAt
    }
}

public struct FlowProject: Codable, Sendable, Identifiable, Equatable {
    public let id: String
    public let name: String
    public var slug: String?
    public var color: String?
    public var icon: String?
    public var workspaceId: String?
}

struct FlowProjectsResponse: Codable { let projects: [FlowProject] }

public struct FlowTaskStatus: Codable, Sendable, Identifiable, Equatable {
    public let id: String
    public let name: String
    public var slug: String
    public var category: String?
    public var color: String?
    public var position: Int?
}

public struct FlowActivity: Codable, Sendable, Identifiable, Equatable {
    public let id: String
    public var action: String?
    public var actorName: String?
    public var actorAvatarUrl: String?
    public var fieldName: String?
    public var oldValue: String?
    public var newValue: String?
    public var comment: String?
    public var createdAt: String?
}

struct FlowActivitiesResponse: Codable { let activities: [FlowActivity]; let total: Int? }

/// Board query filters (mirrors the web board's filter set).
public struct BoardTaskFilters: Sendable {
    public var statusIds: [String] = []
    public var assigneeIds: [String] = []
    public var priorities: [String] = []
    public var labels: [String] = []
    public var sprintIds: [String] = []
    public var search: String?
    public var limit: Int = 500
    public init() {}
}

/// Partial task field update (PATCH).
public struct TaskUpdateFields: Codable, Sendable {
    public var title: String?
    public var description: String?
    public var priority: String?
    public var storyPoints: Int?
    public var labels: [String]?
    public var assigneeId: String?
    public var epicId: String?
    public var status: String?
    public var startDate: String?
    public var endDate: String?
    public init() {}
}

public struct FlowNotifications: Codable, Sendable, Equatable {
    public var notifications: [FlowNotification]
    public var unreadCount: Int?
}

// MARK: - Request payloads

public struct LogTimeRequest: Codable, Sendable {
    public var durationMinutes: Int
    public var description: String?
    public var taskId: String?
    public var entryDate: String?
    public var source: String

    public init(
        durationMinutes: Int,
        description: String? = nil,
        taskId: String? = nil,
        entryDate: String? = nil,
        source: String = "web"
    ) {
        self.durationMinutes = durationMinutes
        self.description = description
        self.taskId = taskId
        self.entryDate = entryDate
        self.source = source
    }
}

public struct StandupRequest: Codable, Sendable {
    public var yesterdaySummary: String?
    public var todayPlan: String?
    public var blockersSummary: String?
    public var teamId: String?

    public init(
        yesterdaySummary: String? = nil,
        todayPlan: String? = nil,
        blockersSummary: String? = nil,
        teamId: String? = nil
    ) {
        self.yesterdaySummary = yesterdaySummary
        self.todayPlan = todayPlan
        self.blockersSummary = blockersSummary
        self.teamId = teamId
    }
}

// MARK: - Client

public struct FlowClient: Sendable {
    private let apiBaseURL: URL
    private let bearerToken: String
    private let session: URLSession

    public init(apiBaseURL: URL, bearerToken: String, session: URLSession = .shared) {
        self.apiBaseURL = apiBaseURL
        self.bearerToken = bearerToken
        self.session = session
    }

    public init(config: TrackerConfig, session: URLSession = .shared) {
        self.init(apiBaseURL: config.apiBaseURL, bearerToken: config.bearerToken, session: session)
    }

    // JSON coder: snake_case ↔ camelCase, timestamps left as strings.
    static let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.keyEncodingStrategy = .convertToSnakeCase
        return e
    }()
    static let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()

    // MARK: requests

    /// Build a signed URLRequest. `query` items are appended; `body` is JSON-encoded.
    func makeRequest(
        _ method: String,
        _ path: String,
        query: [URLQueryItem] = [],
        body: Data? = nil
    ) -> URLRequest {
        var components = URLComponents(
            url: apiBaseURL.appendingPathComponent(path),
            resolvingAgainstBaseURL: false
        )!
        if !query.isEmpty {
            components.queryItems = query
        }
        var request = URLRequest(url: components.url!)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("Bearer \(bearerToken)", forHTTPHeaderField: "Authorization")
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = body
        }
        return request
    }

    private func send<T: Decodable>(_ request: URLRequest, as type: T.Type) async throws -> T {
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch {
            throw FlowError.transport(error.localizedDescription)
        }
        guard let http = response as? HTTPURLResponse else {
            throw FlowError.transport("non-HTTP response")
        }
        if http.statusCode == 401 || http.statusCode == 403 {
            throw FlowError.unauthorized
        }
        guard (200..<300).contains(http.statusCode) else {
            throw FlowError.unexpectedStatus(http.statusCode)
        }
        guard let decoded = try? Self.decoder.decode(T.self, from: data) else {
            throw FlowError.decode
        }
        return decoded
    }

    private func sendNoContent(_ request: URLRequest) async throws {
        let response: URLResponse
        do {
            (_, response) = try await session.data(for: request)
        } catch {
            throw FlowError.transport(error.localizedDescription)
        }
        guard let http = response as? HTTPURLResponse else {
            throw FlowError.transport("non-HTTP response")
        }
        if http.statusCode == 401 || http.statusCode == 403 { throw FlowError.unauthorized }
        guard (200..<300).contains(http.statusCode) else {
            throw FlowError.unexpectedStatus(http.statusCode)
        }
    }

    // MARK: workspaces & tasks

    public func workspaces() async throws -> [FlowWorkspace] {
        try await send(makeRequest("GET", "workspaces"), as: [FlowWorkspace].self)
    }

    /// The caller's assigned tasks across all workspaces.
    public func assignedTasks(includeDone: Bool = false) async throws -> [FlowTask] {
        let query = [URLQueryItem(name: "include_done", value: includeDone ? "true" : "false")]
        return try await send(
            makeRequest("GET", "developers/me/assigned-tasks", query: query), as: [FlowTask].self
        )
    }

    public func updateTaskStatus(workspaceId: String, taskId: String, status: String) async throws {
        let body = try Self.encoder.encode(["status": status])
        try await sendNoContent(
            makeRequest("PATCH", "workspaces/\(workspaceId)/tasks/\(taskId)/status", body: body)
        )
    }

    // MARK: time tracking

    @discardableResult
    public func logTime(_ req: LogTimeRequest) async throws -> FlowTimeEntry {
        let body = try Self.encoder.encode(req)
        return try await send(makeRequest("POST", "tracking/time", body: body), as: FlowTimeEntry.self)
    }

    /// Resolved daily target hours for the current developer (developer →
    /// project → workspace default → hard fallback). Drives check-in progress.
    public func targetHours(workspaceId: String, projectId: String?) async throws -> FlowTargetHours {
        var query = [URLQueryItem(name: "workspace_id", value: workspaceId)]
        if let pid = projectId, !pid.isEmpty {
            query.append(URLQueryItem(name: "project_id", value: pid))
        }
        return try await send(
            makeRequest("GET", "tracker/target-hours/resolve", query: query),
            as: FlowTargetHours.self
        )
    }

    /// Unread chat topics (the communicator "Threads" inbox) for the badge.
    public func chatInbox(workspaceId: String) async throws -> FlowChatInbox {
        try await send(
            makeRequest("GET", "workspaces/\(workspaceId)/chat/inbox"), as: FlowChatInbox.self
        )
    }

    public func myTimeEntries(start: String, end: String) async throws -> FlowTimeEntries {
        let query = [
            URLQueryItem(name: "start_date", value: start),
            URLQueryItem(name: "end_date", value: end),
        ]
        return try await send(
            makeRequest("GET", "tracking/time/me", query: query), as: FlowTimeEntries.self
        )
    }

    // MARK: standups

    public func submitStandup(_ req: StandupRequest) async throws {
        let body = try Self.encoder.encode(req)
        try await sendNoContent(makeRequest("POST", "tracking/standups", body: body))
    }

    public func myStandups() async throws -> [FlowStandup] {
        let q = [URLQueryItem(name: "limit", value: "30")]
        let resp = try await send(
            makeRequest("GET", "tracking/standups/me", query: q), as: FlowStandupsResponse.self
        )
        return resp.standups
    }

    /// AI-drafted standup from the day's tracked work (reuses /tracker/qa).
    public func draftStandup() async throws -> String {
        let body = try Self.encoder.encode(["question": "Draft my standup", "days": "1"])
        let resp = try await send(makeRequest("POST", "tracker/qa", body: body), as: FlowQAResponse.self)
        return resp.answer
    }

    // MARK: sprints / task create / unassign

    public func sprints(workspaceId: String, teamId: String) async throws -> [FlowSprint] {
        try await send(
            makeRequest("GET", "workspaces/\(workspaceId)/teams/\(teamId)/sprints"), as: [FlowSprint].self
        )
    }

    @discardableResult
    public func createTask(teamId: String, title: String, status: String) async throws -> FlowTask {
        struct Create: Codable { let title: String; let status: String }
        let body = try Self.encoder.encode(Create(title: title, status: status))
        return try await send(makeRequest("POST", "teams/\(teamId)/tasks", body: body), as: FlowTask.self)
    }

    /// Explicit unassign — sends literal `{"assignee_id":null}` (the omit-nil
    /// encoder can't emit null). Sprint-scoped if a sprint id is given, else team.
    public func unassignTask(sprintId: String?, teamId: String?, taskId: String) async throws {
        let path: String
        if let sid = sprintId { path = "sprints/\(sid)/tasks/\(taskId)" }
        else if let tid = teamId { path = "teams/\(tid)/tasks/\(taskId)" }
        else { return }
        try await sendNoContent(makeRequest("PATCH", path, body: Data("{\"assignee_id\":null}".utf8)))
    }

    // MARK: notifications

    public func notifications(page: Int = 1, unreadOnly: Bool = false) async throws -> FlowNotifications {
        let query = [
            URLQueryItem(name: "page", value: String(page)),
            URLQueryItem(name: "unread_only", value: unreadOnly ? "true" : "false"),
        ]
        return try await send(makeRequest("GET", "notifications", query: query), as: FlowNotifications.self)
    }

    public func pollNotifications(since: String) async throws -> FlowNotifications {
        let query = [URLQueryItem(name: "since", value: since)]
        return try await send(makeRequest("GET", "notifications/poll", query: query), as: FlowNotifications.self)
    }

    public func markNotificationRead(id: String) async throws {
        try await sendNoContent(makeRequest("POST", "notifications/\(id)/read"))
    }

    // MARK: projects / board

    public func workspaceMembers(workspaceId: String) async throws -> [FlowMember] {
        try await send(makeRequest("GET", "workspaces/\(workspaceId)/members"), as: [FlowMember].self)
    }

    // MARK: docs

    public func docSpaces(workspaceId: String) async throws -> [DocSpace] {
        try await send(makeRequest("GET", "workspaces/\(workspaceId)/spaces"), as: [DocSpace].self)
    }

    public func docTree(workspaceId: String, spaceId: String? = nil) async throws -> [DocNode] {
        var query: [URLQueryItem] = []
        if let spaceId { query.append(URLQueryItem(name: "space_id", value: spaceId)) }
        return try await send(
            makeRequest("GET", "workspaces/\(workspaceId)/documents/tree", query: query), as: [DocNode].self
        )
    }

    public func docFavorites(workspaceId: String) async throws -> [DocNode] {
        try await send(
            makeRequest("GET", "workspaces/\(workspaceId)/documents/favorites"), as: [DocNode].self
        )
    }

    public func document(workspaceId: String, documentId: String) async throws -> DocDetail {
        try await send(
            makeRequest("GET", "workspaces/\(workspaceId)/documents/\(documentId)"), as: DocDetail.self
        )
    }

    public func searchDocuments(workspaceId: String, query: String) async throws -> [DocListItem] {
        let q = [URLQueryItem(name: "search", value: query), URLQueryItem(name: "limit", value: "20")]
        return try await send(
            makeRequest("GET", "workspaces/\(workspaceId)/documents", query: q), as: [DocListItem].self
        )
    }

    @discardableResult
    public func createDocument(
        workspaceId: String, title: String, spaceId: String? = nil, parentId: String? = nil
    ) async throws -> DocListItem {
        struct Create: Codable { let title: String; let spaceId: String?; let parentId: String? }
        let body = try Self.encoder.encode(Create(title: title, spaceId: spaceId, parentId: parentId))
        return try await send(
            makeRequest("POST", "workspaces/\(workspaceId)/documents", body: body), as: DocListItem.self
        )
    }

    public func toggleDocFavorite(workspaceId: String, documentId: String) async throws {
        try await sendNoContent(
            makeRequest("POST", "workspaces/\(workspaceId)/documents/\(documentId)/favorite")
        )
    }

    @discardableResult
    public func updateDocumentTitle(workspaceId: String, documentId: String, title: String) async throws -> DocListItem {
        let body = try Self.encoder.encode(["title": title])
        return try await send(
            makeRequest("PATCH", "workspaces/\(workspaceId)/documents/\(documentId)", body: body),
            as: DocListItem.self
        )
    }

    public func projects(workspaceId: String) async throws -> [FlowProject] {
        let resp = try await send(
            makeRequest("GET", "workspaces/\(workspaceId)/projects"), as: FlowProjectsResponse.self
        )
        return resp.projects
    }

    /// Board columns for a project (DB-driven statuses; empty ⇒ use canonical defaults).
    public func taskStatuses(workspaceId: String, projectId: String) async throws -> [FlowTaskStatus] {
        let query = [URLQueryItem(name: "project_id", value: projectId)]
        return try await send(
            makeRequest("GET", "workspaces/\(workspaceId)/task-statuses", query: query),
            as: [FlowTaskStatus].self
        )
    }

    /// Tasks for a board, filtered (mirrors the web board's filters).
    public func boardTasks(workspaceId: String, filters: BoardTaskFilters) async throws -> [FlowTask] {
        var query: [URLQueryItem] = [URLQueryItem(name: "limit", value: String(filters.limit))]
        query += filters.statusIds.map { URLQueryItem(name: "status_id", value: $0) }
        query += filters.assigneeIds.map { URLQueryItem(name: "assignee_id", value: $0) }
        query += filters.priorities.map { URLQueryItem(name: "priority", value: $0) }
        query += filters.labels.map { URLQueryItem(name: "labels", value: $0) }
        query += filters.sprintIds.map { URLQueryItem(name: "sprint_id", value: $0) }
        if let s = filters.search, !s.isEmpty { query.append(URLQueryItem(name: "search", value: s)) }
        return try await send(
            makeRequest("GET", "workspaces/\(workspaceId)/tasks", query: query), as: [FlowTask].self
        )
    }

    // MARK: task detail / comments (sprint-scoped)

    public func taskActivities(sprintId: String, taskId: String) async throws -> [FlowActivity] {
        let resp = try await send(
            makeRequest("GET", "sprints/\(sprintId)/tasks/\(taskId)/activities"),
            as: FlowActivitiesResponse.self
        )
        return resp.activities
    }

    public func addComment(sprintId: String, taskId: String, text: String) async throws {
        let body = try Self.encoder.encode(["comment": text])
        try await sendNoContent(
            makeRequest("POST", "sprints/\(sprintId)/tasks/\(taskId)/comments", body: body)
        )
    }

    @discardableResult
    public func updateTask(sprintId: String, taskId: String, fields: TaskUpdateFields) async throws -> FlowTask {
        let body = try Self.encoder.encode(fields)
        return try await send(
            makeRequest("PATCH", "sprints/\(sprintId)/tasks/\(taskId)", body: body), as: FlowTask.self
        )
    }

    // MARK: task detail / comments (project/team-scoped — for backlog tasks)

    public func projectTaskActivities(teamId: String, taskId: String) async throws -> [FlowActivity] {
        let resp = try await send(
            makeRequest("GET", "teams/\(teamId)/tasks/\(taskId)/activities"),
            as: FlowActivitiesResponse.self
        )
        return resp.activities
    }

    public func addProjectTaskComment(teamId: String, taskId: String, text: String) async throws {
        let body = try Self.encoder.encode(["comment": text])
        try await sendNoContent(
            makeRequest("POST", "teams/\(teamId)/tasks/\(taskId)/comments", body: body)
        )
    }

    @discardableResult
    public func updateProjectTask(teamId: String, taskId: String, fields: TaskUpdateFields) async throws -> FlowTask {
        let body = try Self.encoder.encode(fields)
        return try await send(
            makeRequest("PATCH", "teams/\(teamId)/tasks/\(taskId)", body: body), as: FlowTask.self
        )
    }
}
