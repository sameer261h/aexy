# Production Resource Limits

`docker-compose.prod.yml` sets conservative CPU and memory limits so one
service cannot consume the whole host. Local dev compose files intentionally do
not mirror these limits; dev workloads need room for hot reload, test runs, and
frontend builds.

## Current starting limits

| Service | Memory | CPU |
|---|---:|---:|
| postgres | 4g | 2.0 |
| backend | 4g | 2.0 |
| temporal-worker | 3g | 2.0 |
| temporal | 2g | 1.0 |
| frontend | 2g | 1.0 |
| mailagent | 1g | 1.0 |
| rustfs | 1g | 1.0 |
| redis | 1g | 0.5 |
| temporal-ui | 512m | 0.5 |
| backup | 512m | 0.5 |

These values are guardrails, not proof of capacity. Revisit them after the
first real traffic baseline.

## What to measure before changing limits

Run this during normal traffic, imports, sync jobs, backup windows, and any
large customer-data operation:

```bash
docker stats
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs --tail=100 backend temporal-worker postgres
```

Track:

- backend p95/p99 latency and worker count saturation
- Temporal workflow backlog and activity retry spikes
- Postgres memory, disk growth, slow queries, and connection count
- Redis memory usage and eviction count
- frontend restart count and response latency
- RustFS disk and memory growth
- backup duration, CPU, and IO impact

Raise limits only when measurements show sustained pressure. Lower limits only
after confirming the service has headroom during peak and background jobs.
