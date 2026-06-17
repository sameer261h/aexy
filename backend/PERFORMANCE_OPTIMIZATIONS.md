# Backend Performance Optimizations — Backlog

Concrete, code-grounded optimizations for the Aexy Python backend (`backend/src/aexy/`).
The backend is I/O-bound (Postgres + LLM APIs + Temporal), so these target the real
latency sources. A Rust rewrite was evaluated and rejected — no CPU-bound hot path exists.

**Recommended order:** #1 → #2 → #4 → #5 → #3 (effort-to-payoff). Do #1 first (free),
then turn on query logging to find which N+1 endpoints (#2) to attack first.

| # | Change | Effort | Payoff | Risk |
|---|--------|--------|--------|------|
| 1 | orjson global response class | ~1h | Medium, everywhere | Very low |
| 2 | N+1 query fixes on slow endpoints | Days, ongoing | **Highest** | Low |
| 4 | `asyncio.gather` independent awaits | Per-method | High on multi-call paths | Low |
| 5 | Temporal batch activities | Per-flow | High at volume | Medium |
| 3 | Cache LLM + analytics reads | Per-service | High (latency + $) | Medium |

---

## 1. Adopt orjson as the default response class

**Status:** Not implemented. `main.py:53` uses the default stdlib-`json` `JSONResponse`.
`orjson` is not in `pyproject.toml`.

**Why:** orjson is 3–10× faster than stdlib json on the list-heavy endpoints and
serializes `datetime`/`UUID`/dataclasses natively. Global, near-zero-risk win.

**Action:**
- Add `orjson>=3.9` to `pyproject.toml`.
- In `main.py`:
  ```python
  from fastapi.responses import ORJSONResponse

  app = FastAPI(
      title=settings.app_name,
      ...
      default_response_class=ORJSONResponse,
  )
  ```

**Validate:** Run the full test suite after the switch — orjson returns `bytes` and is
stricter (e.g. won't coerce non-string dict keys). Responses pass through Pydantic v2
first, so this is almost always safe.

**Large payload endpoints that benefit most:**
- `api/analysis.py:329` — `result.scalars().all()` (all developers + fingerprints)
- `api/billing.py:101` — `plans = result.scalars().all()`
- `api/tracker_ingest.py:163` — bulk project query

---

## 2. Eliminate N+1 query patterns (highest impact)

**Status:** ~46% of services lack eager loading. Biggest real latency source.

**Two anti-patterns to fix:**

**(a) Lazy relationship access** — `.scalars().all()` then reading `obj.relationship`
per row fires one query per row. Fix at the query:
```python
from sqlalchemy.orm import selectinload, joinedload

select(EmailCampaign).options(selectinload(EmailCampaign.recipients))
```
- `selectinload` → one-to-many (collections)
- `joinedload` → many-to-one (single parent)

**(b) Sequential independent lookups** — separate round-trips that don't depend on each
other (see #4 to gather them) or could be a single join.

**Candidate services flagged (audit + fix):**
- `services/reputation_service.py` — `calculate_domain_health()` ~line 50
- `services/email_campaign_service.py:48–80, 150–180` — multiple sequential lookups
- `services/gtm_analytics_service.py` — no eager loading across the service
- `services/abm_service.py:382` — no joinedload on ABMAccount queries
- `services/github_service.py` — large service, no eager loading

**How to find the worst offenders:** enable SQLAlchemy `echo=True` in dev, or add a
per-request query-count middleware. Attack highest query-count endpoints first.

---

## 3. Use the existing cache layer (LLM + analytics)

**Status:** `cache/analysis_cache.py` and `cache/insights_cache.py` exist (Redis + in-memory
fallback, TTL, JSON) but only ~6 files use them. Expensive LLM services don't cache results.

**Where it pays off:** expensive to compute + read far more than written.
- **LLM-derived outputs** — `insights_ai_service`, `commit_analyzer`,
  `competitor_intel_service` call `gateway.call_llm()` with no caching. Key on a content
  hash of the input → identical inputs never re-hit Claude/Gemini (saves latency **and** spend).
- **Analytics/aggregation reads** — `gtm_analytics_service`, leaderboards, dashboards.
  Short TTL (30–120s) absorbs refresh storms.

**Pattern (reuse existing helper):**
```python
cache = get_analysis_cache()
key = f"insights:{workspace_id}:{hash_inputs(...)}"
if (hit := await cache.get(key)) is not None:
    return hit
result = await expensive_work()
await cache.set(key, result, ttl=300)
return result
```

**The hard part is invalidation.** Only cache where a stale TTL window is tolerable, or
the key can be busted cleanly on write. Don't cache mutable user state without an
invalidation hook.

---

## 4. Parallelize independent awaits with `asyncio.gather`

**Status:** Only ~6 `asyncio.gather` sites. Most multi-step methods await sequentially
even when steps are independent.

**Action — gather only truly independent operations:**
```python
# before: ~2× latency
a = await gateway.call_llm(prompt_a)
b = await gateway.call_llm(prompt_b)

# after: ~1× latency
a, b = await asyncio.gather(
    gateway.call_llm(prompt_a),
    gateway.call_llm(prompt_b),
)
```

**Good existing examples to mirror:** `services/seo_audit_service.py:455`,
`services/ai_feedback_service.py:154`.

**Cautions (stack-specific):**
- **Never share one `AsyncSession` across gathered DB queries** — asyncpg sessions are not
  concurrency-safe. Gather is for independent LLM/HTTP calls; use a session-per-branch for DB.
- Bound fan-out with a `Semaphore` when gathering over a list, to respect the LLM rate
  limiter and the connection pool.

(Blocking-call audit: clean — httpx everywhere, no `requests.`/`time.sleep` in async paths.)

---

## 5. Batch Temporal dispatches (fewer, fatter activities)

**Status:** `dispatch()` (`temporal/dispatch.py:170`) starts one workflow per call.
Per-item loops mean one workflow execution per row — Temporal overhead × N.

**Offenders:**
- `services/email_campaign_service.py:106` — loops 50 recipients, one `dispatch()` each → 50 workflows/batch
- `temporal/activities/tracking_automation.py:92–240` — nested workspace→team→developer
  loops emitting one event per developer

**Right pattern already exists — copy it:**
- `temporal/activities/tracker_enrich.py:187` groups by `(project, developer)`, one LLM call per group
- `temporal/dispatch.py:62–106` defines heartbeating batch activities
  (`batch_score_leads`, `personalize_outreach_batch`)

**Action (email first):**
```python
# before: 50 workflows
for r in recipients:
    await dispatch("send_campaign_email", SendCampaignEmailInput(recipient_id=r.id), ...)

# after: 1 workflow, loop inside the activity (already has retry/heartbeat config)
await dispatch("send_campaign_batch",
    SendCampaignBatchInput(campaign_id=campaign_id, recipient_ids=[r.id for r in recipients]),
    task_queue=TaskQueue.EMAIL,
)
```

**Trade-off:** a batch activity retries as a unit — make the inner loop **idempotent
per-recipient** (track sent state, skip already-sent on retry) so a retry doesn't re-send.
Keep batch sizes bounded; heartbeat inside long loops.

---

## Suggested first step

Wire up #1 (orjson) and a per-request query-count middleware, then profile to rank the
N+1 endpoints (#2) by actual query count before spending time on #2–#5.
