import Foundation

#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

// Orchestrates first-run onboarding (AEXY_TRACKER.md §6):
//   1. OAuth 2.0 device-code grant → scoped device token.
//   2. GET /tracker/projects → list Tracker-enabled projects, user picks one.
//   3. POST /tracker/devices:enroll → bind device to project, persist to Keychain.
// Returns a fully-populated TrackerConfig ready for the capture loop.
//
// NOTE: the device-code OAuth endpoints are an EXTERNAL aexy.io dependency that
// need not exist for this to build (see Auth.swift). The /tracker/projects and
// /tracker/devices:enroll endpoints are defined in AEXY_TRACKER_INGEST_API.md §3.

// MARK: - Wire models

/// One row of `GET /tracker/projects` (AEXY_TRACKER_INGEST_API.md §3).
public struct TrackerProject: Codable, Sendable, Equatable, Identifiable {
    public var id: String
    public var name: String
    public var slug: String
}

/// `POST /tracker/devices:enroll` request body. The server resolves
/// developer_id from the bearer token; we supply the device + chosen project.
public struct EnrollRequest: Codable, Sendable {
    public var deviceId: String
    public var projectId: String
    public var name: String
    public var platform: String

    public init(deviceId: String, projectId: String, name: String, platform: String = "macos") {
        self.deviceId = deviceId
        self.projectId = projectId
        self.name = name
        self.platform = platform
    }
}

/// `POST /tracker/devices:enroll` response. The server (DeviceEnrollResponse)
/// returns the bound device + project; it does NOT mint a separate token — the
/// device keeps using the device-code token for ingest, so `token` is optional.
public struct EnrollResponse: Codable, Sendable, Equatable {
    public var token: String?
    public var projectId: String
    public var deviceId: String?
}

public enum OnboardingError: Error, Sendable, Equatable {
    case noTrackerProjects        // §6.5: no project has the Tracker module enabled.
    case selectionFailed
    case unexpectedStatus(Int)
    case transport(String)
    case decode
}

// MARK: - Onboarding

public struct Onboarding: Sendable {
    /// Picks which project to enroll into. The scaffold default takes the first
    /// project; a real build injects a UI picker (menu-bar / sheet). Returning
    /// nil aborts onboarding.
    public typealias ProjectSelector = @Sendable ([TrackerProject]) -> TrackerProject?

    /// Surfaces the user_code + verification_uri so the UI can prompt the user
    /// ("Sign in at <url> and enter <code>"). Defaults to printing.
    public typealias CodePresenter = @Sendable (DeviceCodeResponse) -> Void

    public let apiBaseURL: URL
    public let authenticator: DeviceCodeAuthenticator
    public let deviceId: String
    public let deviceName: String
    public let session: URLSession
    public let selectProject: ProjectSelector
    public let presentCode: CodePresenter
    public let keychain: KeychainTokenStore

    public init(
        apiBaseURL: URL,
        authenticator: DeviceCodeAuthenticator,
        deviceId: String = PersistentDeviceID.load(),
        deviceName: String = Onboarding.defaultDeviceName(),
        session: URLSession = .shared,
        keychain: KeychainTokenStore = KeychainTokenStore(),
        selectProject: @escaping ProjectSelector = { $0.first },
        presentCode: @escaping CodePresenter = { code in
            NSLog("Aexy Tracker: sign in at \(code.verificationUri) and enter code \(code.userCode)")
        }
    ) {
        self.apiBaseURL = apiBaseURL
        self.authenticator = authenticator
        self.deviceId = deviceId
        self.deviceName = deviceName
        self.session = session
        self.keychain = keychain
        self.selectProject = selectProject
        self.presentCode = presentCode
    }

    /// Run the full flow and return a persisted, ready-to-use config.
    public func run() async throws -> TrackerConfig {
        // 1. Device-code grant.
        let code = try await authenticator.requestCode()
        presentCode(code)
        let token = try await authenticator.poll(for: code)

        // 2. List Tracker-enabled projects and pick one.
        let projects = try await fetchProjects(token: token)
        guard !projects.isEmpty else { throw OnboardingError.noTrackerProjects }
        guard let project = selectProject(projects) else { throw OnboardingError.selectionFailed }

        // 3. Enroll the device. The server reuses the device-code token for
        //    ingest auth, so fall back to it when enroll mints no token.
        let enrolled = try await enroll(token: token, project: project)
        let bearerToken = enrolled.token ?? token

        // 4. Persist to the Keychain so relaunches skip onboarding.
        let credential = StoredCredential(
            token: bearerToken,
            projectId: enrolled.projectId,
            apiBaseURL: apiBaseURL.absoluteString
        )
        _ = keychain.save(credential)

        return TrackerConfig(
            apiBaseURL: apiBaseURL,
            bearerToken: bearerToken,
            deviceId: enrolled.deviceId ?? deviceId,
            projectId: enrolled.projectId
        )
    }

    // MARK: steps

    private func fetchProjects(token: String) async throws -> [TrackerProject] {
        var request = URLRequest(url: apiBaseURL.appendingPathComponent("tracker/projects"))
        request.httpMethod = "GET"
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")

        let (data, http) = try await perform(request)
        guard http.statusCode == 200 else { throw OnboardingError.unexpectedStatus(http.statusCode) }
        guard let projects = try? TrackerJSON.decoder.decode([TrackerProject].self, from: data) else {
            throw OnboardingError.decode
        }
        return projects
    }

    private func enroll(token: String, project: TrackerProject) async throws -> EnrollResponse {
        var request = URLRequest(url: apiBaseURL.appendingPathComponent("tracker/devices:enroll"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        let body = EnrollRequest(deviceId: deviceId, projectId: project.id, name: deviceName)
        request.httpBody = try? TrackerJSON.encoder.encode(body)

        let (data, http) = try await perform(request)
        guard (200..<300).contains(http.statusCode) else {
            throw OnboardingError.unexpectedStatus(http.statusCode)
        }
        guard let decoded = try? TrackerJSON.decoder.decode(EnrollResponse.self, from: data) else {
            throw OnboardingError.decode
        }
        return decoded
    }

    private func perform(_ request: URLRequest) async throws -> (Data, HTTPURLResponse) {
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch {
            throw OnboardingError.transport(error.localizedDescription)
        }
        guard let http = response as? HTTPURLResponse else {
            throw OnboardingError.transport("non-HTTP response")
        }
        return (data, http)
    }

    /// A human-readable device name for the enrollment record.
    public static func defaultDeviceName() -> String {
        let host = ProcessInfo.processInfo.hostName
        return host.isEmpty ? "Mac" : host
    }
}
