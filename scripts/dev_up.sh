#!/usr/bin/env bash
# Local development: API on 127.0.0.1:8000 and authoritative DNS on 127.0.0.1:5353.
# Generates ephemeral dev-only secrets; never use this script in production.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="$ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
  python3 -m venv "$ROOT/.venv"
  "$PY" -m pip install --upgrade pip wheel
  "$PY" -m pip install -r backend/requirements.txt -r client/requirements.txt
fi

mkdir -p backend/data
export LIULI_APP_ENV=dev
export LIULI_DATABASE_URL="${LIULI_DATABASE_URL:-sqlite:///$ROOT/backend/data/liuli.db}"
export LIULI_SECRET_KEY="${LIULI_SECRET_KEY:-$("$PY" -c 'import secrets;print(secrets.token_urlsafe(48))')}"
export LIULI_CERT_MASTER_KEY="${LIULI_CERT_MASTER_KEY:-$("$PY" -c 'import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())')}"
export LIULI_CODE_PEPPER="${LIULI_CODE_PEPPER:-$("$PY" -c 'import secrets;print(secrets.token_urlsafe(32))')}"
export LIULI_DOC_PEPPER="${LIULI_DOC_PEPPER:-$("$PY" -c 'import secrets;print(secrets.token_urlsafe(32))')}"
export LIULI_PLATFORM_DOMAIN="${LIULI_PLATFORM_DOMAIN:-liuli.test}"
export LIULI_NS_HOSTNAMES="${LIULI_NS_HOSTNAMES:-ns1.liuli.test,ns2.liuli.test}"
export LIULI_TRUST_PROXY_HEADERS=false

if [ "${1:-}" = "--seed" ]; then
  (cd backend && "$PY" scripts/seed_demo.py)
fi

cleanup() {
  [ -n "${API_PID:-}" ] && kill "$API_PID" 2>/dev/null || true
  [ -n "${DNS_PID:-}" ] && kill "$DNS_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

(cd backend && exec "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port 8000) &
API_PID=$!
(cd backend && exec "$PY" -m app.dns.server --host 127.0.0.1 --port 5353 --refresh 15) &
DNS_PID=$!

echo "API:  http://127.0.0.1:8000/api/v1  (docs: /docs)"
echo "DNS:  127.0.0.1:5353 UDP+TCP"
echo "Demo: cd backend && $PY scripts/seed_demo.py  (demo@liuli.dev by default)"
echo "Client: $PY -m client.app.main --demo  (or set API URL in Settings)"
wait
