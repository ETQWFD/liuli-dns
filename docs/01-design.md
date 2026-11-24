# 琉璃域名 LiuliDNS — MVP 设计与实现说明书

> 版本：v0.1.0（MVP）
> 定位：面向自有已注册域名的 **权威 DNS 托管 + 证书管理 + 桌面控制台**。
> 不含域名注册商职能；不承诺公网绝对可达；平台审核不等于官方权威核验。

---

## 0. MVP 结论先行

| 维度 | MVP 做 | 明确不做 |
|---|---|---|
| 账号 | 邮箱注册/登录、Argon2id、邮箱验证、登录限流、算术人机验证 | 短信/OAuth/第三方身份源 |
| 实名 | 材料发指定邮箱人工审核；后台按用户编号生成一次性激活码；HMAC 去重、单次使用、终身有效 | 对接公安/官方核验接口；留存证件原图 |
| 域名 | 添加用户**已在注册商注册**的一级域名；NS 委派到本平台权威 DNS；分配二级域名 | 代注册一级域名、抢注、域名交易 |
| 解析 | A/AAAA/CNAME/TXT/MX/NS/SOA/CAA/SRV；批量事务 + 版本快照 + 回滚 + 对账 | 递归解析、公共 DoH/DoT 网关（MVP 不含） |
| 证书 | 上传/替换 PEM（私钥 AES-256-GCM 加密入库）、链校验、到期提醒；手动 DNS-01 后上传 | 分发私钥、代办 CA 审核 |
| 客户端 | PySide6 + QML 玻璃界面、原生模式、三语、引导可跳过、崩溃脱敏日志 | 防杀进程、对抗用户控制、静默提权 |
| 服务端 | FastAPI + SQLAlchemy + 自建 dnslib 权威 DNS + 管理后台（密码 + TOTP + 审计） | 多租户计费、CDN、WAF 商业化 |
| 打包 | venv + PyInstaller/Nuitka + NSIS + signtool 签名脚本 | 在仓库保存代码签名私钥 |

**真实可用路径**：用户把域名 NS 指向本平台 DNS（需公网 IP + 53 端口可达）→ 平台真实应答解析 → 用户手动 DNS-01 签发后上传证书 → 指向 GitHub Pages/自有服务器 → 正式访问。全程不依赖任何域名注册 API。

---

## 1. 项目结构

```
liuli-dns/
├── README.md                     # 快速开始 / 架构 / 边界
├── README.public.md              # 公开客户端仓库的 README
├── LICENSE                       # EULA：数据、实名、私钥、限流、免责
├── LICENSE-CLIENT                # 客户端 MIT
├── docker-compose.yml            # api + dns + postgres（根目录）
├── deploy/
│   ├── Dockerfile.api
│   ├── Dockerfile.dns
│   ├── nginx.example.conf        # TLS 终止 + 反向代理
│   └── systemd/                  # liuli-api.service / liuli-dns.service
├── docs/
│   ├── 01-design.md              # 本文
│   ├── 02-deploy.md              # 部署与运维
│   ├── 03-packaging-signing.md   # 打包、NSIS、代码签名
│   ├── 04-security-boundaries.md # 威胁模型与能力边界
│   ├── 05-api.md                 # 可公开的 API 摘要
│   └── screenshots/              # 9 张离屏渲染截图
├── backend/                      # 私有仓库内容
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py               # FastAPI 装配、中间件、异常处理
│   │   ├── config.py             # 环境变量配置（无生产默认密钥）
│   │   ├── db.py / models.py / schemas.py
│   │   ├── security.py           # Argon2id / JWT / HMAC / AES-GCM / 脱敏
│   │   ├── deps.py               # 鉴权、实名门禁、幂等
│   │   ├── ratelimit.py / captcha.py / audit.py / errors.py
│   │   ├── mailer.py / jobs.py / logging_setup.py / respond.py / cli.py
│   │   ├── routers/
│   │   │   ├── auth.py  realname.py  domains.py  records.py
│   │   │   ├── certificates.py  tools.py  meta.py
│   │   │   └── （后台在 app/admin/，不在此目录）
│   │   ├── services/
│   │   │   ├── dnszone.py        # 校验、zone 快照、版本/回滚
│   │   │   ├── verify.py         # NS / TXT 控制权验证
│   │   │   └── certs.py          # 解析、匹配、加密、到期
│   │   ├── dns/
│   │   │   └── server.py         # 权威 DNS（UDP+TCP，关递归）
│   │   └── admin/
│   │       ├── views.py          # 服务端渲染后台（密码+TOTP+审计）
│   │       └── templates/*.html
│   ├── tests/                    # pytest：54 用例
│   └── scripts/seed_demo.py
├── client/                       # 开源仓库内容（仅前端 + 公开文档/截图）
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py               # QGuiApplication / QML 引擎 / 打包路径
│   │   ├── bridge.py             # QML ⇄ API 桥（线程池/多part）
│   │   ├── ui_theme.py           # 玻璃/原生主题 token
│   │   ├── core/
│   │   │   ├── api.py            # httpx 客户端，无硬编码密钥
│   │   │   ├── tokens.py         # keyring，失败则仅内存
│   │   │   ├── crash.py          # 脱敏崩溃日志 + 剪贴板
│   │   │   ├── netutil.py        # 端口校验、防火墙 UAC
│   │   │   ├── localserver.py    # 127.0.0.1 本地实验服务
│   │   │   ├── i18n.py / settings.py
│   │   │   └── __init__.py
│   │   └── qml/
│   │       ├── Main.qml
│   │       ├── components/ (GlassCard, AnimatedButton, TxField, StatusPill,
│   │       │                 Toast, CrashDialog, FilePicker, DomainPicker,
│   │       │                 MiniField, MiniCombo)
│   │       └── pages/ (Auth, Onboarding, Dashboard, Domains, Records,
│   │                   Certificates, Realname, Tools, SettingsPage)
│   └── resources/ (app-icon.png/.ico, github.svg, noise.png)
├── packaging/
│   ├── entry.py                  # 冻结入口
│   ├── liuli.spec                # PyInstaller onedir
│   ├── build.ps1 / build_nuitka.ps1
│   ├── installer.nsi             # NSIS 安装/卸载
│   ├── sign.ps1                  # signtool（只按证书指纹）
│   └── version_info.txt
└── scripts/
    ├── check_secrets.sh / .ps1   # 密钥/私钥/.env 扫描
    ├── export_public_repo.sh     # 导出前端 + 公开文档
    └── dev_up.sh                 # 本地 API+DNS 启动
```

**仓库拆分**：`client/ + docs/01、04、05 + screenshots + LICENSE + README.public.md` → 开源仓库；`backend/ + deploy/ + docker-compose.yml + packaging/sign.ps1` → 私有仓库。公开导出脚本会拒绝 `backend/deploy/.env/data` 并运行密钥扫描；任何 token/私钥/证件片段命中即失败。

## 2. 系统架构

```
┌──────────────────────── Windows 桌面（PySide6/QML） ────────────────────────┐
│  玻璃 UI / 原生 UI · 三语 · 引导 · 设置                                   │
│  ApiClient(httpx) ── 仅 HTTPS ──► 后端 API（无令牌/私钥硬编码）            │
│  TokenStore: Windows 凭据管理器（keyring），不可用则仅内存                 │
│  CrashHandler: 本地脱敏日志 + 复制到剪贴板                                 │
│  LocalLab: 127.0.0.1:<自定义端口> DNS查询/端口检测/证书解析 + 防火墙放行   │
└───────────────────────────────────┬───────────────────────────────────────┘
                                    │ HTTPS + JWT + 幂等键
┌───────────────────────────────────▼───────────────────────────────────────┐
│ FastAPI (uvicorn, 24h)                                                    │
│  ├ auth / realname / domains / records / certificates / tools              │
│  ├ admin（密码+TOTP+审计，服务端渲染）                                     │
│  ├ 中间件：request-id、统一错误、IP/用户全域限流、审计                     │
│  └ jobs：证书到期提醒、令牌清理、激活码锁定重置、zone 对账                 │
│ 依赖：PostgreSQL（生产）/ SQLite（开发）、Redis（可选限流共享）            │
└───────────────┬───────────────────────────────┬───────────────────────────┘
                │ SQL                            │ 读取 zone 快照(缓存15s)
┌───────────────▼──────────────┐   ┌────────────▼───────────────────────────┐
│ PostgreSQL                   │   │ 权威 DNS 服务 (dnslib, UDP+TCP:53)     │
│ users / sessions / ...       │   │ 关递归 · 关 ANY 放大 · 按源IP限速     │
└──────────────────────────────┘   └────────────┬───────────────────────────┘
                                                │ NS 委派
                                   用户注册商处的自有域名
```

---

## 3. 数据库设计

> 生产 PostgreSQL 15；开发 SQLite。所有时间 UTC；敏感字段只存哈希/密文。

| 表 | 关键字段 | 约束与说明 |
|---|---|---|
| `users` | id, user_no, email, password_hash, role, email_verified_at, is_active, failed_login_count, locked_until, totp_secret_enc, locale, created_at, last_login_at | `user_no` 全局唯一（`U-2026-000123`），用于实名审核检索；`email` 小写唯一；密码 Argon2id 字符串 |
| `sessions` | id, user_id, refresh_hash, ua_hash, ip_hash, expires_at, revoked_at | 只存 refresh 的 SHA-256；登出即撤销 |
| `email_tokens` | id, user_id, kind(verify/reset), token_hash, expires_at, used_at | token 只存哈希；一次性 |
| `realname_submissions` | id, user_id, status(pending/approved/rejected), doc_type, doc_number_hmac, doc_last4, submitted_at, reviewed_at, reviewer_id, reject_reason | **不存原图、不存身份证片段/映射**；`doc_number_hmac` 用服务端 pepper |
| `activation_codes` | id, user_id, user_no, code_hmac, status(unused/used/revoked), attempts, max_attempts=5, locked_until, issued_at, used_at, revoked_at, issued_by | `code_hmac` 全局唯一（HMAC-SHA256）；**不存明文**；生成时查重，冲突重试 |
| `domains` | id, user_id, fqdn, status(pending/active/suspended), ns_mode(delegated/local_lab), verify_token, verified_at, zone_version, created_at | `fqdn` 唯一；创建需实名；每用户每日限额 |
| `dns_records` | id, domain_id, name, type, ttl, value, priority, deleted_at, created_at | `(domain_id,name,type,value,priority)` 唯一；`name` 为相对名（`@`/`www`/`*`） |
| `zone_revisions` | id, domain_id, version, snapshot_json, actor_id, reason, created_at | 每次变更写快照，支持回滚与对账 |
| `certificates` | id, domain_id, source(upload/acme), common_name, sans_json, serial, fingerprint_sha256, not_before, not_after, cert_pem, chain_pem, key_cipher, status, replaced_at | `key_cipher` = AES-256-GCM 密文；**API 永不下发** |
| `audit_logs` | id, actor_id, actor_type(user/admin), action, target, ip_hash, detail_json, created_at | 所有后台操作、证书替换、回滚必写；detail 已脱敏 |
| `idempotency_keys` | id, user_id, endpoint, key, request_hash, response_json, status_code, created_at, expires_at | `(user_id, endpoint, key)` 唯一；请求体不一致 → 409 |
| `notifications` | id, user_id, kind(cert_expiry/realname), payload_json, scheduled_at, sent_at, status | 到期提醒 30/14/7/3/1 天 |

**策略**：证件原图不落库（用户发送至指定邮箱，审核后由邮箱侧删除并留审计记录）；数据库仅保留 HMAC 与尾号 4 位。激活码明文只在生成瞬间返回给管理员一次，页面关闭即不可再取。

---

## 4. API 设计（`/api/v1`）

统一响应：成功 `{"ok":true,"data":...,"request_id":"..."}`；失败 `{"ok":false,"error":{"code","message","details"},"request_id"}`。

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/meta/version` `/healthz` | 无 | 版本与健康检查 |
| POST | `/auth/captcha` | 无 | 返回 `captcha_id` + 算术题（10 分钟、一次性、绑定会话） |
| POST | `/auth/register` | 无 | 邮箱+密码+验证码；发验证邮件 |
| POST | `/auth/verify-email` | 无 | 一次性 token |
| POST | `/auth/login` | 无 | 返回 access(15m)+refresh(30d)；失败计数/锁定/触发验证码 |
| POST | `/auth/refresh` `/auth/logout` | refresh | 轮换 refresh，旧 token 立即失效 |
| GET | `/auth/me` | Bearer | 用户、实名状态、域名数 |
| POST | `/auth/password/forgot` `/auth/password/reset` | 无 | 邮件一次性 token |
| POST | `/realname/submissions` | Bearer | 提交类型/证件 HMAC 输入/尾号，进入 pending；提示邮件提交材料 |
| GET | `/realname/status` | Bearer | pending/approved/rejected/active + 审核时间 |
| POST | `/realname/activate` | Bearer | 一次性激活码；失败限次；成功即终身有效 |
| GET/POST | `/domains` | Bearer + 实名 | 列表/添加（返回 NS 与 TXT 验证指引） |
| GET/DELETE | `/domains/{id}` | Bearer | 详情/删除（先删证书与记录，写审计） |
| POST | `/domains/{id}/verify` | Bearer | 校验 NS 委派或 TXT；成功转 active |
| POST | `/domains/{id}/reconcile` | Bearer | 对账，重建 zone 快照 |
| GET | `/domains/{id}/records` | Bearer | 列表 |
| POST | `/domains/{id}/records` | Bearer | 单条新增 |
| PATCH/DELETE | `/domains/{id}/records/{rid}` | Bearer | 修改/删除 |
| POST | `/domains/{id}/records/batch` | Bearer | **幂等**批量应用；事务 + zone 版本 |
| POST | `/domains/{id}/rollback/{version}` | Bearer | 回滚到历史版本（写审计） |
| GET/POST | `/domains/{id}/certificates` | Bearer | 列表 / multipart 上传 cert+chain+key |
| POST | `/domains/{id}/certificates/{cid}/activate` | Bearer | 替换启用（旧证书保留元数据） |
| DELETE | `/domains/{id}/certificates/{cid}` | Bearer | 删除（含密文） |
| POST | `/domains/{id}/certificates/acme/order` | Bearer | 当前返回 501 + 手动 DNS-01 指引 |
| GET | `/tools/dns-check` `/tools/port-check` | Bearer | 解析检查 / 端口连通检查 |
| GET/POST | `/admin/login` `/admin/2fa` | 无 | 强密码 + TOTP；会话 Cookie |
| GET | `/admin` | admin | 面板：待审实名、用户、证书到期 |
| POST | `/admin/realname/{id}/review` | admin | 通过/驳回 + 审计 |
| POST | `/admin/codes` | admin | 按 `user_no` 生成一次性码（仅本次明文） |
| POST | `/admin/codes/{id}/revoke` `/reset-attempts` | admin | 吊销/重置失败次数 |
| GET | `/admin/audit` | admin | 审计检索 |

鉴权：`Authorization: Bearer <access>`；写操作要求 `X-Idempotency-Key`（UUIDv4）；`X-Session-Id` 绑定人机验证。

---

## 5. UI 页面

| 页面 | 核心内容 | 交互/动画 |
|---|---|---|
| 引导 Onboarding | 3 步：能力边界 → 账号与实名 → 创建须知。显著提示"创建过程中请勿关闭设备或断网，否则可能失败" | 可跳过（写入本地标记）；卡片 420ms 淡入 + 轻微缩放；警告提示常驻 |
| 登录/注册 | 邮箱、密码、算术验证码；忘记密码 | 按钮 hover 磁吸 + 涟漪；错误抖动 |
| 总览 Dashboard | 域名数、解析状态、证书到期卡片、最近操作 | 数字滚动；玻璃卡片悬浮抬升 |
| 域名 Domains | 列表、状态徽标、NS 指引、TXT 验证、二级域名分配 | 新建向导（分步抽屉）；复制 NS 有成功动效 |
| 解析 Records | 表格化记录编辑、批量应用、版本历史、回滚 | 行增删高度过渡；保存进度环 |
| 证书 Certificates | 上传 cert/chain/key、SAN 与到期展示、启用/替换 | 拖拽上传；私钥输入默认掩码，永不回显 |
| 工具箱 Tools | 本地 DNS 查询、端口检测、证书解析、自定义端口与防火墙放行 | 开关滑块；日志流式滚动 |
| 设置 Settings | 原生/玻璃界面切换、简中/EN/繁中、API 地址、GitHub 图标、崩溃日志 | 主题实时过渡 600ms；语言即时生效 |

设计语言：深青-靛蓝渐变底 + 光晕/斜向高光 + 噪点"毛细孔"纹理（运行时生成 512×512 低对比噪点）+ 半透明玻璃卡片（高光描边）；原生模式使用纯色与 1px 边框。动效统一 hover 缩放、按钮水波纹、页面 190ms 淡入与 420ms 引导卡过渡，不承诺绝对不卡顿。

---

## 6. 错误处理

- **统一错误码**：`AUTH_*`, `CAPTCHA_*`, `REALNAME_*`, `CODE_*`, `DOMAIN_*`, `RECORD_*`, `CERT_*`, `RATE_LIMITED`, `IDEMPOTENCY_CONFLICT`, `INTERNAL`。
- **HTTP 映射**：400 参数、401 未登录、403 未实名/无权限、404 不存在、409 冲突、422 校验、429 限流、500 内部。
- **不外泄**：不返回堆栈、SQL、路径、秘钥、邮箱是否存在（注册/找回统一文案）。
- **请求追踪**：`X-Request-ID` 全链路；日志 JSON 行，`redact()` 过滤 Authorization/password/token/private key/邮箱/证件号。
- **事务**：域名创建、批量记录、证书替换均单事务；失败回滚；`zone_revisions` 提供恢复点；`reconcile` 以数据库为准重建快照。
- **客户端**：网络错误分类（超时/离线/证书/5xx）；离线队列仅缓存非敏感 UI 状态；崩溃 → 脱敏日志 + 复制剪贴板 + 重启入口。

---

## 7. 限流与人机验证

| 维度 | 规则 |
|---|---|
| 登录 | 同 IP 20/min；同账号 5/min；连续失败 5 次要求验证码，10 次锁定 15 分钟（指数退避，管理员可解） |
| 注册 | 3 次/小时/IP；同邮箱 24h 内 1 次 |
| 验证码 | 30 次/min/IP；10 分钟过期；一次性；绑定 `X-Session-Id` |
| 实名激活 | 5 次/小时/用户；单码 5 次失败锁定 1 小时，管理员可重置 |
| 域名创建 | 5 个/天/用户；总上限 20 |
| 记录变更 | 30 批/小时/域名；单批 ≤200 条 |
| 证书上传 | 10 次/小时/域名 |
| 全局 | 600/min/IP、5000/min/实例；超限 429 + `Retry-After` |
| DNS | 50 qps/源 IP、2000 qps/实例；关闭递归；ANY 最小应答；响应 >1232B 置 TC |
| 后台 | 5 次/min/IP；TOTP 5 次后锁定 30 分钟 |

实现：内存滑动窗口（单实例默认），`REDIS_URL` 存在时切换 Redis 共享计数；`429` 返回统一错误体，DNS 层超限静默丢弃并计数。**限流只能缓解，不承诺完全防住 DDoS/CC**；生产建议前置云清洗/防火墙。

---

## 8. 权威 DNS 设计

- 仅应答本平台托管 zone；其他查询 `REFUSED`，**不递归**。
- 匹配：最长后缀命中 `domains.fqdn` → 相对名精确匹配 → 支持 `*` 通配（仅最左）。
- 自动合成 `SOA`、`NS`（`ns1/ns2.<平台域>`）、apex `A/AAAA` 可选。
- 记录校验：IPv4/IPv6 合法性、CNAME 目标、MX 优先级 0-65535、TXT ≤255 字符分段、CNAME 与其它类型冲突（apex 禁 CNAME）、重名冲突、单 zone ≤500 条。
- 缓存：zone 快照 15s 或版本号变更即刷新；数据库不可用时返回 `SERVFAIL`，不返回过期错误数据。
- 传输：UDP 53 + TCP 53；开发模式 `--port 5353 --host 127.0.0.1`。

---

## 9. 证书与私钥

1. 上传三件套：`cert.pem`、`chain.pem`（可选）、`key.pem`。
2. 校验：PEM 解析、私钥与证书公钥匹配、密钥强度（RSA≥2048 / ECDSA P-256+）、SAN/CN 覆盖域名、有效期、链顺序（可选信任链校验）。
3. 存储：私钥 `AES-256-GCM(CERT_MASTER_KEY)`，`key_cipher = "v1:<b64(nonce|tag|ct)>"`；密钥只在环境变量/密钥管理服务中；API 永不返回私钥。
4. 替换：新证书校验通过后原子替换，旧证书 `replaced_at` 标记并保留元数据（可配置 30 天后清理密文）。
5. 提醒：每日任务扫描 30/14/7/3/1 天到期，站内 + 邮件。
6. ACME（未启用）：MVP 不内置 CA 客户端；`POST /domains/{id}/certificates/acme/order` 返回 `501 CERT_NOT_CONFIGURED`，并给出手动 DNS-01 + 上传 PEM 的步骤。
7. **代码签名私钥**永不进入仓库/客户端/AI：仅存在于签名机或云 HSM，脚本通过证书指纹调用 `signtool`。

---

## 10. 安全与合规边界（写入 EULA）

- 平台为**技术托管服务**，非域名注册商，不代办注册；一级域名须用户自行取得。
- 实名审核为**平台人工审核**，非官方权威核验；未实名不得创建/管理域名。
- 数据收集：邮箱、登录与操作日志、实名状态、域名与解析记录、证书元数据；不收集与业务无关的个人信息。
- 私钥加密存储、最小权限访问、审计留痕；不随客户端分发任何私钥。
- 公网可达依赖用户自备公网 IP、已注册域名、可达端口与正确 NS 委派；**不承诺绝对可达**。
- 限流与验证只能缓解滥用，**不承诺完全防住 DDoS/CC**；遭遇攻击时可能限流、暂停解析或中断服务。
- 服务可能维护、升级、迁移而短时中断；不承诺 100% 可用与绝对无 Bug。
- 禁止：钓鱼/诈骗/赌博/色情/恶意软件分发、侵权、垃圾邮件、DNS 放大攻击、伪造他人域名、绕过实名。
- 违规处置：暂停解析、吊销证书、封禁账号，保留审计与依法配合。
- SmartScreen 信誉需累积，不承诺永久无提示；坚持同一证书签名并公示发布者名称供核对。

---

## 11. 测试计划

| 层级 | 范围 | 关键用例 | 工具 |
|---|---|---|---|
| 单元 | security/dnszone/certs/ratelimit/captcha | Argon2 校验、HMAC 去重、AES 加解密、记录类型校验、CNAME 冲突、滑动窗口边界、题面与答案一次性 | pytest |
| 集成 | auth/realname/domains/records/certs/admin | 注册→验证→登录→refresh 轮换；实名 pending→approve→激活码→used→重复失败；域名创建→TXT 验证→批量记录→回滚→对账；证书上传→私钥不泄露→替换；429；幂等重放 | pytest + TestClient |
| 组件 | DNS resolver | A/AAAA/CNAME/TXT/MX、最长后缀、通配、REFUSED、ANY 抑制、TC 截断、限速 | dnslib 内存 socket |
| 契约 | OpenAPI | 响应结构与错误码一致；敏感字段不在 schema | schemathesis（可选） |
| 客户端 | QML 加载/桥接/崩溃 | offscreen 启动、页面切换、三语、主题切换、崩溃日志脱敏与剪贴板 | pytest-qt + 截图 |
| 安全 | 秘钥扫描/越权 | 仓库无 secret；A 用户访问 B 域名 404；管理员未 2FA 拒绝；日志无 PII | 自定义脚本 |
| 手工验收 | 真实链路 | NS 委派 → 公网 dig → 上传证书 → 浏览器 HTTPS 访问 | dig/curl/浏览器 |

**验收命令**：`pytest -q`、`scripts/check_secrets.sh`、`python -m app.dns.server --port 5353` + `dig @127.0.0.1 -p 5353`。

---

## 12. 分阶段实施与验收

| 阶段 | 交付 | 验收 |
|---|---|---|
| P0 设计 | 本文 + 结构 + 表 + API + 页面 + 错误/限流/测试 | 评审通过 |
| P1 账号与实名 | auth、captcha、realname、activation、admin 基础、审计 | 注册登录、实名审核、激活码一次性 |
| P2 域名与解析 | domains、records、zone 版本/回滚、权威 DNS、验证 | `dig` 正确应答；批量幂等；回滚成功 |
| P3 证书 | 上传/校验/加密/替换/提醒；ACME 返回 501 + 手动指引 | 私钥不出现在响应/日志/仓库 |
| P4 客户端 | QML 玻璃 UI、三语、引导、设置、工具、崩溃日志 | 安装可用、日志可复制、无硬编码密钥 |
| P5 打包与签名 | PyInstaller/Nuitka + NSIS + sign.ps1 + CI | 安装/卸载/签名验证（需签名机） |
| P6 加固 | Redis 限流、监控、备份、对账任务、文档 | 压测与演练通过 |

**已知边界**：本仓库在 Linux 构建环境完成源码、单测、DNS 实测与 UI 离屏渲染；Windows EXE/NSIS 安装包与 Authenticode 签名需在 Windows 签名机构建（脚本已提供，无私钥）。
