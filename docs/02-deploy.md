# 02 · 部署与运维

> 目标：把 API、权威 DNS、PostgreSQL 跑在一台有公网 IP 的 Linux 服务器上，并让用户把自有域名的 NS 委派到本平台。
>
> 重要：本平台**不做域名注册商**。服务器只能托管用户已经拥有的域名；平台自身域名也需先在注册商处注册并配置好引导 DNS。

## 1. 前置条件

| 项目 | 要求 |
|---|---|
| 服务器 | Ubuntu 24.04 / Debian 12，2 vCPU / 2 GB 起，公网 IPv4（建议同时有 IPv6） |
| 域名 | 例如 `liuli.example`，已在任意注册商注册并可管理 DNS |
| NS 主机名 | `ns1.liuli.example`、`ns2.liuli.example`（可换成自己的域名） |
| 端口 | TCP 80/443（API/证书）、UDP+TCP 53（权威 DNS）、22（运维） |
| 软件 | Python 3.12、PostgreSQL 16、nginx、certbot；或 Docker 24+ / Compose v2 |
| 邮箱 | 可发信的 SMTP 账号；实名材料收件箱（如 `realname@liuli.example`） |

公网 DNS 的引导顺序很关键：

1. 在注册商处为 `ns1.liuli.example`、`ns2.liuli.example` 建 A/AAAA 记录，指向本机公网 IP。
2. 如果 NS 主机名和平台域名同属一个 TLD 且注册商要求 glue，提交 glue 记录（名称服务器注册）。
3. 再把 `liuli.example` 的 NS 指向 `ns1/ns2.liuli.example`。
4. 用户的域名在各自注册商处把 NS 改为 `ns1/ns2.liuli.example`；平台 DNS 只应答已添加并验证的 zone，不做递归。
5. 平台 API 域名（如 `api.liuli.example`）必须能通过公网 DNS 解析；不要让平台 DNS 自己托管平台域，平台 DNS 会拒绝平台自身 zone。

## 2. 裸机部署（systemd）

### 2.1 系统与用户

```bash
sudo apt update && sudo apt install -y python3.12 python3.12-venv postgresql nginx certbot python3-certbot-nginx
sudo useradd --system --create-home --shell /usr/sbin/nologin liuli
sudo mkdir -p /opt/liuli-dns /etc/liuli /var/lib/liuli /var/log/liuli
sudo chown -R liuli:liuli /opt/liuli-dns /var/lib/liuli /var/log/liuli
```

把代码放到 `/opt/liuli-dns`（私有仓库），安装后端依赖：

```bash
sudo -u liuli python3.12 -m venv /opt/liuli-dns/.venv
sudo -u liuli /opt/liuli-dns/.venv/bin/pip install -U pip
sudo -u liuli /opt/liuli-dns/.venv/bin/pip install -r /opt/liuli-dns/backend/requirements.txt
```

### 2.2 PostgreSQL

```bash
sudo -u postgres psql <<'SQL'
CREATE USER liuli WITH PASSWORD 'REPLACE_WITH_LONG_RANDOM_PASSWORD';
CREATE DATABASE liuli OWNER liuli;
SQL
```

数据库表由应用启动时 `init_db()` 创建（当前 MVP 无 Alembic 迁移）。生产升级前先备份；修改表结构时应先在预发环境验证。

### 2.3 环境变量（只放服务器）

```bash
sudo install -m 640 -o root -g liuli /dev/null /etc/liuli/liuli.env
sudo tee /etc/liuli/liuli.env >/dev/null <<'EOF'
LIULI_APP_ENV=prod
LIULI_DATABASE_URL=postgresql+psycopg://liuli:REPLACE_DB_PASSWORD@127.0.0.1:5432/liuli
LIULI_SECRET_KEY=REPLACE
LIULI_CERT_MASTER_KEY=REPLACE
LIULI_CODE_PEPPER=REPLACE
LIULI_DOC_PEPPER=REPLACE
LIULI_PLATFORM_DOMAIN=liuli.example
LIULI_NS_HOSTNAMES=ns1.liuli.example,ns2.liuli.example
LIULI_PUBLIC_BASE_URL=https://api.liuli.example
LIULI_DNS_HOST=0.0.0.0
LIULI_DNS_PORT=53
LIULI_DNS_RESOLVERS=8.8.8.8,1.1.1.1
LIULI_SMTP_HOST=smtp.example.com
LIULI_SMTP_PORT=587
LIULI_SMTP_USER=no-reply@liuli.example
LIULI_SMTP_PASSWORD=REPLACE
LIULI_SMTP_FROM=no-reply@liuli.example
LIULI_SMTP_STARTTLS=true
LIULI_REALNAME_INBOX=realname@liuli.example
LIULI_TRUST_PROXY_HEADERS=true
EOF
```

生成密钥（不要把输出提交到仓库）：

```bash
python3 -c 'import secrets;print(secrets.token_urlsafe(48))'                 # SECRET_KEY
python3 -c 'import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())'  # CERT_MASTER_KEY（必须 32 字节）
python3 -c 'import secrets;print(secrets.token_urlsafe(32))'                 # CODE_PEPPER / DOC_PEPPER
```

`LIULI_CERT_MASTER_KEY` 丢失或更换会导致既有证书私钥无法解密；必须单独备份到密钥管理服务/离线保险箱，不能只存数据库备份中。

### 2.4 后台管理员（密码 + TOTP）

在服务器上生成，不把输出发到聊天/仓库：

```bash
cd /opt/liuli-dns/backend
sudo -u liuli ../.venv/bin/python -m app.cli init-admin --email admin@liuli.example
# 按提示输入强密码（≥14 位，大小写/数字/符号至少三类）
# 把输出的 LIULI_ADMIN_PASSWORD_HASH / LIULI_ADMIN_TOTP_SECRET 写入 /etc/liuli/liuli.env
```

首次登录 `/admin` 需要密码 + TOTP；TOTP secret 只放密码管理器/硬件令牌，不写代码。

### 2.5 systemd

```bash
sudo cp deploy/systemd/liuli-api.service /etc/systemd/system/
sudo cp deploy/systemd/liuli-dns.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now liuli-api liuli-dns
sudo systemctl status liuli-api liuli-dns
```

- API 只监听 `127.0.0.1:8000`，由 nginx 终止 TLS。
- DNS 监听 `0.0.0.0:53`，unit 已授予 `CAP_NET_BIND_SERVICE`；不要把 DNS 放进反向代理。
- 若系统启用了 `systemd-resolved` 占用 53，需停用它或改用独立 IP/端口；生产建议 DNS 独立公网 IP。

### 2.6 nginx 与 TLS

```bash
sudo cp deploy/nginx.example.conf /etc/nginx/sites-available/liuli-api.conf
sudo ln -s /etc/nginx/sites-available/liuli-api.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d api.liuli.example
```

把 `api.liuli.example` 的 A/AAAA 记录放在注册商/公共 DNS，不要指向本平台权威 DNS 的待验证 zone。`LIULI_TRUST_PROXY_HEADERS=true` 只在 API 确实位于可信反向代理之后时启用；否则客户端可伪造 `X-Forwarded-For` 绕过 IP 限流。

### 2.7 防火墙

```bash
sudo ufw allow 22/tcp
sudo ufw allow 80,443/tcp
sudo ufw allow 53/tcp
sudo ufw allow 53/udp
sudo ufw enable
```

只开放必要端口；数据库 5432 不对外。云厂商安全组也要放行 53 UDP/TCP。

## 3. Docker Compose 部署

```bash
cp backend/.env.example .env       # 在仓库根目录；不要提交
# 填写 LIULI_*，并额外设置 POSTGRES_PASSWORD
docker compose up -d --build
docker compose logs -f api dns
```

- `docker-compose.yml` 使用根目录 `.env`；PostgreSQL 数据在 `pgdata` volume。
- API 映射 `127.0.0.1:8000`，请在前面放 nginx/云负载均衡并终止 TLS。
- DNS 映射宿主机 `53/udp`、`53/tcp` 到容器 `5353`；容器以非 root 运行。
- 升级前 `docker compose exec db pg_dump -U liuli liuli > backup.sql`，并备份 `CERT_MASTER_KEY`。

## 4. 验证清单

```bash
# API 健康
curl -fsS https://api.liuli.example/healthz

# 权威 DNS（在外部网络执行）
dig @ns1.liuli.example demo.example A
dig @ns1.liuli.example demo.example AAAA
dig @ns1.liuli.example blog.demo.example CNAME
dig @ns1.liuli.example not-hosted.example A     # 期望 REFUSED

# 管理后台
curl -I https://api.liuli.example/admin          # 应 200/302，需密码+TOTP
```

平台 DNS 实测（开发端口 5353）已覆盖：UDP/TCP A 记录、`www` A、CNAME、非托管 zone `REFUSED`、`ANY` 拒绝。生产 53 端口需在云安全组和主机防火墙同时放行。

用户验收链路：

1. 注册 → 邮箱验证 → 登录。
2. 提交实名材料到 `LIULI_REALNAME_INBOX`，后台审核 → 生成激活码 → 用户激活。
3. 添加已注册一级域名 → 按页面提示改 NS（或加 TXT）→ 点验证。
4. 添加 A/AAAA/CNAME/TXT/MX 记录 → 保存（批量需幂等键）。
5. 上传 PEM 证书 + 私钥（服务端校验并加密）→ 启用。
6. 将记录指向 GitHub Pages/自有服务器 → 浏览器 HTTPS 访问。

## 5. 备份、恢复与密钥

```bash
# 每日数据库备份
docker compose exec -T db pg_dump -U liuli liuli | gzip > /var/backups/liuli-$(date +%F).sql.gz
# 裸机
sudo -u postgres pg_dump liuli | gzip > /var/backups/liuli-$(date +%F).sql.gz
```

必须同时备份：

- PostgreSQL 数据库（用户、实名状态、域名、记录、证书密文、审计）。
- `LIULI_CERT_MASTER_KEY`（单独离线保存；不要和数据库放在同一台机器）。
- `/etc/liuli/liuli.env`（加密保管）。
- 审计日志与发布版本号；代码签名私钥不在服务器备份范围内。

恢复：新建空库 → `gunzip -c backup.sql.gz | psql` → 恢复同一 `CERT_MASTER_KEY` → 启动 API/DNS。**更换主密钥后旧证书密文不可解密**，需要用户重新上传私钥。

## 6. 运维任务

- `maintenance_loop()` 每 15 分钟：证书到期提醒（30/14/7/3/1 天）、过期证书状态、会话/令牌清理、zone 对账。也可手动 `python -m app.cli maintenance`。
- 日志为 JSON 行、带 request-id；检查 `/var/log/liuli` 或 `docker compose logs`。日志已脱敏，不应出现密码/令牌/私钥/完整证件号。
- 监控最少覆盖：`/healthz`、53 UDP/TCP 应答、磁盘/数据库连接、429 比例、证书到期、后台登录失败。
- 修改限流阈值通过 `LIULI_*_PER_MINUTE` 环境变量；多实例共享限流需配置 Redis 并配合网关，内存限流只适合单实例。
- 证书到期前由用户上传新 PEM；当前 ACME 自动签发未启用（API 返回 501 与手动 DNS-01 步骤）。
- 服务中断/攻击处置：临时限流、暂停问题 zone、吊销证书、保留审计并通知用户；不要删除证据。

## 7. 边界

- 不保证公网绝对可达；注册商 NS 限制、云安全组、ISP 封锁、端口不可达、域名到期都会导致失败。
- 限流和算术验证只缓解滥用，不承诺防住 DDoS/CC；生产建议前置云清洗/WAF。
- 当前 MVP 无自动数据库迁移、无多活、无跨区容灾；重要业务请先做压测、备份演练和恢复演练。
- 平台实名审核是平台人工审核，不是官方权威核验；不存证件原图。
