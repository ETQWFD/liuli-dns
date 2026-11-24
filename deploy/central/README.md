# LiuliDNS 中央后台部署（正式多人使用）

## 先说清楚地址

- **单机模式**（默认安装包）：后台只在这台电脑上：
  `http://127.0.0.1:8000/admin`
  它只能审核这台电脑上的账号，不能给其他电脑上的用户发激活码。
- **正式多人模式**：把本目录的中央后端部署到一台有公网入口的服务器，再用 Cloudflare Tunnel 暴露两个域名：
  - 客户端 API：`https://api.asnia.cc/api/v1`
  - 运营后台：`https://admin.asnia.cc/admin`
  这两个地址只有在服务器部署、Tunnel 建立并完成 DNS 路由后才存在。没有服务器和 Cloudflare 凭据时，软件不会伪造一个“可用”的地址。

## 服务器要求

Ubuntu 22.04/24.04、Python 3.12、systemd；域名 `asnia.cc` 已接入 Cloudflare（当前 NS 已是 Cloudflare）。建议 Cloudflare Access 再给 `admin.asnia.cc` 加一层邮箱/OTP 策略。

## 一、启动中央后端

```bash
sudo apt update && sudo apt install -y python3 python3-venv
sudo mkdir -p /opt/liuli-dns
sudo cp -a . /opt/liuli-dns   # 或 git clone 到该目录
cd /opt/liuli-dns
sudo bash deploy/central/install.sh
```

脚本会：

1. 创建 `liuli` 系统用户和 `/var/lib/liuli-dns` 数据目录；
2. 创建虚拟环境并安装 `backend/requirements.txt`；
3. 生成 `deploy/central/central.env`（0600）：
   - 数据库密钥、HMAC pepper、加密密钥
   - 管理员密码、TOTP secret
4. 写入 `/var/lib/liuli-dns/admin-credentials.txt`（0600）；
5. 安装并启动 `liuli-central.service`。

查看管理员凭据：

```bash
sudo cat /var/lib/liuli-dns/admin-credentials.txt
```

此时后台地址是本机：

```
http://127.0.0.1:8000/admin
```

远程访问前不要直接把 8000 端口开放到公网，继续做下面的 Tunnel。

## 二、建立 Cloudflare Tunnel

```bash
cloudflared tunnel login
cloudflared tunnel create liuli-central
cloudflared tunnel route dns liuli-central api.asnia.cc
cloudflared tunnel route dns liuli-central admin.asnia.cc
sudo mkdir -p /etc/cloudflared
sudo cp deploy/central/cloudflared-config.example.yml /etc/cloudflared/config.yml
# 编辑 /etc/cloudflared/config.yml，把 <TUNNEL_ID> 换成 create 输出的 UUID
sudo cloudflared service install
sudo systemctl enable --now cloudflared
```

`/etc/cloudflared/config.yml` 里的两条 ingress 都指向 `http://127.0.0.1:8000`。后台 host 已在服务内部限制：从 `api.asnia.cc` 访问 `/admin` 会返回 404，只有 `admin.asnia.cc` 或本机 loopback 可进入后台。

## 三、填写 Cloudflare API 变量

编辑 `/opt/liuli-dns/deploy/central/central.env`：

```bash
LIULI_CLOUDFLARE_ACCOUNT_ID='你的 Cloudflare Account ID'
LIULI_CLOUDFLARE_API_TOKEN='仅放在服务端的 API Token'
LIULI_PLATFORM_ZONE_ID='asnia.cc 的 Zone ID'
```

Token 只需 Zone DNS 编辑 + Tunnel 管理权限；不要写进客户端、仓库或聊天记录。然后：

```bash
sudo systemctl restart liuli-central
```

- `api.asnia.cc` 是账号/实名/域名控制面。
- 每个用户桌面端仍会在自己的电脑启动 `cloudflared`，用服务端签发的 Tunnel token 把 `*.asnia.cc` 或外部域名反代到本机 upstream。Cloudflare API Token 不会下发到客户端。

## 四、客户端接入

安装客户端后，在“设置 → 服务端地址”填：

```
https://api.asnia.cc/api/v1
```

或构建时在 `client-config.json` 写：

```json
{"api_base": "https://api.asnia.cc/api/v1"}
```

放在 `LiuliDNS.exe` / `liuli-dns` 同目录，或 Linux `/usr/lib/liuli-dns/client-config.json`。客户端使用远程地址时不会启动本机 Python API，而是使用内置 Go tunnel agent 拉取自己的 Tunnel token 和域名映射。

## 五、用户实名与激活码流程

1. 用户在客户端注册并登录。
2. 打开“实名信息”，复制“我的用户编号”。
3. 用户把身份证正面、反面清晰照片发到 `2416444244@qq.com`，邮件主题和正文都写用户编号。没有编号无法对应账号。
4. 管理员登录 `https://admin.asnia.cc/admin`（密码 + TOTP）。
5. 在“用户与发码”搜索用户编号或邮箱；核对邮件后点“标记邮件审核通过”。
6. 点“生成激活码”，页面显示一次性明文和可直接发给用户的话术。
7. 用户回到“实名信息”，在编号上方的输入框粘贴激活码并点“激活”。服务端真实校验 HMAC、绑定用户、状态、失败次数和是否已用；成功后终身有效。
8. 管理员删除邮箱中的身份证照片。平台数据库只保存审核状态、审核时间、证件号 HMAC 和脱敏尾号。

## 六、验证与排错

```bash
curl -fsS http://127.0.0.1:8000/healthz
sudo journalctl -u liuli-central -n 100 --no-pager
sudo systemctl status liuli-central cloudflared --no-pager
```

- 后台打不开：先看 `LIULI_ADMIN_PUBLIC_URL` 是否与浏览器地址一致，再看 systemd 日志。
- 创建 `abc.asnia.cc` 返回 `503 CLOUDFLARE_NOT_CONFIGURED`：说明 Cloudflare 变量没填对；不会假装创建成功。
- 隧道状态一直是“本机隧道代理尚未连接”：客户端还没登录、未实名激活，或客户端缺少 `liuli-tunnel`/`cloudflared`。
- 真实公网 Tunnel 连通性必须由部署者在自己的网络手动验证；自动化构建环境不执行真实公网测试。
