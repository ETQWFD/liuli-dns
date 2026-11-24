# LiuliDNS 琉璃域名

LiuliDNS is a desktop domain console for **Cloudflare Tunnel-only** hosting. It supports platform-owned `*.asnia.cc` subdomains and importing external domains whose NS delegation is moved to Cloudflare. It deliberately does **not** register paid apex domains and does not expose a public IPv4 origin.

Version: **0.2.0**. License: AGPL-3.0 (see `LICENSE`); client artwork and brand assets are covered by `LICENSE-CLIENT`.

## What is implemented

- Python + PySide6/QML client; Python FastAPI local/service API; Go single-binary `liuli-tunnel` supervisor and loopback reverse proxy.
- Real-name gate: new accounts are `unverified`. Creating/importing a domain is blocked until a human operator approves the submission and issues a one-time activation code. Registration never auto-approves real-name status.
- Activation codes: global HMAC-SHA256 deduplication, bound to user id/number, state `unused/used/revoked`, one-time use, failure limits.
- Platform subdomains: `abc.asnia.cc` is created through the Cloudflare API as a proxied CNAME to the user's Tunnel; ingress is configured to the local Go proxy. Failure is reported as “域名暂不可用”, never faked.
- External domains: Cloudflare-assigned NS pair is shown; the domain stays `ns_pending` until public DNS exactly matches both NS records, then CNAME + ingress are created.
- One Tunnel per user, at most five domains across all kinds. The Go proxy tracks in-flight connections, warns at 800 and rejects at 1000 by default.
- Optional free-domain provider adapter (DNSHE) and a safe DigitalPlat placeholder. Provider names are not shown in the client. If NS delegation cannot be written, the API returns “该前缀暂不可用”.
- No NameSilo, no prepaid/credit-card registrar API, no paid apex registration.
- Cloudflare API token, account id and zone id are **server-side environment variables only**. No credential is embedded in the client or repository.
- UI, i18n (zh_CN/en_US/zh_TW), glass/native themes, onboarding, arithmetic CAPTCHA, layered rate limits, redacted logs, clipboard copy, NSIS installer and signing scripts.

## Important operational boundary

Cloudflare has no compliant mainland-China edge. Free Tunnel traffic is commonly scheduled to Hong Kong, Tokyo, Singapore and other nearby locations. Speed and latency are unstable, especially at peak hours, and some mobile browsers may show TLS errors. The free plan has no SLA and Cloudflare may change policy or rate-limit at any time. This is not suitable for large downloads, video streaming or high-concurrency public sites.

`*.asnia.cc` depends on the platform-owned zone. If the platform stops Tunnel service, those subdomains stop resolving/working. IPv4 direct origin is not supported.

Real-name review is a **platform review**, not an official government identity verification. Only status, review time, a证件号 HMAC and masked last four digits are stored; the uploaded image is deleted after review.

## Repository layout

```
backend/            FastAPI service, SQLite/PostgreSQL models, admin console
client/             PySide6 + QML desktop client
tunnel/             Go Tunnel supervisor/reverse proxy + config templates
tools/              check_tunnel_config.py (offline/local validation only)
scripts/            tunnel start scripts
packaging/          Linux/Windows/macOS build scripts, NSIS, signing scripts
docs/               design, deployment, API, security, packaging and Tunnel docs
```

## Local development

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
cd backend
LIULI_APP_ENV=dev ../.venv/bin/python -m pytest -q
```

Run the API locally:

```bash
cd backend
LIULI_LOCAL_MODE=1 LIULI_DATABASE_URL=sqlite:////tmp/liuli.db \
LIULI_SECRET_KEY=dev-secret LIULI_CERT_MASTER_KEY=dev-cert \
LIULI_CODE_PEPPER=dev-code LIULI_DOC_PEPPER=dev-doc \
../.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The desktop client starts `server_entry.py` automatically for a loopback API base. On first standalone start it creates `admin-credentials.txt` (mode 0600) under the user data directory; the operator logs in at `/admin`, reviews the submission and issues the activation code. This is a human review step, not automatic approval.

## Cloudflare Tunnel setup (server side)

Set these only on the server/API host; never in the client:

```bash
export LIULI_PLATFORM_DOMAIN=asnia.cc
export LIULI_PLATFORM_ZONE_ID=<asnia.cc zone id>
export LIULI_CLOUDFLARE_ACCOUNT_ID=<account id>
export LIULI_CLOUDFLARE_API_TOKEN=<scoped API token>
# optional free-domain provider
export LIULI_DNSHE_API_KEY=<dnshe key>
export LIULI_DNSHE_API_SECRET=<dnshe secret>
```

Token permissions: Zone:Read, DNS:Edit for `asnia.cc` (and zones created for external domains), and Account:Cloudflare Tunnel:Edit. The API token is used only by the Python service to create the per-user Tunnel, CNAME and ingress. `cloudflared` receives a per-user Tunnel token through a 0600 file, never through the client API.

The Go process is one per user. Python writes `tunnel.json` and `domains.json`; the Go supervisor starts `cloudflared` and proxies `Host`-matched requests to `127.0.0.1` origins. See `docs/06-cloudflare-tunnel.md`.

## Local configuration validation only

```bash
python3 tools/check_tunnel_config.py --config /path/to/tunnel.json --probe
```

This script only reads files and probes loopback control/proxy ports. **Public Tunnel connectivity and DNS propagation must be verified manually by the developer on their own machine; the AI does not run any real public tunnel test.** See `docs/06-cloudflare-tunnel.md` for the manual checklist.

## Build

Linux `.deb` and Windows EXE/portable ZIP:

```bash
.venv/bin/python packaging/build_release.py
```

macOS must be built on macOS (PyInstaller cannot cross-compile):

```bash
packaging/build_macos.sh
```

The Windows installer payload includes embedded CPython 3.11, PySide6, the local API, `liuli-tunnel.exe` and `cloudflared.exe`. The Linux package includes `liuli-dns-server`, `liuli-tunnel` and `cloudflared`. Code-signing keys are never included in the repository and are supplied by the release operator. See `docs/03-packaging-signing.md`.

## Tests

`backend/tests` contain API tests with a deterministic fake Cloudflare adapter and fake Tunnel manager. They verify the real-name gate, activation state machine, platform/external domain flows, NS-pending rejection, five-domain limit, admin review, redaction and certificate encryption. They do not claim real Cloudflare connectivity. Go tunnel proxy behavior is tested with a local fake `cloudflared`; public Tunnel verification is explicitly out of scope for automation.

## Security notes

- No secrets in git: use environment variables or local 0600 files; scan before publishing.
- The admin console requires password + TOTP and is never a normal user account.
- Certificates: private key encrypted at rest; the API never returns it.
- Logs redact tokens, passwords, email addresses, ID numbers and private keys.
- Real-name images are not committed and are deleted after review; only HMAC + masked tail are stored.
