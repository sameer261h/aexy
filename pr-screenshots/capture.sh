#!/usr/bin/env bash
# Reproduce every pull-request screenshot. One command, no manual steps.
#
#   ./pr-screenshots/capture.sh
#
# Images land in pr-screenshots/. Re-running overwrites them.
set -euo pipefail
cd "$(dirname "$0")/.."

WS=b077afca-3524-4c65-8a5b-2256d5c12675          # Alex's Worksspace
DEV=c2fca9c2-93f0-49d0-b749-9061ce097b85          # obeytheproletariat@gmail.com

echo "1/4  checking the stack is up"
docker ps --format '{{.Names}}' | grep -q aexy-frontend || { echo "  frontend container is not running — start the stack first"; exit 1; }
curl -sf http://localhost:3000 >/dev/null || { echo "  localhost:3000 is not responding"; exit 1; }

echo "2/4  minting a token for the test account"
TOK=$(docker exec aexy-backend python scripts/generate_test_token.py "$DEV" 2>/dev/null | grep -oE 'eyJ[A-Za-z0-9._-]+' | head -1)
[ -n "$TOK" ] || { echo "  could not mint a token"; exit 1; }

echo "3/4  seeding the data the screens need (idempotent)"
TOK="$TOK" WS="$WS" python3 pr-screenshots/seed.py

SEQ=$(curl -s -H "Authorization: Bearer $TOK" \
  "http://localhost:8000/api/v1/workspaces/$WS/crm/sequences" \
  | python3 -c "import sys,json;print(next((s['id'] for s in json.load(sys.stdin) if 'same day' in s['name']),''))")

echo "4/4  capturing"
cd frontend && TOK="$TOK" WS="$WS" SEQ="$SEQ" node ../pr-screenshots/capture.mjs
echo
echo "done — images are in pr-screenshots/"
