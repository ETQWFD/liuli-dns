#!/usr/bin/env bash
# Export the public client repository.  Only the desktop client, public docs,
# screenshots and licenses are copied; backend/deploy/env/keys never are.
#
#   scripts/export_public_repo.sh /tmp/liuli-dns-client
#
# The script refuses dangerous output paths and runs a secret scan before
# declaring success.  It does not create or push a Git remote.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-}"
if [ -z "$OUT" ]; then
  echo "usage: $0 <empty-output-directory>" >&2
  exit 2
fi
case "$OUT" in
  /|/home|/home/user|"$ROOT"|.) echo "refusing unsafe output path: $OUT" >&2; exit 2 ;;
esac
if [ -e "$OUT" ] && [ -n "$(ls -A "$OUT" 2>/dev/null)" ]; then
  echo "output directory is not empty: $OUT" >&2
  exit 2
fi
mkdir -p "$OUT"

copy_file() { if [ -e "$1" ]; then cp -a "$1" "$2"; fi; }

mkdir -p "$OUT/docs/screenshots" "$OUT/scripts"
cp -a "$ROOT/client" "$OUT/client"
find "$OUT/client" -type d \( -name __pycache__ -o -name .pytest_cache \) -prune -exec rm -rf {} +
find "$OUT/client" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete

# Public documentation only. Deployment topology and backend source stay private.
copy_file "$ROOT/docs/01-design.md" "$OUT/docs/01-design.md"
copy_file "$ROOT/docs/04-security-boundaries.md" "$OUT/docs/04-security-boundaries.md"
copy_file "$ROOT/docs/05-api.md" "$OUT/docs/05-api.md"
for f in "$ROOT"/docs/screenshots/*.png; do [ -e "$f" ] && cp -a "$f" "$OUT/docs/screenshots/"; done
copy_file "$ROOT/README.public.md" "$OUT/README.md"
copy_file "$ROOT/LICENSE" "$OUT/LICENSE-EULA"
copy_file "$ROOT/LICENSE-CLIENT" "$OUT/LICENSE"
copy_file "$ROOT/scripts/check_secrets.sh" "$OUT/scripts/check_secrets.sh"

# The public tree must not contain server code, deployment secrets or tokens.
for forbidden in backend deploy .env data packaging; do
  if [ -e "$OUT/$forbidden" ]; then
    echo "public export contains forbidden path: $forbidden" >&2
    exit 1
  fi
done

"$OUT/scripts/check_secrets.sh" "$OUT"
echo "Public client repository exported to: $OUT"
echo "Next: git init, review the tree, add a remote and push only after review."
echo "Never add backend/, deploy/, .env, private keys or user data to this repository."
