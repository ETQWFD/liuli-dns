# 05 · API 摘要

> 基础路径：`/api/v1`（管理后台除外，见第 6 节）。生产必须 HTTPS。
> 完整 OpenAPI 在开发模式 `GET /openapi.json`；生产默认关闭文档。本文只列稳定契约，避免客户端依赖内部实现。

## 1. 通用约定

### 响应

成功：

```json
{"ok": true, "data": {...}, "request_id": "..."}
```

失败：

```json
{"ok": false, "error": {"code": "DOMAIN_VERIFY_FAILED", "message": "...", "details": {...}}, "request_id": "..."}
```

- 每个响应带 `X-Request-ID`；错误体也带 `request_id`。
- 不返回堆栈、SQL、路径、密钥、私钥；不泄露其他用户资源是否存在（越权统一 404）。
- 写操作事务提交/回滚；批量记录需要幂等键。

### 鉴权

```http
Authorization: Bearer <access_token>
```

- access token 15 分钟；refresh 30 天并轮换，旧 refresh 重用会撤销该用户全部会话。
- 登录/注册/找回密码需要先取算术验证码；客户端在请求头带 `X-Session-Id`，且与验证码签发时一致。
- 未实名调用域名创建/管理接口返回 `403 REALNAME_REQUIRED`。

### 幂等

批量应用记录必须带：

```http
X-Idempotency-Key: <UUIDv4>
```

相同用户 + 端点 + key + 相同请求体 → 返回首次结果；请求体不同 → `409 IDEMPOTENCY_CONFLICT`。

## 2. 元数据与健康

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/meta/version` | 无 | 名称、版本、环境 |
| GET | `/meta/public` | 无 | 平台域名、NS、实名邮箱、能力边界（`acme_auto=false`） |
| GET | `/healthz` | 无 | API + DB 健康；返回 `status/db` |

## 3. 账号

| 方法 | 路径 | 鉴权 | 主要字段 |
|---|---|---|---|
| POST | `/auth/captcha` | 无 | 返回 `captcha_id`、`question`、`expires_in`；绑定 `X-Session-Id` |
| POST | `/auth/register` | 无 | `email,password,captcha_id,captcha_answer,locale`；密码 ≥10 且含字母+数字 |
| POST | `/auth/verify-email` | 无 | `code`（一次性邮箱码） |
| POST | `/auth/login` | 无 | `email,password,captcha_id,captcha_answer`；返回 access/refresh/user |
| POST | `/auth/refresh` | refresh | `refresh_token`；轮换 |
| POST | `/auth/logout` | 无（带 refresh） | `refresh_token`；撤销 |
| GET | `/auth/me` | Bearer | `id,user_no,email,email_verified,realname_status,...` |
| POST | `/auth/password/forgot` | 无 | `{"email":...}`；统一文案，防枚举 |
| POST | `/auth/password/reset` | 无 | `code,password`；重置后撤销会话 |

登录限流：同 IP 20/min，同账号 5/min；连续失败 10 次锁定 15 分钟；`AUTH_LOCKED` 429。

## 4. 实名

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| POST | `/realname/submissions` | Bearer | `doc_type`（`id_card`/`passport`）、`doc_number`；只存 HMAC+尾号，进入 pending |
| GET | `/realname/status` | Bearer | pending/approved/rejected/active、审核时间、原因、收件邮箱与步骤 |
| POST | `/realname/activate` | Bearer（邮箱已验证） | `code`；一次性；失败限次/锁定；成功后终身有效 |

激活码状态：`unused → used` 或 `revoked`；成功后重复使用 `409 CODE_USED`；无效/不匹配 `400 CODE_INVALID`；锁定 `429 CODE_LOCKED`。管理员可重置失败次数/吊销。

## 5. 域名、解析、证书、工具

### 域名

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/domains` | Bearer+邮箱验证 | 返回 `items[]`（fqdn/status/zone_version/verification） |
| POST | `/domains` | Bearer+实名 | `{"fqdn":"example.com","ns_mode":"delegated"}`；返回 NS/TXT 指引 |
| GET | `/domains/{id}` | Bearer+邮箱验证 | 详情 |
| DELETE | `/domains/{id}` | Bearer+实名 | 删除域名与关联记录/证书密文，写审计 |
| POST | `/domains/{id}/verify` | Bearer+实名 | 校验 NS 或 TXT；成功 active |
| POST | `/domains/{id}/reconcile` | Bearer+实名 | 以 DB 重建 zone 快照 |
| GET | `/domains/{id}/revisions` | Bearer+邮箱验证 | `items[]` 版本历史 |

验证指引字段：`verification.nameservers`、`verification.txt_name=_liuli-verify.<fqdn>`、`verification.txt_value`。

### 解析记录

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/domains/{id}/records` | Bearer+邮箱验证 | 返回 `items[]` 与 `version`（注意不是 `records`） |
| POST | `/domains/{id}/records` | Bearer+实名 | 单条 `{name,type,ttl,value,priority?}` |
| PATCH | `/domains/{id}/records/{rid}` | Bearer+实名 | 修改单条 |
| DELETE | `/domains/{id}/records/{rid}` | Bearer+实名 | 删除单条 |
| POST | `/domains/{id}/records/batch` | Bearer+实名 | `{records:[...],mode:"merge|replace",reason}`；必带幂等键 |
| POST | `/domains/{id}/records/rollback/{version}` | Bearer+实名 | 回滚到历史版本 |

支持类型：A/AAAA/CNAME/TXT/MX/NS/SRV/CAA。名称用相对名（`@`、`www`、`*`）。CNAME 冲突、apex CNAME、非法 IP/优先级会被拒绝。

示例：

```bash
curl -X POST https://api.example.com/api/v1/domains/12/records/batch \
  -H "Authorization: Bearer $ACCESS" \
  -H "Content-Type: application/json" \
  -H "X-Idempotency-Key: 6f1c2d0e-...." \
  -d '{"records":[{"name":"@","type":"A","ttl":300,"value":"203.0.113.10"}],"mode":"replace","reason":"web"}'
```

### 证书

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/domains/{id}/certificates` | Bearer+邮箱验证 | `items[]` 元数据；不含私钥 |
| POST | `/domains/{id}/certificates` | Bearer+实名 | multipart：`cert`、`key` 必填，`chain` 可选，`password` 可选（加密私钥口令，不落库） |
| POST | `/domains/{id}/certificates/{cid}/activate` | Bearer+实名 | 启用/替换 |
| DELETE | `/domains/{id}/certificates/{cid}` | Bearer+实名 | 删除密文与元数据 |
| POST | `/domains/{id}/certificates/acme/order` | Bearer+实名 | 当前返回 `501 CERT_NOT_CONFIGURED` + 手动 DNS-01 指引 |
| GET | `/certificates/expiring?days=45` | Bearer+邮箱验证 | 到期清单 |
| GET | `/domains/agent/config` | Bearer+实名活化 | 只返回该用户自己的 Tunnel token、代理端口、域名映射；绝不下发 Cloudflare API Token |
| POST | `/domains/agent/heartbeat` | Bearer+实名活化 | 桌面 Go agent 上报 running/连接数/域名数/版本/错误；控制面据此显示真实状态 |

上传示例：

```bash
curl -X POST https://api.example.com/api/v1/domains/12/certificates \
  -H "Authorization: Bearer $ACCESS" \
  -F "cert=@fullchain.pem" -F "key=@privkey.pem" -F "chain=@chain.pem"
```

响应仅包含 `common_name/sans/serial/fingerprint/not_before/not_after/status/source/days_left`；**任何响应都不含私钥**。

### 工具

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/tools/dns-check?name=example.com&type=A` | Bearer+邮箱验证 | 返回 answers/count；类型白名单 |
| POST | `/tools/port-check` | Bearer+邮箱验证 | `{"domain_id":12,"port":443}`；只查自己域名且仅公网单播地址，防 SSRF |
| POST | `/tools/cert-inspect` | Bearer+邮箱验证 | multipart `cert`；返回证书元数据 |

## 6. 管理后台（HTML，非 JSON）

- `/admin`：登录页；强密码。
- `/admin/login`：POST 密码；成功后进入 `/admin/2fa`。
- `/admin/2fa`：POST TOTP；失败限次；会话 Cookie。
- `/admin/dashboard`、`/admin/audit`、`/admin/codes`。
- `POST /admin/realname/{sub_id}/review`：通过/驳回。
- `GET /admin/users?q=&status=`：按邮箱或用户编号搜索用户，显示未使用激活码和待审记录。
- `POST /admin/users/{user_id}/approve-offline`：管理员核对审核邮箱中的身份证正反面和编号后，手工标记审核通过；该接口绝不自动实名。
- `POST /admin/codes`：按 `user_no` 生成激活码（同一用户已有未使用码时拒绝重复生成；明文只显示一次）。
- `POST /admin/codes/{id}/revoke`、`/reset-attempts`。

后台操作写审计；生产建议额外做 IP 白名单与独立域名。后台不返回用户私钥。

## 7. 错误码

| 类别 | 代码 |
|---|---|
| 通用 | `VALIDATION`(422), `NOT_FOUND`(404), `CONFLICT`(409), `FORBIDDEN`(403), `INTERNAL`(500) |
| 认证 | `AUTH_REQUIRED`, `AUTH_INVALID`, `AUTH_EMAIL_UNVERIFIED`, `AUTH_LOCKED`(429) |
| 人机验证 | `CAPTCHA_REQUIRED`, `CAPTCHA_INVALID` |
| 实名 | `REALNAME_REQUIRED`(403), `REALNAME_INVALID_STATE`, `CODE_INVALID`, `CODE_USED`, `CODE_REVOKED`, `CODE_LOCKED`(429) |
| 域名 | `DOMAIN_INVALID`, `DOMAIN_EXISTS`, `DOMAIN_NOT_ACTIVE`, `DOMAIN_LIMIT`, `DOMAIN_VERIFY_FAILED` |
| 记录 | `RECORD_INVALID`, `RECORD_CONFLICT` |
| 证书 | `CERT_INVALID`, `CERT_KEY_MISMATCH`, `CERT_DOMAIN_MISMATCH`, `CERT_EXPIRED`, `CERT_NOT_CONFIGURED` |
| 幂等/限流 | `IDEMPOTENCY_CONFLICT`, `RATE_LIMITED`(429 + `Retry-After`) |

## 8. 客户端约定

- 不硬编码任何 token/secret/私钥；API 根地址由用户设置，生产只允许 HTTPS。
- 登录后 access token 仅内存；refresh token 交给 keyring（失败则仅内存）。
- 批量操作生成新的 UUID 幂等键；网络重试沿用同一 key，避免重复写入。
- access 过期自动 refresh；refresh 失败清会话并要求重新登录。
- 错误只展示脱敏 message，不展示内部 details 中的敏感内容；崩溃日志本地脱敏后可复制。

## 9. 边界

- API 的响应不构成公网可达承诺；DNS 委派、端口、注册商限制由用户侧决定。
- 限流/验证缓解滥用，不承诺防住 DDoS/CC。
- `ACME` 自动签发当前未启用；手动 DNS-01 后上传 PEM 是支持路径。
- 生产 OpenAPI 文档默认关闭；需要对接时在预发环境导出并审阅。
