# Container Image Pinning

Aexy pins external Docker images by digest. Tags such as `postgres:18-alpine`
and `node:20-alpine` stay in the file for readability, but the digest is what
makes rebuilds repeatable:

```Dockerfile
FROM postgres:18-alpine@sha256:...
```

```yaml
image: redis:7-alpine@sha256:...
```

## Why this matters

Mutable tags can change under the same name. A normal `docker pull` can bring
in a new OS layer, compiler package, Postgres patch, Temporal auto-setup
behavior, or object-storage release without a code review. Digest pins turn
those changes into explicit PRs.

## Update process

Refresh digests in a dedicated infra PR:

```bash
docker buildx imagetools inspect postgres:18-alpine
docker buildx imagetools inspect redis:7-alpine
docker buildx imagetools inspect rustfs/rustfs:latest
docker buildx imagetools inspect temporalio/auto-setup:latest
docker buildx imagetools inspect temporalio/ui:latest
docker buildx imagetools inspect python:3.13-slim
docker buildx imagetools inspect node:20-alpine
```

Use the top-level `Digest:` value for the tag. After updating:

```bash
docker compose -f docker-compose.yml config
docker compose -f docker-compose.dev.yml config
docker compose -f docker-compose.prod.yml config
docker compose build postgres backend mailagent frontend
```

For the custom Postgres image, rebuild and smoke-test before deploy:

```bash
docker compose build postgres
docker compose up -d postgres
docker compose exec postgres pg_isready -U postgres
```

Do not combine digest refreshes with product changes. If a digest update
breaks a build or startup path, revert the digest refresh without reverting
application work.
