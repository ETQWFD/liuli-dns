# macOS 构建、签名与公证

PyInstaller 不能在 Linux/Windows 上交叉编译 macOS 应用。必须在 macOS 主机执行：

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
packaging/build_macos.sh
```

脚本会：

1. 用 Go 交叉编译 `darwin/arm64` 与 `darwin/amd64` 的 `liuli-tunnel`，`lipo` 成 universal 二进制。
2. 下载官方 `cloudflared-darwin-{arm64,amd64}.tgz`，合并为 universal `cloudflared`。
3. 用 PyInstaller 构建 `LiuliDNS.app` 和 `liuli-dns-server`。
4. 把两个单文件二进制放进 `Contents/MacOS`。
5. 可选签名与公证，然后生成 `.dmg`。

## 签名与公证

Apple 的 **Developer ID Application** 证书必须由开发者以 Apple Developer Program 账号申请，私钥只能保存在开发者钥匙串/HSM，不能交给 AI，也不能提交到仓库。

```bash
export CODESIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)"
export NOTARY_PROFILE="liuli-notary"   # xcrun notarytool store-credentials 创建
packaging/build_macos.sh
```

没有这两个变量时脚本仍会产出未签名 DMG，但 Gatekeeper 会提示“无法验证开发者”，不适合正式分发。

## Windows Authenticode

使用外部购买的 OV/EV 代码签名证书，通过 `packaging/sign.ps1 -Thumbprint <证书指纹>` 签名 `LiuliDNS-Setup-0.2.2.exe`。私钥不随软件分发、不进入仓库、不交给 AI。没有可信证书时安装器仍是“未知发布者”，SmartScreen 可能拦截。

## Linux

`.deb` 本身可由 `dpkg-deb` 校验完整性。正式仓库分发建议再用组织 GPG 密钥对 `SHA256SUMS.txt` 做 detached signature；签名私钥同样不进仓库。
