#!/usr/bin/env bash
# Local launcher for the single-user Go tunnel supervisor.
# It never creates DNS records and never starts a public test by itself.
set -euo pipefail
CONFIG="${1:-${LIULI_TUNNEL_CONFIG:-$HOME/.local/share/liuli-dns/server/tunnel/tunnel.json}}"
BIN="${LIULI_TUNNEL_BIN:-$(dirname "$0")/../build-tools/tunnel-dist/liuli-tunnel}"
[ -x "$BIN" ] || { echo "liuli-tunnel binary not found: $BIN" >&2; exit 2; }
[ -f "$CONFIG" ] || { echo "tunnel config not found: $CONFIG" >&2; exit 2; }
exec "$BIN" run --config "$CONFIG"
