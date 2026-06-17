import Foundation

#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

// Authenticated, batched, idempotent upload to POST /tracker/events:batch
// (docs/api/tracker-ingest.md §3.1). Safe to retry: events are removed from the
// buffer only after the server confirms them (accepted + duplicates + rejected).

public enum SyncError: Error, Sendable {
    case unexpectedStatus(Int)
    case schemaRejected          // 409 — app update required
    case rateLimited(retryAfter: Int?)
    case transport(String)
}

public struct SyncUploader: Sendable {
    private let config: TrackerConfig
    private let session: URLSession

    public init(config: TrackerConfig, session: URLSession = .shared) {
        self.config = config
        self.session = session
    }

    /// Flush one batch. Returns the response on success. On a non-fatal error
    /// (rate limit / 5xx / transport) it throws so the caller keeps the buffer
    /// and backs off.
    @discardableResult
    public func flush(_ buffer: LocalBuffer) async throws -> EventBatchResponse? {
        let batch = await buffer.peekBatch(max: config.maxBatch)
        guard !batch.isEmpty else { return nil }

        let request = EventBatchRequest(
            schemaVersion: config.schemaVersion,
            deviceId: config.deviceId,
            sentAt: Date(),
            events: batch
        )

        var urlRequest = URLRequest(url: config.apiBaseURL.appendingPathComponent("tracker/events:batch"))
        urlRequest.httpMethod = "POST"
        urlRequest.setValue("application/json", forHTTPHeaderField: "Content-Type")
        urlRequest.setValue("Bearer \(config.bearerToken)", forHTTPHeaderField: "Authorization")
        urlRequest.httpBody = try TrackerJSON.encoder.encode(request)

        let (data, response): (Data, URLResponse)
        do {
            (data, response) = try await session.data(for: urlRequest)
        } catch {
            throw SyncError.transport(error.localizedDescription)
        }

        guard let http = response as? HTTPURLResponse else {
            throw SyncError.transport("non-HTTP response")
        }

        switch http.statusCode {
        case 200:
            let decoded = try TrackerJSON.decoder.decode(EventBatchResponse.self, from: data)
            // Remove everything the server accounted for. Rejected events are
            // malformed and will never succeed — drop them too (logged upstream).
            var confirmed = Set(batch.map { $0.eventId })
            // (accepted + duplicates are implicitly the batch minus rejected that
            //  we still want gone; we simply clear the whole peeked batch.)
            confirmed.formUnion(decoded.rejected.map { $0.eventId })
            await buffer.remove(ids: confirmed)
            return decoded
        case 409:
            throw SyncError.schemaRejected
        case 429:
            let retry = (http.value(forHTTPHeaderField: "Retry-After")).flatMap { Int($0) }
            throw SyncError.rateLimited(retryAfter: retry)
        case 500...599:
            throw SyncError.unexpectedStatus(http.statusCode)
        default:
            // 400/401/403: surface; the batch is either malformed or auth is bad.
            throw SyncError.unexpectedStatus(http.statusCode)
        }
    }
}
