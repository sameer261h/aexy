#!/usr/bin/env sh
set -eu

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
FRONTEND_URL="${FRONTEND_URL:-http://localhost:3000}"
MAILAGENT_URL="${MAILAGENT_URL:-http://localhost:8001}"

compose() {
  docker compose -f "$COMPOSE_FILE" "$@"
}

check_http() {
  name="$1"
  url="$2"
  if curl -fsS "$url" >/dev/null; then
    printf 'ok - %s (%s)\n' "$name" "$url"
  else
    printf 'not ok - %s (%s)\n' "$name" "$url" >&2
    return 1
  fi
}

check_exec() {
  name="$1"
  service="$2"
  shift 2
  if compose exec -T "$service" "$@" >/dev/null; then
    printf 'ok - %s\n' "$name"
  else
    printf 'not ok - %s\n' "$name" >&2
    return 1
  fi
}

check_exec "postgres accepts connections" postgres pg_isready -U "${POSTGRES_USER:-postgres}"
check_exec "redis responds" redis redis-cli ping
check_http "backend readiness" "$BACKEND_URL/api/v1/ready"
check_http "frontend http" "$FRONTEND_URL/"

if compose ps --services | grep -qx mailagent; then
  check_http "mailagent readiness" "$MAILAGENT_URL/ready"
fi

if compose ps --services | grep -qx temporal-worker; then
  check_exec "temporal worker can reach temporal" temporal-worker python -c "import socket; s=socket.create_connection(('temporal', 7233), 5); s.close()"
fi

printf 'compose smoke checks passed for %s\n' "$COMPOSE_FILE"
