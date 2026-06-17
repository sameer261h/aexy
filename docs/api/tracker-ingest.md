# Tracker Ingest API

The contract between the [Aexy Tracker](../aexy-tracker.md) macOS client and the server. All routes are under `/api/v1/tracker` and authenticate with a developer bearer token (`get_current_developer`). Source: `backend/src/aexy/api/tracker_ingest.py`, schemas in `backend/src/aexy/schemas/tracker_ingest.py`.

Design principles:
- **Append-only & idempotent.** Events are keyed by a client-generated `event_id`; re-uploading a batch never double-stores or double-attributes.
- **Server-derived semantics.** The client sends only raw signals; `category` and `attribution` are computed server-side and are intentionally absent from the request schema.
- **Partial success.** A batch with some invalid events still accepts the valid ones and reports the rest as `rejected`.
- **Fail-open rate limiting.** Sliding-window limits via Redis; if Redis is down, requests are allowed.

## Sign-in (native app)

### `GET /auth/device/login?provider={github|google|microsoft}&port={1024..65535}`
Entry point for the desktop app's browser sign-in (RFC 8252 loopback). Validates the provider + loopback port, then 302-redirects into the normal `GET /auth/{provider}/login?redirect_url=http://127.0.0.1:{port}/callback` flow. After the user authenticates, the provider callback 302s the developer JWT to that loopback callback, where the app captures it and exchanges it (via `POST /developers/me/api-tokens`) for a long-lived `aexy_…` token used as the ingest bearer. The host is server-forced to `127.0.0.1`, so the JWT can only ever be delivered to the local machine.

## Endpoints

### `GET /tracker/projects`
Projects the caller can bind a device to (member + `settings.tracker_enabled = true`). Returns `[{ id, name, slug }]`.

### `POST /tracker/devices:enroll`
Register or re-bind a device. The server resolves `developer_id` from the token and stores the device → project binding. Re-enrollment can re-point an existing device (must belong to the caller). Does **not** mint a new token — the client keeps using its bearer token for ingest.

Request: `{ device_id, project_id, name?, platform="macos" }` → `201 { device_id, project_id, config }` where `config` is the capture config (see below).

### `POST /tracker/events:batch`
Ingest a batch of samples. Idempotent on `event_id`; partial success.

Request:
```json
{
  "schema_version": "1.0",
  "device_id": "<uuid>",
  "sent_at": "2026-06-17T10:00:00Z",
  "events": [ { "event_id": "...", "client_seq": 1, "ts": "...", "interval_s": 60,
               "active_app": { "name": "...", "bundle_id": "...", "window_title": "..." },
               "file_context": {...}, "dev_context": {...}, "browser": {...},
               "input_cadence": { "key_events": 0, "mouse_events": 0 },
               "meeting": {...}, "system": {...}, "evidence_ref": null } ]
}
```
Response: `{ accepted, duplicates, rejected: [{event_id, reason}], server_seq, next_poll_after_s, config_etag }`.

Validation:
- `schema_version` must start with `1.` (else `409`).
- `interval_s` ∈ `[1, 600]`; up to **500 events** per batch.
- `ts` must fall within `[now − 30d, now + 5m]` (clock-skew + backfill guard); out-of-range events are `rejected` (`reason="ts_out_of_range"`), not fatal.
- Duplicate `event_id`s (within the batch or already stored) are counted in `duplicates` and not re-stored.
- `accepted + duplicates + rejected` reconciles to the events sent.

Accepting events kicks the enrich/attribute loop for the project (fire-and-forget, coalesced by a time-bucketed workflow id).

### `POST /tracker/devices:heartbeat?device_id=…`
Liveness ping + config pull. Returns the current `DeviceConfig`.

### `GET /tracker/sync/status?device_id=…`
Returns `{ device_id, server_seq, last_seen_at }` — the server high-water mark so the client can self-heal its local cursor.

### `POST /tracker/evidence:presign?device_id=…`
Presigned RustFS PUT URL for an optional screenshot artifact. Request `{ event_id, content_type, byte_size, sha256 }` → `{ evidence_ref, upload_url, expires_in_s }`. `503` if storage isn't configured.

## Capture config (`DeviceConfig`)

Pushed to the client via enroll/heartbeat; server-controlled:

| Field | Default | Meaning |
|---|---|---|
| `config_etag` | `cfg_0` | Changes when config changes. |
| `sample_interval_s` | 60 | Seconds between samples. |
| `screenshot_policy` | `off` | `off` \| `active_window` \| `full_screen`. |
| `screenshot_every_n_samples` | 5 | Screenshot cadence when enabled. |
| `idle_threshold_s` | 300 | Above this idle time the client stops capturing. |
| `paused` | `false` | Remote kill-switch. |
| `excluded_bundle_ids` | `[]` | App bundle IDs to never capture. |

## Rate limits (sliding window, fail-open)

| Key | Limit / 60s |
|---|---|
| batches per device | 30 |
| batches per project | 600 |
| events per project | 50,000 |
| presigns per device | 60 |

Exceeding a limit returns `429`. If Redis is unavailable, limits are skipped (fail-open).

## Privacy

`input_cadence` carries aggregate **counts only** (`key_events`, `mouse_events`) — never keystroke content (`extra="forbid"` rejects unexpected fields). `category` and `attribution` are server-derived and rejected if sent by the client. Screenshots require an explicit non-`off` `screenshot_policy`.
