# OpenObserve → Aexy Tickets

Route alerts from OpenObserve (and other observability platforms) into Aexy's
ticketing system. A recurring error opens **one** ticket; repeat firings bump
that ticket instead of spawning duplicates, and each ticket is auto-populated
with severity, log context, affected service, and trace links.

The same pipeline accepts Grafana / Datadog / Sentry once an adapter is added
(`backend/src/aexy/integrations/alert_providers/`); OpenObserve ships today.

## How it works

```
OpenObserve alert ──▶ POST /api/v1/webhooks/alerts/{token}
                        (HMAC/secret verified, rate-limited, ACKed immediately)
                          │
                          ▼  Temporal (process_alert_event)
                     normalize → fingerprint → routing rules → dedup
                          │
      ┌───────────────────┼────────────────────────┐
      ▼                   ▼                         ▼
 open ticket exists   recently closed          nothing matches
 → bump + comment     → reopen                 → create populated ticket
 (comment throttled)  (flapping guard)
```

The one-open-ticket-per-error guarantee is enforced by a partial unique index
(`uq_tickets_open_dedup` on `workspace_id, dedup_key` where status is open), so
even simultaneous alert deliveries can't create duplicates.

## Setup

### 1. Create the integration in Aexy

`POST /api/v1/workspaces/{workspace_id}/alert-integrations` (admin):

```json
{
  "provider": "openobserve",
  "name": "OpenObserve prod",
  "base_url": "https://openobserve.your-company.com",
  "default_form_id": "<ticket-form-id>",
  "routing_rules": [
    { "match": { "service": "payments-*", "severity_gte": "high" },
      "team_id": "<team>", "priority": "urgent" },
    { "match": { "service": "*" }, "team_id": "<platform-team>" }
  ],
  "dedup_window_minutes": 60,
  "comment_throttle_minutes": 15,
  "auto_resolve": true
}
```

The response includes `webhook_url` and `signing_secret` (**shown once** — store
it). Rotate later via `POST .../{id}/rotate-secret`.

### 2. Add a Destination in OpenObserve

`Alerts → Destinations → Add`:

| Field | Value |
|---|---|
| URL | the `webhook_url` from step 1 |
| Method | `POST` |
| Header | `X-Aexy-Signature: <signing_secret>` |

Aexy accepts the signature header either as the raw secret or as an
HMAC-SHA256 hex digest of the request body (`sha256=` prefix optional), so it
works whether or not your OpenObserve version can compute an HMAC.

### 3. Use this alert Template

```json
{
  "alert_name": "{alert_name}",
  "service": "payments-api",
  "severity": "critical",
  "environment": "prod",
  "stream": "{stream_name}",
  "start_time": "{alert_start_time}",
  "alert_url": "{alert_url}",
  "count": "{alert_count}",
  "rows": "{rows}"
}
```

- **`service`** and **`severity`** — set per alert (or derive from the stream).
  Severity accepts `critical|high|medium|low` and common synonyms (`error`,
  `warn`, `sev1`…). Missing → `medium`.
- **`rows`** — the matched log lines; becomes the ticket's **log context** and
  is scanned for `trace_id=…` to build trace deep links off `base_url`.
- **`alert_url`** — deep link back to the source alert.
- To signal recovery, send a paired alert with `"status": "resolved"`; with
  `auto_resolve` on, Aexy resolves the linked ticket.

**Convention:** one OpenObserve alert per *kind* of error per service (e.g.
`payments-api 5xx spike`). The fingerprint is
`provider:service:normalized_alert_name`, where the alert name has volatile
tokens (uuids, timestamps, hex ids, numbers) stripped — so `OOM in worker-7f9c`
and `OOM in worker-2b1a` collapse to one ticket, while `5xx spike` and `4xx
spike` stay separate. Override with `fingerprint_template` (e.g.
`"{service}:{alert_name}:{environment}"`) for per-environment tickets.

### 4. Test it

`POST .../{id}/test` with a sample payload runs the full pipeline synchronously
and returns `{action_taken, ticket_id, fingerprint}`. Inspect delivery history
at `GET .../{id}/events` — each row shows what happened (`created` / `updated` /
`throttled` / `reopened` / `resolved` / `dropped`) and the resulting ticket.

## Populated ticket fields

| Field | Source |
|---|---|
| `severity`, `priority` | alert severity + matched routing rule |
| `source` | `openobserve` |
| `field_values.service_name` | affected microservice |
| `field_values.log_context` | log excerpt from `rows` (≤50 lines / 32 KB) |
| `field_values.trace_ids` / `trace_links` | trace IDs + `base_url` deep links |
| `field_values.alert_url` | link to the source alert |
| `field_values.occurrence_count` / `first_seen` | incident timeline |

## Automations

`alert.ticket_created` and `alert.ticket_updated` are registered triggers for
the **tickets** module, so no-code automations can react — e.g. "when an alert
ticket is created with severity=critical → Slack #incidents + notify on-call".

## Tuning

- **Duplicate tickets for the same error** → fingerprint too fine. Simplify the
  alert name or set a `fingerprint_template`.
- **Unrelated errors merged** → fingerprint too coarse. Make alert names more
  specific per failure mode.
- **Comment floods** → raise `comment_throttle_minutes` (counters still update
  every occurrence regardless).
- **Flapping** → `dedup_window_minutes` controls how long after close a
  recurrence reopens vs. opens fresh.
