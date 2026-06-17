import XCTest
@testable import AexyTrackerCore

// Tests for the onboarding/auth pieces (docs/aexy-tracker.md §6): Keychain round-trip
// and Codable decoding of the device-code + token responses.
//
// NOTE: `swift test` cannot run here (no bundled XCTest); these must COMPILE and
// be correct. Keychain access may fail headlessly (errSecMissingEntitlement) in
// a CLI context — the round-trip test tolerates that and still asserts the
// store's nil-safe contract.

final class KeychainTokenStoreTests: XCTestCase {
    private func uniqueStore() -> KeychainTokenStore {
        KeychainTokenStore(service: "io.aexy.tracker.tests.\(UUID().uuidString)")
    }

    func testSaveLoadDeleteRoundTrip() {
        let store = uniqueStore()
        let cred = StoredCredential(
            token: "trk_abc_secret",
            projectId: "proj_42",
            apiBaseURL: "https://aexy.io/api/v1"
        )

        let saved = store.save(cred)
        if !saved {
            // Headless CLI without Keychain entitlement — load must be nil and
            // delete must remain safe (no crash, no false success on a phantom).
            XCTAssertNil(store.load())
            XCTAssertTrue(store.delete())
            return
        }

        let loaded = store.load()
        XCTAssertEqual(loaded, cred)

        XCTAssertTrue(store.delete())
        XCTAssertNil(store.load())
    }

    func testLoadMissingReturnsNil() {
        let store = uniqueStore()
        XCTAssertNil(store.load())
    }
}

final class DeviceCodeDecodingTests: XCTestCase {
    func testDecodesDeviceCodeResponseSnakeCase() throws {
        let body = """
        {
          "device_code": "dc_9f1c",
          "user_code": "WDJB-MJHT",
          "verification_uri": "https://aexy.io/device",
          "verification_uri_complete": "https://aexy.io/device?code=WDJB-MJHT",
          "expires_in": 900,
          "interval": 5
        }
        """
        let decoded = try TrackerJSON.decoder.decode(DeviceCodeResponse.self, from: Data(body.utf8))
        XCTAssertEqual(decoded.deviceCode, "dc_9f1c")
        XCTAssertEqual(decoded.userCode, "WDJB-MJHT")
        XCTAssertEqual(decoded.verificationUri, "https://aexy.io/device")
        XCTAssertEqual(decoded.verificationUriComplete, "https://aexy.io/device?code=WDJB-MJHT")
        XCTAssertEqual(decoded.expiresIn, 900)
        XCTAssertEqual(decoded.interval, 5)
    }

    func testDecodesTokenResponseSnakeCase() throws {
        let body = """
        {"access_token": "trk_xyz_secret", "token_type": "Bearer", "expires_in": 3600, "scope": "tracker:read tracker:write"}
        """
        let decoded = try TrackerJSON.decoder.decode(DeviceTokenResponse.self, from: Data(body.utf8))
        XCTAssertEqual(decoded.accessToken, "trk_xyz_secret")
        XCTAssertEqual(decoded.tokenType, "Bearer")
        XCTAssertEqual(decoded.expiresIn, 3600)
        XCTAssertEqual(decoded.scope, "tracker:read tracker:write")
    }

    func testDecodesTokenErrorSnakeCase() throws {
        let body = """
        {"error": "authorization_pending", "error_description": "still waiting"}
        """
        let decoded = try TrackerJSON.decoder.decode(DeviceTokenError.self, from: Data(body.utf8))
        XCTAssertEqual(decoded.error, "authorization_pending")
        XCTAssertEqual(decoded.errorDescription, "still waiting")
    }

    func testDecodesProjectsList() throws {
        let body = """
        [
          {"id": "p1", "name": "Aexy Core", "slug": "aexy-core"},
          {"id": "p2", "name": "Tracker", "slug": "tracker"}
        ]
        """
        let projects = try TrackerJSON.decoder.decode([TrackerProject].self, from: Data(body.utf8))
        XCTAssertEqual(projects.count, 2)
        XCTAssertEqual(projects.first?.id, "p1")
        XCTAssertEqual(projects.last?.slug, "tracker")
    }

    func testFormEncodingPercentEscapes() {
        let data = DeviceCodeAuthenticator.form(["scope": "tracker:read tracker:write"])
        let s = String(decoding: data, as: UTF8.self)
        // Space and ':' must be percent-encoded for x-www-form-urlencoded.
        XCTAssertFalse(s.contains(" "))
        XCTAssertTrue(s.contains("scope="))
    }
}
