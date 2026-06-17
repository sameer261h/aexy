import Foundation

// Runtime configuration for the tracker client. In a shipping build these come
// from onboarding + Keychain (AEXY_TRACKER.md §5–6); for the scaffold they're
// read from environment variables so the loop can be exercised end-to-end.

public struct TrackerConfig: Sendable {
    public var apiBaseURL: URL          // e.g. https://aexy.io/api/v1
    public var bearerToken: String      // scoped device token (Keychain in prod)
    public var deviceId: String         // stable per-install UUID
    public var schemaVersion: String
    public var sampleIntervalS: Int
    public var idleThresholdS: Int
    public var flushEverySamples: Int   // flush after N buffered samples
    public var maxBatch: Int
    public var projectId: String?       // bound project (Keychain/enroll); additive

    public init(
        apiBaseURL: URL,
        bearerToken: String,
        deviceId: String,
        schemaVersion: String = "1.0",
        sampleIntervalS: Int = 60,
        idleThresholdS: Int = 300,
        flushEverySamples: Int = 5,
        maxBatch: Int = 500,
        projectId: String? = nil
    ) {
        self.apiBaseURL = apiBaseURL
        self.bearerToken = bearerToken
        self.deviceId = deviceId
        self.schemaVersion = schemaVersion
        self.sampleIntervalS = sampleIntervalS
        self.idleThresholdS = idleThresholdS
        self.flushEverySamples = flushEverySamples
        self.maxBatch = maxBatch
        self.projectId = projectId
    }

    /// Build from environment, returning nil if required values are missing.
    public static func fromEnvironment(_ env: [String: String] = ProcessInfo.processInfo.environment) -> TrackerConfig? {
        guard let base = env["AEXY_API_URL"], let url = URL(string: base),
              let token = env["AEXY_TRACKER_TOKEN"] else {
            return nil
        }
        let deviceId = env["AEXY_DEVICE_ID"] ?? PersistentDeviceID.load()
        var cfg = TrackerConfig(apiBaseURL: url, bearerToken: token, deviceId: deviceId)
        if let interval = env["AEXY_SAMPLE_INTERVAL"], let n = Int(interval) {
            // Clamp to the server's accepted interval_s range (ge=1, le=600);
            // an out-of-range value would 422 every batch and hot-loop retries.
            cfg.sampleIntervalS = min(600, max(1, n))
        }
        return cfg
    }

    /// Build from a Keychain-stored credential (the onboarding result), returning
    /// nil if nothing is stored or the stored base URL is unparseable.
    public static func fromKeychain(
        store: KeychainTokenStore = KeychainTokenStore(),
        deviceId: String = PersistentDeviceID.load()
    ) -> TrackerConfig? {
        guard let cred = store.load(), let url = URL(string: cred.apiBaseURL) else {
            return nil
        }
        return TrackerConfig(
            apiBaseURL: url,
            bearerToken: cred.token,
            deviceId: deviceId,
            projectId: cred.projectId
        )
    }

    /// Preferred loader: use the Keychain credential from onboarding if present,
    /// otherwise fall back to the environment (scaffold). Returns nil when the app
    /// is not yet configured — the caller should then run onboarding.
    public static func resolve(
        store: KeychainTokenStore = KeychainTokenStore(),
        env: [String: String] = ProcessInfo.processInfo.environment
    ) -> TrackerConfig? {
        fromKeychain(store: store) ?? fromEnvironment(env)
    }
}

/// A stable device UUID persisted under Application Support.
public enum PersistentDeviceID {
    public static func load() -> String {
        let dir = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)
            .first!.appendingPathComponent("AexyTracker", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let file = dir.appendingPathComponent("device_id")
        if let existing = try? String(contentsOf: file, encoding: .utf8),
           !existing.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return existing.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        let id = UUID().uuidString
        try? id.write(to: file, atomically: true, encoding: .utf8)
        return id
    }
}
