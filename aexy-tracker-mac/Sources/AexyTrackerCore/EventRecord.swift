import Foundation

// Wire model for the Aexy Tracker ingest contract (AEXY_TRACKER_INGEST_API.md §4).
// Encoded with `.convertToSnakeCase`, so `eventId` → `event_id`, `intervalS` →
// `interval_s`, etc. `category`/`attribution` are server-derived and never sent.

public struct ActiveApp: Codable, Sendable, Equatable {
    public var name: String
    public var bundleId: String
    public var windowTitle: String?

    public init(name: String, bundleId: String, windowTitle: String? = nil) {
        self.name = name
        self.bundleId = bundleId
        self.windowTitle = windowTitle
    }
}

public struct FileContext: Codable, Sendable, Equatable {
    public var path: String?
    public var repo: String?
    public var branch: String?
}

public struct DevContext: Codable, Sendable, Equatable {
    public var terminalCwd: String?
    public var lastCommand: String?
    public var editorFile: String?
}

public struct BrowserContext: Codable, Sendable, Equatable {
    public var url: String?
    public var title: String?
}

public struct InputCadence: Codable, Sendable, Equatable {
    public var keyEvents: Int
    public var mouseEvents: Int
}

public struct SystemContext: Codable, Sendable, Equatable {
    public var onBattery: Bool?
    public var displays: Int?
    public var online: Bool?
    public var network: String?
}

public struct EventRecord: Codable, Sendable, Equatable {
    public var eventId: String
    public var clientSeq: Int
    public var ts: Date
    public var intervalS: Int
    public var activeApp: ActiveApp
    public var fileContext: FileContext?
    public var devContext: DevContext?
    public var browser: BrowserContext?
    public var inputCadence: InputCadence?
    public var system: SystemContext?
    public var evidenceRef: String?

    public init(
        eventId: String = UUID().uuidString,
        clientSeq: Int,
        ts: Date,
        intervalS: Int,
        activeApp: ActiveApp,
        fileContext: FileContext? = nil,
        devContext: DevContext? = nil,
        browser: BrowserContext? = nil,
        inputCadence: InputCadence? = nil,
        system: SystemContext? = nil,
        evidenceRef: String? = nil
    ) {
        self.eventId = eventId
        self.clientSeq = clientSeq
        self.ts = ts
        self.intervalS = intervalS
        self.activeApp = activeApp
        self.fileContext = fileContext
        self.devContext = devContext
        self.browser = browser
        self.inputCadence = inputCadence
        self.system = system
        self.evidenceRef = evidenceRef
    }
}

public struct EventBatchRequest: Codable, Sendable {
    public var schemaVersion: String
    public var deviceId: String
    public var sentAt: Date
    public var events: [EventRecord]
}

public struct RejectedEvent: Codable, Sendable {
    public var eventId: String
    public var reason: String
}

public struct EventBatchResponse: Codable, Sendable {
    public var accepted: Int
    public var duplicates: Int
    public var rejected: [RejectedEvent]
    public var serverSeq: Int
    public var nextPollAfterS: Int?
    public var configEtag: String?
}

public enum TrackerJSON {
    public static let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.keyEncodingStrategy = .convertToSnakeCase
        e.dateEncodingStrategy = .iso8601
        return e
    }()

    public static let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        d.dateDecodingStrategy = .iso8601
        return d
    }()
}
