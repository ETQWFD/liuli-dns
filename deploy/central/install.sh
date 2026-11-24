#!/bin/bash
set -euo pipefail
APP_DIR=${APP_DIR:-/opt/liuli-dns}
DATA_DIR=${DATA_DIR:-/var/lib/liuli-dns}
REPO_DIR=$(cd "$(dirname "$0")/../.." && pwd)

if [ "$(id -u)" -ne 0 ]; then
  echo "run as root: sudo bash deploy/central/install.sh" >&2
  exit 1
fi
id -u liuli >/dev/null 2>&1 || useradd --system --home "$DATA_DIR" --shell /usr/sbin/nologin liuli
install -d -m 700 -o liuli -g liuli "$DATA_DIR"

if [ ! -d "$APP_DIR/.git" ] && [ "$REPO_DIR" != "$APP_DIR" ]; then
  mkdir -p "$APP_DIR"
  tar -C "$REPO_DIR" --exclude=.git --exclude=.venv --exclude=build-tools --exclude=release --exclude=data -cf - . | tar -C "$APP_DIR" -xf -
fi
cd "$APP_DIR"
python3 -m venv .venv
.venv/bin/pip install --disable-pip-version-check -r backend/requirements.txt
if [ ! -f deploy/central/central.env ]; then
  .venv/bin/python deploy/central/bootstrap.py \
    --env-file deploy/central/central.env --data-dir "$DATA_DIR" \
    --admin-url "${ADMIN_URL:-https://admin.example.com/admin}"
fi
chown -R liuli:liuli "$DATA_DIR"
chown -R root:root "$APP_DIR"
chmod 600 deploy/central/central.env "$DATA_DIR/admin-credentials.txt"
cp deploy/central/liuli-central.service /etc/systemd/system/liuli-central.service
systemctl daemon-reload
systemctl enable --now liuli-central
systemctl --no-pager status liuli-central || true
echo
echo "Admin credentials: $DATA_DIR/admin-credentials.txt"
echo "Admin URL: see LIULI_ADMIN_PUBLIC_URL in deploy/central/central.env"
echo "Next: set Cloudflare variables, then: systemctl restart liuli-central"
