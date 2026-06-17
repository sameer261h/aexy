import XCTest
@testable import AexyTrackerCore

final class EventRecordTests: XCTestCase {
    func testEncodesSnakeCaseAndOmitsServerDerivedFields() throws {
        let rec = EventRecord(
            eventId: "11111111-1111-1111-1111-111111111111",
            clientSeq: 7,
            ts: Date(timeIntervalSince1970: 1_750_000_000),
            intervalS: 60,
            activeApp: ActiveApp(name: "VS Code", bundleId: "com.microsoft.VSCode", windowTitle: "main.py")
        )
        let data = try TrackerJSON.encoder.encode(rec)
        let json = String(decoding: data, as: UTF8.self)

        XCTAssertTrue(json.contains("\"event_id\""))
        XCTAssertTrue(json.contains("\"client_seq\""))
        XCTAssertTrue(json.contains("\"interval_s\""))
        XCTAssertTrue(json.contains("\"bundle_id\""))
        XCTAssertTrue(json.contains("\"window_title\""))
        // Server-derived fields are not part of the model and must never be sent.
        XCTAssertFalse(json.contains("category"))
        XCTAssertFalse(json.contains("attribution"))
    }

    func testRoundTrips() throws {
        let rec = EventRecord(
            clientSeq: 1,
            ts: Date(timeIntervalSince1970: 1_750_000_000),
            intervalS: 60,
            activeApp: ActiveApp(name: "Slack", bundleId: "com.tinyspeck.slackmacgap")
        )
        let data = try TrackerJSON.encoder.encode(rec)
        let decoded = try TrackerJSON.decoder.decode(EventRecord.self, from: data)
        XCTAssertEqual(decoded, rec)
    }

    func testDecodesBatchResponseSnakeCase() throws {
        let body = """
        {"accepted": 4, "duplicates": 1, "rejected": [{"event_id":"x","reason":"ts_out_of_range"}],
         "server_seq": 42, "next_poll_after_s": 60, "config_etag": "cfg_7a2"}
        """
        let resp = try TrackerJSON.decoder.decode(EventBatchResponse.self, from: Data(body.utf8))
        XCTAssertEqual(resp.accepted, 4)
        XCTAssertEqual(resp.duplicates, 1)
        XCTAssertEqual(resp.serverSeq, 42)
        XCTAssertEqual(resp.nextPollAfterS, 60)
        XCTAssertEqual(resp.rejected.first?.reason, "ts_out_of_range")
    }
}

final class LocalBufferTests: XCTestCase {
    private func tempBuffer() -> (LocalBuffer, URL) {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("aexy-buffer-\(UUID().uuidString).json")
        return (LocalBuffer(fileURL: url), url)
    }

    private func event(_ seq: Int) -> EventRecord {
        EventRecord(
            eventId: "id-\(seq)",
            clientSeq: seq,
            ts: Date(timeIntervalSince1970: 1_750_000_000 + Double(seq)),
            intervalS: 60,
            activeApp: ActiveApp(name: "VS Code", bundleId: "com.microsoft.VSCode")
        )
    }

    func testAppendPeekRemove() async throws {
        let (buffer, url) = tempBuffer()
        defer { try? FileManager.default.removeItem(at: url) }

        for i in 1...5 { await buffer.append(event(i)) }
        let count = await buffer.count
        XCTAssertEqual(count, 5)

        let batch = await buffer.peekBatch(max: 3)
        XCTAssertEqual(batch.map { $0.eventId }, ["id-1", "id-2", "id-3"])

        // Peek does not remove.
        let stillThere = await buffer.count
        XCTAssertEqual(stillThere, 5)

        await buffer.remove(ids: ["id-1", "id-2", "id-3"])
        let after = await buffer.count
        XCTAssertEqual(after, 2)
    }

    func testPersistenceAcrossInstances() async throws {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("aexy-buffer-\(UUID().uuidString).json")
        defer { try? FileManager.default.removeItem(at: url) }

        let first = LocalBuffer(fileURL: url)
        await first.append(event(1))
        await first.append(event(2))

        // A fresh instance pointed at the same file reloads the buffered events.
        let second = LocalBuffer(fileURL: url)
        let count = await second.count
        XCTAssertEqual(count, 2)
    }
}
