import Foundation
import Network

#if canImport(AppKit)
import AppKit
#endif

// Browser sign-in for the tracker (RFC 8252 native-app loopback flow):
//   1. bind a loopback HTTP listener on 127.0.0.1:<os-assigned port>
//   2. open the system browser to GET /auth/device/login?provider=&port=
//   3. the user logs in; the backend 302s the developer JWT to
//      http://127.0.0.1:<port>/callback?token=<JWT>
//   4. the listener captures the token and the browser tab shows a success page
// The JWT is then exchanged for a long-lived API token (see Onboarding).

public enum BrowserLoginError: Error, Sendable, Equatable {
    case listenerFailed(String)
    case timedOut
    case noToken
    case badURL
}

/// Extract the `token` query param from a raw HTTP request's first line
/// ("GET /callback?token=… HTTP/1.1"). Pure + testable.
public func parseTokenFromRequest(_ request: String) -> String? {
    let firstLine = request.split(whereSeparator: { $0 == "\r" || $0 == "\n" }).first
    guard let line = firstLine else { return nil }
    let parts = line.split(separator: " ")
    guard parts.count >= 2 else { return nil }
    let target = String(parts[1])  // e.g. /callback?token=abc&foo=bar
    guard let qIdx = target.firstIndex(of: "?") else { return nil }
    let query = target[target.index(after: qIdx)...]
    for pair in query.split(separator: "&") {
        let kv = pair.split(separator: "=", maxSplits: 1)
        if kv.count == 2, kv[0] == "token" {
            let value = String(kv[1])
            return value.removingPercentEncoding ?? value
        }
    }
    return nil
}

/// A one-shot loopback HTTP listener that captures the OAuth callback token.
public final class LoopbackReceiver: @unchecked Sendable {
    private let listener: NWListener
    private let queue = DispatchQueue(label: "io.aexy.tracker.loopback")
    private var readyCont: CheckedContinuation<UInt16, Error>?
    private var tokenCont: CheckedContinuation<String, Error>?
    private var buffered: Result<String, Error>?
    private var settled = false

    public init() throws {
        let params = NWParameters.tcp
        params.requiredInterfaceType = .loopback      // 127.0.0.1 only
        params.allowLocalEndpointReuse = true
        self.listener = try NWListener(using: params)  // OS-assigned port
    }

    /// Start listening and return the bound loopback port.
    public func start() async throws -> UInt16 {
        listener.newConnectionHandler = { [weak self] conn in self?.handle(conn) }
        return try await withCheckedThrowingContinuation { cont in
            queue.async {
                self.readyCont = cont
                self.listener.stateUpdateHandler = { [weak self] state in
                    guard let self else { return }
                    switch state {
                    case .ready:
                        if let port = self.listener.port?.rawValue, let c = self.readyCont {
                            self.readyCont = nil
                            c.resume(returning: port)
                        }
                    case .failed(let err):
                        let e = BrowserLoginError.listenerFailed("\(err)")
                        if let c = self.readyCont { self.readyCont = nil; c.resume(throwing: e) }
                        self.deliver(.failure(e))
                    default:
                        break
                    }
                }
                self.listener.start(queue: self.queue)
            }
        }
    }

    /// Await the captured token, or throw after `timeoutSeconds`.
    public func waitForToken(timeoutSeconds: Int = 300) async throws -> String {
        try await withThrowingTaskGroup(of: String.self) { group in
            group.addTask { try await self.awaitToken() }
            group.addTask {
                try await Task.sleep(nanoseconds: UInt64(max(1, timeoutSeconds)) * 1_000_000_000)
                throw BrowserLoginError.timedOut
            }
            defer { group.cancelAll() }
            return try await group.next()!
        }
    }

    public func cancel() {
        queue.async { self.deliver(.failure(BrowserLoginError.timedOut)) }
    }

    private func awaitToken() async throws -> String {
        try await withCheckedThrowingContinuation { cont in
            queue.async {
                if let buffered = self.buffered {
                    cont.resume(with: buffered)
                } else {
                    self.tokenCont = cont
                }
            }
        }
    }

    // Always called on `queue`.
    private func deliver(_ result: Result<String, Error>) {
        guard !settled else { return }
        settled = true
        if let c = tokenCont {
            tokenCont = nil
            c.resume(with: result)
        } else {
            buffered = result
        }
        listener.cancel()
    }

    private func handle(_ conn: NWConnection) {
        conn.start(queue: queue)
        conn.receive(minimumIncompleteLength: 1, maximumLength: 65_536) { [weak self] data, _, _, _ in
            guard let self else { return }
            let raw = data.flatMap { String(data: $0, encoding: .utf8) } ?? ""
            let token = parseTokenFromRequest(raw)
            let body = """
            <html><head><meta charset="utf-8"><title>Aexy Tracker</title></head>\
            <body style="font-family:-apple-system,sans-serif;text-align:center;padding:3rem">\
            <h2>\(token != nil ? "Signed in to Aexy Tracker" : "Sign-in failed")</h2>\
            <p>You can close this window and return to the app.</p></body></html>
            """
            let statusLine = token != nil ? "200 OK" : "400 Bad Request"
            let response = "HTTP/1.1 \(statusLine)\r\n"
                + "Content-Type: text/html; charset=utf-8\r\n"
                + "Content-Length: \(body.utf8.count)\r\n"
                + "Connection: close\r\n\r\n"
                + body
            conn.send(
                content: response.data(using: .utf8),
                completion: .contentProcessed { _ in conn.cancel() }
            )
            self.deliver(token.map { .success($0) } ?? .failure(BrowserLoginError.noToken))
        }
    }
}

/// Open the browser to the backend device-login endpoint and return the JWT
/// the loopback listener captures.
public func loginViaBrowser(
    provider: String,
    apiBaseURL: URL,
    timeoutSeconds: Int = 300
) async throws -> String {
    let receiver = try LoopbackReceiver()
    let port = try await receiver.start()

    guard var comps = URLComponents(
        url: apiBaseURL.appendingPathComponent("auth/device/login"),
        resolvingAgainstBaseURL: false
    ) else { throw BrowserLoginError.badURL }
    comps.queryItems = [
        URLQueryItem(name: "provider", value: provider),
        URLQueryItem(name: "port", value: String(port)),
    ]
    guard let url = comps.url else { throw BrowserLoginError.badURL }

    #if canImport(AppKit)
    await MainActor.run { _ = NSWorkspace.shared.open(url) }
    #endif

    return try await receiver.waitForToken(timeoutSeconds: timeoutSeconds)
}
