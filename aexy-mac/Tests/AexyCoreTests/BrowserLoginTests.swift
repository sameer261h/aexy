import XCTest
@testable import AexyCore

// Tests for the loopback callback parser used by browser sign-in.
final class BrowserLoginTests: XCTestCase {
    func testParsesTokenFromCallbackLine() {
        let req = "GET /callback?token=abc123 HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n"
        XCTAssertEqual(parseTokenFromRequest(req), "abc123")
    }

    func testParsesTokenAmongOtherParams() {
        let req = "GET /callback?foo=1&token=xyz&bar=2 HTTP/1.1\r\n\r\n"
        XCTAssertEqual(parseTokenFromRequest(req), "xyz")
    }

    func testPercentDecodesToken() {
        let req = "GET /callback?token=a%2Bb%3Dc HTTP/1.1\r\n\r\n"
        XCTAssertEqual(parseTokenFromRequest(req), "a+b=c")
    }

    func testNilWhenNoToken() {
        XCTAssertNil(parseTokenFromRequest("GET /callback?foo=1 HTTP/1.1\r\n\r\n"))
    }

    func testNilWhenNoQuery() {
        XCTAssertNil(parseTokenFromRequest("GET /callback HTTP/1.1\r\n\r\n"))
    }

    func testNilOnGarbage() {
        XCTAssertNil(parseTokenFromRequest(""))
        XCTAssertNil(parseTokenFromRequest("nonsense"))
    }
}
