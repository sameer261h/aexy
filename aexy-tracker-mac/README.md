# Aexy Tracker (macOS)

The macOS capture client for Aexy Tracker — a lightweight menu-bar app that
samples semantic work signals and uploads them to the Aexy cloud Tracker module,
where the AI loop turns them into attributed time, journals, and insights.

See the product spec (`AEXY_TRACKER.md`) and the ingest contract
(`AEXY_TRACKER_INGEST_API.md`) at the repo root.

## Layout

```
Sources/
  AexyTrackerCore/      # headless, testable core
    EventRecord.swift   #   wire model (snake_case ↔ ingest contract §4)
    Config.swift        #   runtime config + persistent device id
    LocalBuffer.swift   #   offline-first, append-only buffer (actor)
    Collectors.swift    #   frontmost app / window title / idle (NSWorkspace, AX, CGEventSource)
    SyncUploader.swift   #   batched, idempotent POST /tracker/events:batch
    TrackerClient.swift #   the sample → buffer → flush loop
  AexyTracker/
    main.swift          # menu-bar app (NSStatusItem, accessory policy)
Tests/AexyTrackerCoreTests/   # XCTest: encoding + buffer semantics
```

## Build & test

```bash
swift build                  # builds core + menu-bar executable
swift test                   # requires full Xcode (XCTest); CI has it
swift run AexyTracker         # launch the menu-bar app
```

> The command-line-tools-only toolchain can `swift build`/`swift run` but not
> `swift test` (no bundled XCTest). Run tests under a full Xcode install.

## Configure (scaffold)

Capture starts when these env vars are present (a shipping build replaces this
with the OAuth device-code onboarding + Keychain flow, AEXY_TRACKER.md §6):

```bash
export AEXY_API_URL="https://aexy.io/api/v1"
export AEXY_TRACKER_TOKEN="trk_…"     # scoped device token
export AEXY_SAMPLE_INTERVAL=60         # optional
swift run AexyTracker
```

The menu-bar item shows capture state (`●` running, `❚❚` paused, `⚠︎` not
configured) and offers Pause/Resume, Flush now, and Quit.

## Scope of this scaffold

- **In:** semantic capture (app/window/idle), offline buffer with persistence,
  idempotent batched upload with retry/back-off, idle back-off, menu-bar UI.
- **Out (next):** OAuth device-code onboarding + Keychain token storage; project
  picker; optional evidence screenshots (ScreenCaptureKit); file/git + browser
  collectors; notarized `.app` bundle + Sparkle auto-update.

## How it maps to the contract

`EventRecord` encodes with `.convertToSnakeCase` so Swift `eventId`/`intervalS`
become `event_id`/`interval_s`. `category` and `attribution` are server-derived
and deliberately absent from the model — the client never sends them. The
uploader removes events from the buffer only after the server confirms the
batch, so retries are safe (idempotent on `event_id`).
