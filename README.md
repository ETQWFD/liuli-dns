# LiuliDNS 琉璃域名

LiuliDNS is a desktop domain console for **Cloudflare Tunnel-only** hosting. It supports platform-owned `*.asnia.cc` subdomains and importing external domains whose NS delegation is moved to Cloudflare. It deliberately does **not** register paid apex domains and does not expose a public IPv4 origin.

Version: **0.2.1**. License: AGPL-3.0 (see `LICENSE`); client artwork and brand assets are covered by `LICENSE-CLIENT`.

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

## 后台地址、用户编号与激活码

### 单机版（只审核本机账号）

客户端只连接本机 API 时，后台地址固定为：

```
http://127.0.0.1:8000/admin
```

第一次启动会在本机数据目录生成管理员凭据（0600）：

- Windows：`%LOCALAPPDATA%\LiuliDNS\server\admin-credentials.txt`
- Linux：`~/.local/share/liuli-dns/server/admin-credentials.txt`

文件里有后台 URL、管理员密码和 TOTP 密钥。这个后台只读取本机数据库，**不能审核其他电脑上的用户**。

### 正式多人版（给其他用户发激活码）

必须把 `deploy/central` 部署到一台有公网入口的服务器，并用 Cloudflare Tunnel 暴露：

- 客户端 API：`https://api.asnia.cc/api/v1`
- 运营后台：`https://admin.asnia.cc/admin`

部署步骤见 `deploy/central/README.md`。没有服务器和 Cloudflare API Token 时，这两个地址不会凭空存在，软件也不会伪造成功。

### 用户侧流程

1. 用户注册并登录，打开“实名信息”。
2. 页面显示“我的用户编号”，用户点击复制；激活码输入框就在编号上方。
3. 用户把身份证正面、反面拍清晰，连同用户编号一起发到 `2416444244@qq.com`；邮件主题写“实名审核 + 编号”。不发编号无法对应账号。
4. 管理员登录后台，在“用户与发码”按编号或邮箱搜索用户，核对邮件后点“标记邮件审核通过”，再点“生成激活码”。
5. 用户把一次性激活码粘贴到实名页上方输入框，点“激活”。服务端真实校验 HMAC、绑定用户、状态、失败次数和是否已用；成功后实名终身有效。
6. 身份证照片只用于本次人工审核，审核后删除；数据库不保留证件原图，只保留审核状态、审核时间和必要的脱敏记录。平台审核不是官方权威核验。

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
