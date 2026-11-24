# Cloudflare Tunnel 接入说明

## 架构

```
Internet -> Cloudflare edge -> per-user named Tunnel -> cloudflared
           -> 127.0.0.1:8787 (Go liuli-tunnel reverse proxy)
           -> 127.0.0.1:<user origin>
```

- 一个用户一个 named Tunnel。该用户最多 5 个域名（`*.asnia.cc`、外部导入、免费域名合计）共用该 Tunnel。
- Python 服务负责 Cloudflare API：创建/复用 Tunnel、创建 CNAME、写 ingress、查询并发状态。
- Go `liuli-tunnel` 负责唯一一个 `cloudflared` 子进程、Host 路由、并发软限制和本地 `/health`、`/status`、`/reload` 控制面。
- 客户端永远拿不到 Cloudflare API Token，也拿不到 Tunnel token；Tunnel token 只写入用户数据目录的 0600 文件。

## 必需的服务端环境变量

```bash
LIULI_PLATFORM_DOMAIN=asnia.cc
LIULI_PLATFORM_ZONE_ID=<asnia.cc 的 Zone ID>
LIULI_CLOUDFLARE_ACCOUNT_ID=<Cloudflare Account ID>
LIULI_CLOUDFLARE_API_TOKEN=<最小权限 API Token>
LIULI_TUNNEL_PROXY_PORT=8787
LIULI_TUNNEL_CONTROL_PORT=8788
LIULI_TUNNEL_WARN_CONNECTIONS=800
LIULI_TUNNEL_MAX_CONNECTIONS=1000
```

`LIULI_CLOUDFLARE_API_TOKEN` 至少需要：

- `Zone:Read`
- `DNS:Edit`（`asnia.cc` 及外部域名创建的 Zone）
- `Account:Cloudflare Tunnel:Edit`

Token 只放服务端环境变量或 0600 env 文件，不写入客户端、仓库、日志或截图。

## 平台二级域名 `abc.asnia.cc`

1. 用户完成实名审核并输入一次性激活码。
2. 服务端调用 Cloudflare API，在 `asnia.cc` Zone 创建/更新 `abc` 的 proxied CNAME，目标为 `<tunnel_id>.cfargotunnel.com`。
3. 服务端把该 hostname 写入该用户 Tunnel 的 ingress，service 固定为 `http://127.0.0.1:8787`，最后一条为 `http_status:404`。
4. 服务端确认 Go supervisor 的 `/status` 为 `running=true` 后才把域名置为 `active`。
5. 任一步失败：回滚刚创建的 CNAME（如已创建），返回 `503` / “域名暂不可用”，不得置 active。

`asnia.cc` 已经在 Cloudflare，不需要再改 NS，但必须提供正确的 Zone ID 和具备 DNS 编辑权限的 Token；否则平台域名创建会明确失败。

## 外部域名

1. `POST /domains/external` 在 Cloudflare 创建/查找该域名的 Zone，保存 Cloudflare 返回的两个 NS。
2. 状态为 `ns_pending`，界面显示“等待 NS 切换”，不创建 CNAME，不配置 ingress。
3. 用户自行到注册商把 NS 改成这两个地址。
4. 用户点击“重新检测”；`check_ns_switched()` 查询公共 DNS，要求返回的 NS 集合**精确等于** Cloudflare 分配的两个地址（不是包含关系）。
5. 验证通过后才创建 CNAME、写 ingress、启动 Tunnel，置为 `active`。

NS 未生效时 API 返回 `409 DOMAIN_NS_PENDING`，不会假装成功。

## 免费域名（可选）

- 优先 DNSHE：`LIULI_DNSHE_API_KEY`、`LIULI_DNSHE_API_SECRET`，API base 默认 `https://api005.dnshe.com/index.php`。
- 备选 DigitalPlat 仅做明确失败占位；没有安全的公开 NS 委派写接口时不伪造成功。
- 平台名称只在服务端配置中出现，客户端只显示“免费域名”“该前缀暂不可用”。

## 并发限制

Cloudflare 免费版单 Tunnel 的并发连接存在软限制，具体数值会随策略变化。软件采用保守默认：

- `active >= 800`：在响应中加 `X-Liuli-Tunnel-Warning`，状态接口返回 `warning=true`，界面提示“连接数较高，新访问可能变慢或失败”。
- `active >= 1000`：返回 `503` 与 `Retry-After: 30`。
- `warning=true` 时后端拒绝创建新域名映射，避免继续放大风险。

这不是 Cloudflare 官方硬限制，也不构成 SLA；阈值可通过环境变量调整。

## 本地配置验证（AI 不执行公网测试）

```bash
python3 tools/check_tunnel_config.py \
  --config ~/.local/share/liuli-dns/server/tunnel/tunnel.json \
  --domain abc.asnia.cc --probe
```

该脚本只检查本地文件、权限、端口、hostname、upstream 和 `127.0.0.1` 控制面/代理；不会访问 Cloudflare 或公网域名。模板见：

- `tunnel/tunnel.example.json`
- `tunnel/domains.example.json`
- `tunnel/cloudflared.example.yml`
- `scripts/start-tunnel.sh`
- `scripts/start-tunnel.ps1`

### 开发者手动验证清单（必须在本地执行，自动化环境不执行）

- [ ] 在 Cloudflare 账户确认 `asnia.cc` Zone 状态为 Active，记录 Zone ID。
- [ ] API Token 权限最小化，能列出 Zone、编辑 DNS、编辑 Tunnel。
- [ ] 启动本机 API，完成一个已激活实名的测试账号。
- [ ] 调用 `POST /api/v1/domains/platform` 创建测试前缀。
- [ ] 检查 Cloudflare DNS 是否出现 proxied CNAME 到 `<tunnel_id>.cfargotunnel.com`。
- [ ] 检查 Tunnel 配置 ingress 是否包含该 hostname，最后一条是 `http_status:404`。
- [ ] 在本地访问 `http://127.0.0.1:8080` 确认源站正常。
- [ ] 从**另一网络**访问 `https://<prefix>.asnia.cc`，确认返回测试页。
- [ ] 观察 `/domains/tunnel/status` 的 `running`、`active_connections`、`warning`。
- [ ] 停止 `cloudflared` 或断开 Tunnel，确认界面提示“域名暂不可用”，不显示假 active。
- [ ] 外部域名测试：创建 Zone、替换 NS、等待传播、点击检测、确认只有 NS 精确匹配后才 active。

以上公网验证由开发者本人在本地手动完成；AI 只生成配置、脚本和本地校验工具，不执行真实公网隧道测试。
