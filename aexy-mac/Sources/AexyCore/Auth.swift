import Foundation
import Security

#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

// OAuth 2.0 Device Authorization Grant + Keychain token storage for onboarding
// (docs/aexy-tracker.md §6, docs/api/tracker-ingest.md §2). In a shipping build the
// scoped device token is obtained by signing in at aexy.io and is stored in the
// macOS Keychain so capture can resume without re-auth.
//
// NOTE: the aexy.io OAuth endpoints (device-code + token) are an EXTERNAL backend
// dependency that does not need to exist for this code to compile/build. The flow
// below is the RFC 8628 client side; the server endpoints must be added later
// (see the report / DeviceCodeConfig defaults below).

// MARK: - Keychain storage

/// Persisted credential: the scoped device token plus the binding it was issued
/// for (project + api base url), so a relaunch can skip onboarding entirely.
public struct StoredCredential: Codable, Sendable, Equatable {
    public var token: String
    public var projectId: String
    public var apiBaseURL: String

    public init(token: String, projectId: String, apiBaseURL: String) {
        self.token = token
        self.projectId = projectId
        self.apiBaseURL = apiBaseURL
    }
}

/// Thin, nil-safe wrapper over the Security framework `SecItem` APIs storing a
/// single generic-password item (the encoded `StoredCredential`) under a service
/// name. No force-unwraps; every failure path returns nil / false.
public struct KeychainTokenStore: Sendable {
    public let service: String
    public let account: String

    /// `service` defaults to the app bundle identity; tests inject a unique
    /// service so they never collide with a real install.
    public init(service: String = "io.aexy", account: String = "device-credential") {
        self.service = service
        self.account = account
    }

    private func baseQuery() -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
    }

    /// Save (upsert) the credential. Returns false if encoding or the SecItem
    /// write fails (e.g. `errSecMissingEntitlement` in a sandboxless CLI).
    @discardableResult
    public func save(_ credential: StoredCredential) -> Bool {
        guard let data = try? JSONEncoder().encode(credential) else { return false }

        // Delete any existing item first so this is a clean upsert.
        SecItemDelete(baseQuery() as CFDictionary)

        var attributes = baseQuery()
        attributes[kSecValueData as String] = data
        attributes[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlock

        let status = SecItemAdd(attributes as CFDictionary, nil)
        return status == errSecSuccess
    }

    /// Load the stored credential, or nil if absent / unreadable.
    public func load() -> StoredCredential? {
        var query = baseQuery()
        query[kSecReturnData as String] = kCFBooleanTrue
        query[kSecMatchLimit as String] = kSecMatchLimitOne

        var item: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        guard status == errSecSuccess, let data = item as? Data else { return nil }
        return try? JSONDecoder().decode(StoredCredential.self, from: data)
    }

    /// Delete the stored credential. Returns true if it was removed or already
    /// absent; false only on an unexpected SecItem error.
    @discardableResult
    public func delete() -> Bool {
        let status = SecItemDelete(baseQuery() as CFDictionary)
        return status == errSecSuccess || status == errSecItemNotFound
    }
}

// MARK: - Device-code flow models

/// Response to the device-authorization request (RFC 8628 §3.2).
public struct DeviceCodeResponse: Codable, Sendable, Equatable {
    public var deviceCode: String
    public var userCode: String
    public var verificationUri: String
    public var verificationUriComplete: String?
    public var expiresIn: Int
    public var interval: Int?
}

/// Successful token response (RFC 6749 §5.1). Only the fields the client needs.
public struct DeviceTokenResponse: Codable, Sendable, Equatable {
    public var accessToken: String
    public var tokenType: String?
    public var expiresIn: Int?
    public var scope: String?
}

/// Error body while polling (RFC 8628 §3.5: authorization_pending, slow_down,
/// access_denied, expired_token).
public struct DeviceTokenError: Codable, Sendable, Equatable {
    public var error: String
    public var errorDescription: String?
}

public enum DeviceAuthError: Error, Sendable, Equatable {
    case accessDenied
    case expiredToken
    case transport(String)
    case unexpectedStatus(Int)
    case decode
    case server(String)
}

/// Endpoints + client identity for the device-code grant. Defaults point at the
/// (not-yet-implemented) aexy.io OAuth surface; override in tests.
public struct DeviceCodeConfig: Sendable {
    public var deviceCodeURL: URL
    public var tokenURL: URL
    public var clientId: String
    public var scope: String

    public init(
        deviceCodeURL: URL,
        tokenURL: URL,
        clientId: String = "aexy-mac",
        scope: String = "tracker:read tracker:write"
    ) {
        self.deviceCodeURL = deviceCodeURL
        self.tokenURL = tokenURL
        self.clientId = clientId
        self.scope = scope
    }

    /// Standard aexy OAuth surface (EXTERNAL dependency — must be added
    /// server-side; see report). Base e.g. https://server.aexy.io
    public static func aexy(authBase: URL) -> DeviceCodeConfig {
        DeviceCodeConfig(
            deviceCodeURL: authBase.appendingPathComponent("oauth/device/code"),
            tokenURL: authBase.appendingPathComponent("oauth/token")
        )
    }
}

// MARK: - Device-code authenticator

/// Client side of the OAuth 2.0 Device Authorization Grant (RFC 8628).
/// `requestCode()` kicks off the flow; `poll(for:)` blocks until the user
/// authorizes (or the request expires / is denied), honoring `slow_down`.
public struct DeviceCodeAuthenticator: Sendable {
    private let config: DeviceCodeConfig
    private let session: URLSession

    public init(config: DeviceCodeConfig, session: URLSession = .shared) {
        self.config = config
        self.session = session
    }

    /// Step 1 — request a device + user code. The caller shows `userCode` and
    /// `verificationUri` to the user.
    public func requestCode() async throws -> DeviceCodeResponse {
        var request = URLRequest(url: config.deviceCodeURL)
        request.httpMethod = "POST"
        request.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.httpBody = Self.form([
            "client_id": config.clientId,
            "scope": config.scope,
        ])

        let (data, response) = try await perform(request)
        guard (200..<300).contains(response.statusCode) else {
            throw DeviceAuthError.unexpectedStatus(response.statusCode)
        }
        guard let decoded = try? TrackerJSON.decoder.decode(DeviceCodeResponse.self, from: data) else {
            throw DeviceAuthError.decode
        }
        return decoded
    }

    /// Step 2 — poll the token endpoint until the grant resolves. Returns the
    /// access token string on success. Respects the server `interval` and
    /// `slow_down` backoff, and gives up when `expires_in` elapses.
    public func poll(for code: DeviceCodeResponse) async throws -> String {
        var interval = max(1, code.interval ?? 5)
        let deadline = Date().addingTimeInterval(TimeInterval(code.expiresIn))

        while Date() < deadline {
            try await Self.sleep(seconds: interval)

            var request = URLRequest(url: config.tokenURL)
            request.httpMethod = "POST"
            request.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
            request.setValue("application/json", forHTTPHeaderField: "Accept")
            request.httpBody = Self.form([
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "device_code": code.deviceCode,
                "client_id": config.clientId,
            ])

            let (data, response) = try await perform(request)

            if (200..<300).contains(response.statusCode) {
                guard let token = try? TrackerJSON.decoder.decode(DeviceTokenResponse.self, from: data) else {
                    throw DeviceAuthError.decode
                }
                return token.accessToken
            }

            // 400 carries an RFC 8628 error code; decide whether to keep polling.
            guard let err = try? TrackerJSON.decoder.decode(DeviceTokenError.self, from: data) else {
                throw DeviceAuthError.unexpectedStatus(response.statusCode)
            }
            switch err.error {
            case "authorization_pending":
                continue
            case "slow_down":
                interval += 5   // RFC 8628 §3.5: increase the poll interval.
            case "access_denied":
                throw DeviceAuthError.accessDenied
            case "expired_token":
                throw DeviceAuthError.expiredToken
            default:
                throw DeviceAuthError.server(err.error)
            }
        }
        throw DeviceAuthError.expiredToken
    }

    // MARK: helpers

    private func perform(_ request: URLRequest) async throws -> (Data, HTTPURLResponse) {
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch {
            throw DeviceAuthError.transport(error.localizedDescription)
        }
        guard let http = response as? HTTPURLResponse else {
            throw DeviceAuthError.transport("non-HTTP response")
        }
        return (data, http)
    }

    static func form(_ params: [String: String]) -> Data {
        let encoded = params.map { key, value in
            let v = value.addingPercentEncoding(withAllowedCharacters: .urlQueryValueAllowed) ?? value
            return "\(key)=\(v)"
        }.joined(separator: "&")
        return Data(encoded.utf8)
    }

    static func sleep(seconds: Int) async throws {
        try await Task.sleep(nanoseconds: UInt64(max(0, seconds)) * 1_000_000_000)
    }
}

extension CharacterSet {
    /// Allowed characters for `application/x-www-form-urlencoded` values.
    static let urlQueryValueAllowed: CharacterSet = {
        var set = CharacterSet.alphanumerics
        set.insert(charactersIn: "-._~")
        return set
    }()
}
