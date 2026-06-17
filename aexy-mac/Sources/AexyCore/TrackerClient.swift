import Foundation
import Network

// Wires the pieces together (docs/aexy-tracker.md §4): on a fixed interval, sample
// the active context, buffer it, and flush in batches. Backs off when idle, and
// flushes immediately when network connectivity returns (auto-sync on reconnect).

public actor TrackerClient {
    private let config: TrackerConfig
    private let collector: ActivityCollector
    private let buffer: LocalBuffer
    private let uploader: SyncUploader

    private var clientSeq: Int = 0
    private var samplesSinceFlush = 0
    private var running = false

    private let pathMonitor = NWPathMonitor()
    private let monitorQueue = DispatchQueue(label: "io.aexy.netmonitor")
    private var wasReachable = true

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
        startReachabilityMonitor()
        Task { await loop() }
    }

    public func stop() {
        running = false
        pathMonitor.cancel()
    }

    // MARK: - Auto-sync on reconnect

    private func startReachabilityMonitor() {
        pathMonitor.pathUpdateHandler = { [weak self] path in
            guard let self else { return }
            Task { await self.handleReachability(path.status == .satisfied) }
        }
        pathMonitor.start(queue: monitorQueue)
    }

    private func handleReachability(_ reachable: Bool) async {
        let recovered = reachable && !wasReachable
        wasReachable = reachable
        // On an offline → online transition, push the buffered backlog at once.
        if recovered { await flush() }
    }

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
