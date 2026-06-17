# Aexy (macOS)

The macOS capture client for Aexy — a lightweight menu-bar app that
samples semantic work signals and uploads them to the Aexy cloud Tracker module,
where the AI loop turns them into attributed time, journals, and insights.

See the product spec (`docs/aexy-tracker.md`) and the ingest contract
(`docs/api/tracker-ingest.md`) at the repo root.

## Layout

```
Sources/
  AexyCore/      # headless, testable core
    EventRecord.swift   #   wire model (snake_case ↔ ingest contract §4)
    Config.swift        #   runtime config + persistent device id
    LocalBuffer.swift   #   offline-first, append-only buffer (actor)
    Collectors.swift    #   frontmost app / window title / idle (NSWorkspace, AX, CGEventSource)
    SyncUploader.swift   #   batched, idempotent POST /tracker/events:batch
    TrackerClient.swift #   the sample → buffer → flush loop
  Aexy/
    main.swift          # menu-bar app (NSStatusItem, accessory policy)
Tests/AexyCoreTests/   # XCTest: encoding + buffer semantics
```

## Build & test

```bash
swift build                  # builds core + menu-bar executable
swift test                   # requires full Xcode (XCTest); CI has it
swift run Aexy         # launch the menu-bar app
```

> The command-line-tools-only toolchain can `swift build`/`swift run` but not
> `swift test` (no bundled XCTest). Run tests under a full Xcode install.

## Package as a .app

`swift run` produces an **unbundled** binary with no bundle identifier, so
bundle-dependent APIs (native notifications via `UNUserNotificationCenter`) are
skipped. Build a proper, ad-hoc-signed `.app` to exercise the full app:

```bash
./Packaging/build-app.sh        # → Aexy.app  (release build + ad-hoc sign)
open Aexy.app
```

`Packaging/Info.plist` sets the bundle id (`io.aexy.desktop`) and `LSUIElement`
(menu-bar accessory). For distribution, replace the ad-hoc identity with a
Developer ID, notarize, and add auto-update (e.g. Sparkle).

## Configure (scaffold)

On launch the app resolves credentials in this order:

1. **Keychain** — a credential from a prior sign-in.
2. **`AEXY_TRACKER_TOKEN`** — if set (headless/dev), the app enrolls with that
   token, persists to the Keychain, then starts capture.
3. **Browser sign-in** — otherwise it waits; pick **Sign in → GitHub / Google /
   Microsoft** from the menu. The browser opens to the backend login; after you
   authenticate, the token is captured on a `127.0.0.1` loopback listener,
   exchanged for a long-lived `aexy_…` API token, and the device enrolls. No env
   vars needed. (See `docs/aexy-tracker.md` → "Browser sign-in".)

For headless/dev runs use path 2 with a developer JWT (no browser):

```bash
export AEXY_API_URL="http://localhost:8000/api/v1"
# a developer JWT — e.g. docker exec aexy-backend python scripts/generate_test_token.py --first
export AEXY_TRACKER_TOKEN="eyJ…"
export AEXY_PROJECT_ID="<project-uuid>"   # optional; else the first Tracker-enabled project
export AEXY_SAMPLE_INTERVAL=60             # optional
swift run Aexy
```

The project must have the Tracker module enabled (`settings.tracker_enabled = true`)
and the token's developer must be a member, or enrollment fails. The menu-bar item
shows capture state (`●` running, `❚❚` paused, `…` enrolling, `⚠︎` failed/not
configured) and offers Pause/Resume, Flush now, Sign out, and Quit.

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
