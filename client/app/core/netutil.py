"""Local port validation and Windows firewall rule helper.

Nothing here runs silently with elevation: the UI asks first, and Windows shows
its own UAC prompt. On non-Windows platforms we return instructions instead.
"""

from __future__ import annotations

import platform
import socket
import subprocess

RULE_TEMPLATE = "LiuliDNS Local Lab {port}"


def validate_port(port: int | str) -> tuple[bool, str]:
    try:
        p = int(port)
    except (TypeError, ValueError):
        return False, "端口必须是数字"
    if not 1024 <= p <= 65535:
        return False, "端口需在 1024–65535 之间"
    return True, ""


def port_available(port: int) -> tuple[bool, str]:
    ok, msg = validate_port(port)
    if not ok:
        return False, msg
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", int(port)))
        except OSError:
            return False, "该端口已被占用"
    return True, ""


def _run(args: list[str], timeout: int = 20) -> tuple[int, str]:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)


def rule_exists(port: int) -> bool:
    if platform.system() != "Windows":
        return False
    code, out = _run([
        "netsh", "advfirewall", "firewall", "show", "rule",
        f"name={RULE_TEMPLATE.format(port=port)}",
    ])
    return code == 0 and "Rule" in out or code == 0 and "规则" in out


def add_firewall_rule(port: int) -> tuple[bool, str]:
    if platform.system() != "Windows":
        return False, (
            "当前系统不是 Windows。Linux 可使用："
            f"sudo ufw allow {port}/tcp（若启用 ufw），或仅在本机使用无需放行。"
        )
    if rule_exists(port):
        return True, "规则已存在"
    args = (
        "advfirewall firewall add rule "
        f'name="{RULE_TEMPLATE.format(port=port)}" '
        f"dir=in action=allow protocol=TCP localport={port} profile=private,domain"
    )
    # netsh wants one argument string inside Start-Process; single-quote for PowerShell.
    ps_arg = args.replace("'", "''")
    command = (
        "Start-Process -FilePath 'netsh.exe' "
        f"-ArgumentList '{ps_arg}' -Verb RunAs -Wait"
    )
    code, out = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command], timeout=90)
    if code == 0:
        return True, "已向系统申请添加专用网络入站规则"
    return False, out.strip()[:300] or "用户取消或权限不足"


def firewall_hint(port: int) -> str:
    return (
        "Windows: 设置 → 网络和 Internet → Windows 防火墙 → 高级设置 → 入站规则；"
        f"或管理员终端执行 netsh advfirewall firewall add rule name=\"LiuliDNS Local Lab {port}\" "
        f"dir=in action=allow protocol=TCP localport={port} profile=private,domain"
    )
