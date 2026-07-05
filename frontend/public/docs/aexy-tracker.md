# Aexy Tracker

The Aexy Tracker is a local-first macOS menu-bar app plus a server-side AI pipeline that turns lightweight desktop activity into **attributed time, daily journals, and proactive insights** — with no manual time entry. It is the auto-capture front end for the [Activity Tracking](./tracking.md) module: the inferred time entries and journals it produces show up in the same tracking surfaces.

> **Privacy first.** The tracker captures *metadata only* — app/window titles, file/git/dev context, idle state, and aggregate input **counts** (never keystroke content). Screenshots are off by default. The productivity `category` and task `attribution` are derived **server-side**; the client never sends them.

## Architecture

```
macOS client ──▶ Ingest API ──▶ enrich/attribute ──▶ journal + insights
(Swift menubar)   (/tracker/*)    (Temporal + LLM)      (Temporal + LLM)
                                       │                      │
                                       ▼                      ▼
                              inferred TimeEntry        daily WorkLog +
                              (auto-attributed)         in-app notifications
                                       │
                                       ▼
                     /tracking/tracker UI — timesheet + Q&A + review
```

1. **Capture (macOS client).** On a fixed interval the client samples the active app/window, file/git context, dev context (terminal/editor), browser context, and idle state, then buffers events locally (offline-durable) and uploads them in idempotent batches. See the macOS client section below.
2. **Ingest** (`backend/src/aexy/api/tracker_ingest.py`). Append-only, idempotent-on-`event_id` batches land in `tracker_events`. Contract: [Tracker ingest API](./api/tracker-ingest.md).
3. **Enrich & attribute** (`temporal/activities/tracker_enrich.py`). Consecutive same-signal samples are collapsed into spans; one LLM call per developer categorizes each span (`productive` / `neutral` / `personal`) and maps it to one of the developer's candidate tasks. Productive, attributed spans roll up into **inferred `TimeEntry` rows** (`is_inferred=true`, `source=inferred`, `attribution_status=inferred`), deduped by a deterministic `external_task_ref` (`tracker:<event_id>`).
4. **Journal & insights** (`temporal/activities/tracker_journal.py`). A daily LLM narrative is upserted as a `WorkLog` (idempotent per developer/day); deterministic signals (context switching, meeting load, after-hours, focus fragmentation) surface as deduped in-app notifications.
5. **Review** (`/tracking/tracker`). The developer sees an auto-attributed timesheet and can **confirm**, **reassign** (correct), or **dismiss** each AI-inferred entry, plus ask natural-language questions over their own journals + time.

### Triggering

Enrichment runs two ways (`temporal/dispatch.py`, `temporal/schedules.py`):
- **Real-time:** ingest fires `enrich_attribute_tracker_events` for the project with a time-bucketed `workflow_id` so concurrent batches coalesce.
- **Safety-net sweeps:** `tracker-enrich-sweep` (every 5 min), `tracker-journal-sweep` (every 6 h), `tracker-insights-sweep` (every 3 h).

Concurrent runs can't double-attribute: the pending-event select uses `FOR UPDATE SKIP LOCKED`, and a partial unique index on `time_entries.external_task_ref` (`LIKE 'tracker:%'`) backstops the dedupe.

## Data model

| Table | Purpose |
|---|---|
| `tracker_devices` | Enrolled device → developer + project binding, plus server-controlled capture config (interval, screenshot policy, idle threshold, pause, `excluded_bundle_ids`) and the `server_seq` sync high-water mark. |
| `tracker_events` | Immutable captured samples (idempotent on `(project_id, device_id, id)`). Client signals + server-derived `category` / `attribution` / `enriched_at`. A partial index on `enriched_at IS NULL` drives the pipeline cursor. |
| `time_entries` (existing) | Inferred rows created by the enrich loop. `attribution_status`: `inferred` → `confirmed` \| `corrected` \| `dismissed`. |
| `work_logs` (existing) | Daily journal narratives, keyed by `external_task_ref = tracker-journal:<dev>:<date>`. |

Migrations: `backend/scripts/migrate_tracker_events.sql`, `migrate_tracker_time_entry_dedupe.sql`, `migrate_tracker_attribution_status.sql`.

## Enabling the module

A project must opt in: set `settings.tracker_enabled = true` (JSON boolean) on the `projects` row. Only members of a Tracker-enabled project can enroll a device or list it via `GET /tracker/projects`.

## The timesheet UI (`/tracking/tracker`)

- **Metrics + day-grouped timesheet** of inferred entries with confidence badges; dismissed entries are hidden and excluded from totals.
- **Review actions** per entry: ✓ confirm the AI's attribution, ✎ reassign to one of your assignable tasks (correct), ✗ dismiss. Backed by `PATCH /tracker/timesheet/entries/{id}` and `GET /tracker/candidate-tasks`.
- **Ask AI** (`POST /tracker/qa`): natural-language Q&A over your own journals + inferred time, scoped to the selected date range ("Draft my standup", "What did I ship this week?").

Frontend: `frontend/src/app/(app)/tracking/tracker/page.tsx`, `hooks/useTrackerTimesheet.ts`, `components/tracking/TaskSelect.tsx`. All strings are localized via the `tracking.tracker` i18n namespace (`en`/`hi`).

## macOS client (`aexy-tracker-mac/`)

A SwiftPM menu-bar app (`swift build` / `swift run AexyTracker`; `swift test` needs full Xcode for XCTest). On launch it resolves credentials in order:

1. **Keychain** — a credential from a prior sign-in.
2. **`AEXY_TRACKER_TOKEN`** — if set (headless/dev), the app enrolls with that token, persists to the Keychain, then starts capture.
3. **Browser sign-in** (primary, interactive) — the menu's **Sign in → GitHub / Google / Microsoft** opens the system browser to the backend login; after the user authenticates, the developer JWT is delivered to a local loopback listener, exchanged for a long-lived `aexy_…` API token, and the device enrolls. No env vars needed. See "Browser sign-in" below.

### Browser sign-in (RFC 8252 loopback)

1. The app binds a one-shot HTTP listener on `http://127.0.0.1:<os-port>` (loopback only).
2. It opens the browser to `GET /api/v1/auth/device/login?provider=<p>&port=<port>`, which 302s into the normal `/auth/{provider}/login?redirect_url=http://127.0.0.1:<port>/callback` flow.
3. The user logs in; the provider callback 302s `…/callback?token=<JWT>` to the loopback listener, which captures the JWT and shows a "you can close this window" page.
4. The app exchanges the JWT for a revocable `aexy_…` token via `POST /developers/me/api-tokens` (named per device, 365-day expiry; manage under settings → API tokens) and enrolls the device.

`Sources/AexyTrackerCore/BrowserLogin.swift` runs the listener; `Onboarding.signInViaBrowser(provider:)` ties login → token exchange → enroll. The host is server-forced to loopback so the JWT can only be delivered to the local machine.

Local/dev run (token path, no browser):

```bash
export AEXY_API_URL="http://localhost:8000/api/v1"   # default: https://server.aexy.io/api/v1
export AEXY_TRACKER_TOKEN="<a developer JWT>"          # docker exec aexy-backend python scripts/generate_test_token.py --first
export AEXY_PROJECT_ID="<tracker-enabled project uuid>"  # optional; else first Tracker-enabled project
export AEXY_SAMPLE_INTERVAL=60                          # optional, clamped to 1..600
swift run AexyTracker
```

The menu-bar item shows capture state (`●` running, `❚❚` paused, `…` enrolling, `⚠︎` failed/not configured) and offers Pause/Resume, Flush now, Sign out, Quit. The local buffer is capped to bound offline growth, and events are removed only after the server confirms the batch (safe idempotent retries). See `aexy-tracker-mac/README.md` for layout.

## Related

- [Tracker ingest API](./api/tracker-ingest.md) — the full ingest contract.
- [Activity Tracking](./tracking.md) — the broader tracking module the inferred entries feed.
- [Temporal](./guides/temporal.md) — the workflow engine running the enrich/journal/insight activities.
