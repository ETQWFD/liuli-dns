# 03 · Windows 打包、NSIS 与代码签名

> 本仓库的源代码、后端测试、DNS 实测和 QML 离屏渲染在 Linux 构建环境完成。**Windows EXE/NSIS 安装包与 Authenticode 签名必须在 Windows 10/11 x64 签名机上构建**；本仓库提供脚本，不包含任何证书私钥或 PFX。

## 1. 构建机要求

| 项目 | 要求 |
|---|---|
| 系统 | Windows 10/11 x64（建议专用干净构建机/CI runner） |
| Python | 3.12.x x64，加入 PATH |
| 虚拟环境 | 每个版本新建 `.venv`，不复用不明来源的包 |
| 打包 | PyInstaller 6.x（默认）或 Nuitka 2.6+（备选） |
| 安装器 | NSIS 3.x（`makensis.exe`） |
| 签名 | Windows SDK `signtool.exe`；OV/EV 代码签名证书 |
| 签名私钥 | 证书存储/云 HSM；**不得复制到仓库、聊天、AI、构建缓存** |

## 2. PyInstaller 构建（默认路径）

在仓库根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1 `
  -Python "C:\Python312\python.exe" `
  -Thumbprint "<证书指纹>" `
  -Version "0.1.0"
```

脚本步骤：

1. 新建/复用 `.venv`，安装 `client/requirements.txt` 与 `pyinstaller==6.11.1`。
2. 运行 `scripts/check_secrets.ps1`；发现私钥/Token/.env 立即失败。
3. `PyInstaller --noconfirm --clean packaging\liuli.spec`，生成 `dist\LiuliDNS\`（onedir）。
4. 把 `README.md`、`LICENSE`、`SECURITY-BOUNDARIES.md` 复制进 payload。
5. 若提供 `-Thumbprint`：先签 `dist\LiuliDNS\LiuliDNS.exe`。
6. `makensis` 生成 `dist\LiuliDNS-Setup-0.1.0.exe`，再签安装包。
7. 输出 `dist\SHA256SUMS.txt`。

没有证书时可加 `-SkipSign` 做内部测试，但**不得作为正式发布版**。

### 手工等价命令

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -U pip wheel
.\.venv\Scripts\python -m pip install -r client\requirements.txt "pyinstaller==6.11.1"
.\.venv\Scripts\python -m PyInstaller --noconfirm --clean packaging\liuli.spec
makensis /DAPP_VERSION=0.1.0 /DAPP_VERSION4=0.1.0.0 /DDIST_DIR="$PWD\dist" packaging\installer.nsi
```

## 3. Nuitka 备选

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build_nuitka.ps1
```

关键参数：`--standalone --enable-plugin=pyside6 --windows-console-mode=disable`，并通过 `--include-data-dir` 带上 `client/app/qml` 和 `client/resources`。产物复制到 `dist\LiuliDNS\` 后，复用同一 `installer.nsi` 和签名流程。

Nuitka 与 PyInstaller 二选一；不要在同一安装包混放两套运行时。

## 4. 安装器行为

`packaging/installer.nsi`：

- 每用户安装到 `%LOCALAPPDATA%\Programs\LiuliDNS`，`RequestExecutionLevel user`，不要求管理员。
- 创建开始菜单/桌面快捷方式与卸载入口，写入 HKCU 卸载信息。
- 卸载删除安装目录和快捷方式；**保留**用户设置、崩溃日志与本地实验证书，避免静默毁坏用户数据。
- 不含开机自启、服务、驱动、防火墙规则或后台守护进程。
- 安装包与 EXE 使用同一证书签名；安装器本身不携带私钥。

安装/卸载验收：

```powershell
# 安装后
Get-AuthenticodeSignature .\dist\LiuliDNS\LiuliDNS.exe | Format-List
Get-AuthenticodeSignature .\dist\LiuliDNS-Setup-0.1.0.exe | Format-List
# 启动 → 设置页切换主题/语言 → 工具箱端口校验 → 退出 → 卸载
```

## 5. 代码签名

### 5.1 证书与私钥保管

- 购买 OV 或 EV 代码签名证书（按目标用户与 SmartScreen 预期选择）；证书主体名称必须与发布者一致。
- 私钥只存在于签名机的证书存储或云 HSM。若 CA 要求 PFX，PFX 只放在签名机的受控目录，使用后删除，绝不进入仓库/构建产物/工单/聊天。
- 不在脚本中写 PFX 密码；`sign.ps1` 只按证书指纹调用已安装的证书。
- 换机时通过 CA/HSM 的合规流程迁移，不复制私钥到开发机。

### 5.2 签名命令

```powershell
powershell -ExecutionPolicy Bypass -File packaging\sign.ps1 `
  -Target "dist\LiuliDNS\LiuliDNS.exe" `
  -Thumbprint "<40位指纹>" `
  -TimestampUrl "http://timestamp.digicert.com"
```

脚本会检查证书存在、含私钥、未过期，然后：

```text
signtool sign /sha1 <thumbprint> /fd SHA256 /tr <timestamp> /td SHA256 /v <file>
signtool verify /pa /v <file>
```

签名顺序：**先签 EXE，再打 NSIS，最后签安装包**。否则安装包内是未签名 EXE。

### 5.3 SmartScreen 说明

- 不承诺 SmartScreen 永久无弹窗；信誉需要证书一致性与下载量累积。
- 坚持同一证书签名所有版本，发布页公示发布者名称与 SHA-256。
- 早期用户可能看到“Windows 已保护你的电脑”；引导用户核对发布者，不要教用户盲目点“仍要运行”。
- EV 证书通常有更好的初始信誉，但不构成绝对无提示承诺。

## 6. 客户端端口与防火墙

- 设置页“本地实验端口”支持 1024–65535；保存前在客户端校验合法性与占用。
- “放行防火墙”按钮生成提权请求（UAC），只为用户选择的本地实验端口添加规则；拒绝 UAC 则不修改系统。
- 客户端不做静默提权、不做防杀进程、不写开机自启、不监听 `0.0.0.0`；本地实验服务只绑定 `127.0.0.1`。
- 公网 53/443 端口属于服务端部署，不由安装器修改。

## 7. 崩溃日志

- 运行时崩溃写入 `QStandardPaths::AppLocalDataLocation/logs/crash-*.log`；设置页“打开日志目录”可直接定位。
- 日志会脱敏邮箱、密码、令牌、Authorization、私钥块、证件号等模式；不记录请求体中的敏感字段。
- 崩溃弹窗提供“复制到剪贴板”；用户可自行决定是否发给支持人员。
- 发布前用 `scripts/check_secrets.sh`/`.ps1` 扫描源码与构建 payload；崩溃日志不得进入仓库。

## 8. 发布检查清单

- [ ] `pytest -q` 全绿（当前 54 passed）。
- [ ] `scripts/check_secrets.sh` 无命中；无 `.env`、`.pem`、`.key`、`.pfx`、`.p12`。
- [ ] 在干净 Windows VM 安装/启动/卸载；确认无开机自启、无服务、无后台进程。
- [ ] EXE 与安装包 `signtool verify /pa` 通过，时间戳有效。
- [ ] 设置页三语/双主题切换；崩溃日志可复制；端口校验与 UAC 放行可用。
- [ ] 关闭后端时客户端显示网络错误，不泄露内部异常；配置 HTTPS 后真实登录/域名/证书链路通过。
- [ ] `SHA256SUMS.txt` 与发布页哈希一致；发布页写明“不承诺公网绝对可达/不承诺绝对无 Bug”。
- [ ] 未签名构建只用于内部测试，不对外发布。

## 9. 已知边界

- 本 Linux 环境未执行 Windows 编译/签名；不能声称已有签名 EXE。脚本和 NSIS 定义已提供，需在 Windows 签名机跑通后发布。
- PyInstaller/Nuitka 产物体积较大（PySide6 运行时），首次启动可能较慢；不承诺绝对不卡顿。
- 杀毒软件可能对未签名/新签名安装包误报；按厂商流程提交误报，不通过关闭防护解决。
- 代码签名私钥永不交给 AI；如有人要求提供私钥/PFX，应拒绝并走签名机流程。
