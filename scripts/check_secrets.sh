#!/usr/bin/env bash
# Fail-closed secret scan for the private and public repositories.
# Usage: scripts/check_secrets.sh [repo-root]
set -euo pipefail

ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$ROOT"

TARGETS=()
for t in client backend/app packaging deploy docs scripts README.md LICENSE LICENSE-CLIENT; do
  [ -e "$t" ] && TARGETS+=("$t")
done

EXCLUDES=(
  --exclude-dir=.git --exclude-dir=.venv --exclude-dir=venv
  --exclude-dir=__pycache__ --exclude-dir=.pytest_cache --exclude-dir=node_modules
  --exclude-dir=dist --exclude-dir=build --exclude-dir=data
  --exclude-dir=tests --exclude-dir=screenshots
  --exclude='*.png' --exclude='*.jpg' --exclude='*.jpeg' --exclude='*.ico'
  --exclude='*.pdf' --exclude='*.zip' --exclude='*.so' --exclude='*.dll' --exclude='*.exe'
  --exclude='.env.example' --exclude='check_secrets.sh' --exclude='check_secrets.ps1'
)

PATTERNS=(
  '-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----'
  'AKIA[0-9A-Z]{16}'
  'ghp_[A-Za-z0-9]{36}'
  'github_pat_[A-Za-z0-9_]{20,}'
  'sk-[A-Za-z0-9]{32,}'
  'xox[baprs]-[A-Za-z0-9-]{10,}'
  'LIULI_(SECRET_KEY|CERT_MASTER_KEY|CODE_PEPPER|DOC_PEPPER|ADMIN_PASSWORD_HASH|ADMIN_TOTP_SECRET|SMTP_PASSWORD)=[A-Za-z0-9_+/=-]{40,}'
  '(password|passwd|secret|api_key|access_token|refresh_token)[[:space:]]*[:=][[:space:]]*["'\''][A-Za-z0-9_./+=-]{24,}["'\'']'
  'Authorization:[[:space:]]*Bearer[[:space:]]+[A-Za-z0-9._-]{30,}'
)

echo "[secrets] scanning ${TARGETS[*]}"
HITS=""
for pat in "${PATTERNS[@]}"; do
  OUT="$(grep -RInE --binary-files=without-match "${EXCLUDES[@]}" -- "$pat" "${TARGETS[@]}" || true)"
  if [ -n "$OUT" ]; then
    HITS+="$OUT"$'\n'
  fi
done

ENV_FILES="$(find . -type f \( -name '.env' -o -name '*.pem' -o -name '*.key' -o -name '*.pfx' -o -name '*.p12' \) \
  -not -path './.venv/*' -not -path './.git/*' -not -path './data/*' -not -path './docs/screenshots/*' 2>/dev/null || true)"
if [ -n "$ENV_FILES" ]; then
  HITS+="[files that must never be committed]"$'\n'"$ENV_FILES"$'\n'
fi

if [ -n "${HITS// /}" ] && [ -n "$(printf '%s' "$HITS" | tr -d '[:space:]')" ]; then
  printf '%s\n' "$HITS"
  echo "[secrets] FAILED: possible secret/private material found. Remove it before committing." >&2
  exit 1
fi
echo "[secrets] OK: no obvious token, private key, .env or certificate key file."
