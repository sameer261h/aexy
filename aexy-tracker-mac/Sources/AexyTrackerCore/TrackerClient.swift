import Foundation

// Wires the pieces together (docs/aexy-tracker.md §4): on a fixed interval, sample
// the active context, buffer it, and flush in batches. Backs off when idle.

public actor TrackerClient {
    private let config: TrackerConfig
    private let collector: ActivityCollector
    private let buffer: LocalBuffer
    private let uploader: SyncUploader

    private var clientSeq: Int = 0
    private var samplesSinceFlush = 0
    private var running = false

    public init(
        config: TrackerConfig,
        collector: ActivityCollector = MacActivityCollector(),
        buffer: LocalBuffer? = nil,
        uploader: SyncUploader? = nil
    ) {
        self.config = config
        self.collector = collector
        self.buffer = buffer ?? LocalBuffer()
        self.uploader = uploader ?? SyncUploader(config: config)
    }

    public func start() {
        guard !running else { return }
        running = true
        Task { await loop() }
    }

    public func stop() { running = false }

    /// One tick: capture a sample (unless idle) and flush when due. Exposed for
    /// tests; the loop just calls this on a cadence.
    public func tick() async {
        let ctx = collector.sample()

        // Idle handling: above threshold we skip capture and slow to a heartbeat.
        if ctx.idleSeconds > Double(config.idleThresholdS) {
            return
        }

        clientSeq += 1
        let record = EventRecord(
            clientSeq: clientSeq,
            ts: Date(),
            intervalS: config.sampleIntervalS,
            activeApp: ctx.activeApp,
            fileContext: ctx.fileContext,
            devContext: ctx.devContext,
            browser: ctx.browser,
            system: ctx.system
        )
        await buffer.append(record)
        samplesSinceFlush += 1

        if samplesSinceFlush >= config.flushEverySamples {
            await flush()
        }
    }

    public func flush() async {
        do {
            try await uploader.flush(buffer)
            samplesSinceFlush = 0
        } catch SyncError.schemaRejected {
            // Stop hot-looping; a real app would surface "update required".
            samplesSinceFlush = 0
        } catch {
            // Keep the buffer; the next tick retries (idempotent upload).
        }
    }

    private func loop() async {
        while running {
            await tick()
            let seconds = UInt64(max(1, config.sampleIntervalS))
            try? await Task.sleep(nanoseconds: seconds * 1_000_000_000)
        }
    }
}
