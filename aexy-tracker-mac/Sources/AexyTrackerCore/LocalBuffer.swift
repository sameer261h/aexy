import Foundation

// Local-first buffer (docs/aexy-tracker.md §4). Events survive offline and process
// restarts: the in-memory queue is persisted to a JSON file after each mutation.
// A production build would back this with SQLite; the contract only requires
// durable, append-only, idempotent capture.

public actor LocalBuffer {
    private var events: [EventRecord] = []
    private let fileURL: URL
    // Cap the offline backlog so a prolonged outage can't grow memory / the
    // persisted file without bound. Oldest events are dropped first.
    private let maxEvents: Int

    public init(fileURL: URL? = nil, maxEvents: Int = 50_000) {
        self.maxEvents = maxEvents
        if let url = fileURL {
            self.fileURL = url
        } else {
            let dir = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)
                .first!.appendingPathComponent("AexyTracker", isDirectory: true)
            try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
            self.fileURL = dir.appendingPathComponent("buffer.json")
        }
        // Load synchronously in init (cannot await an actor method from here).
        if let data = try? Data(contentsOf: self.fileURL),
           let decoded = try? TrackerJSON.decoder.decode([EventRecord].self, from: data) {
            events = decoded.suffix(maxEvents).map { $0 }
        }
    }

    public var count: Int { events.count }

    public func append(_ event: EventRecord) {
        events.append(event)
        if events.count > maxEvents {
            events.removeFirst(events.count - maxEvents)
        }
        persist()
    }

    /// Take up to `max` oldest events for upload (does not remove them — they are
    /// removed only after the server confirms, keeping retries safe).
    public func peekBatch(max: Int) -> [EventRecord] {
        Array(events.prefix(max))
    }

    /// Remove confirmed events (accepted + duplicates + permanently rejected).
    public func remove(ids: Set<String>) {
        guard !ids.isEmpty else { return }
        events.removeAll { ids.contains($0.eventId) }
        persist()
    }

    // MARK: - Persistence

    private func persist() {
        guard let data = try? TrackerJSON.encoder.encode(events) else { return }
        try? data.write(to: fileURL, options: .atomic)
    }
}
