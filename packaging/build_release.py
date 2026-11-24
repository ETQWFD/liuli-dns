#!/usr/bin/env python3
"""Build the shipping artifacts on Linux:
  * release/liuli-dns_0.2.1_amd64.deb       (native Linux onedir + dpkg-deb)
  * release/LiuliDNS-Setup-0.2.1.exe        (Windows installer, embedded CPython + wheels)
  * release/LiuliDNS-0.2.1-windows-x64-portable.zip
The Windows build deliberately avoids Wine: it ships the official embeddable
CPython runtime and Windows wheels, plus a tiny native launcher compiled by NSIS.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build-tools"
RELEASE = ROOT / "release"
VENV = ROOT / ".venv"
PY = VENV / "bin" / "python"
VERSION = "0.2.1"
WIN_STAGE = BUILD / "win-stage"
WIN_RUNTIME = WIN_STAGE / "runtime"
WHEELS = BUILD / "wheels-win"
EMBED = BUILD / "python-3.11.9-embed-amd64.zip"
MIRROR = "https://mirrors.huaweicloud.com/python/3.11.9"
PYPI = "https://repo.huaweicloud.com/repository/pypi/simple"


def log(msg: str) -> None:
    print(f"\n=== {msg} ===", flush=True)


def run(cmd, cwd=ROOT, timeout=None, env=None, check=True):
    print("$", " ".join(str(x) for x in cmd), flush=True)
    subprocess.run(cmd, cwd=str(cwd), timeout=timeout, env=env, check=check)


def die(msg: str):
    print("ERROR:", msg, flush=True)
    sys.exit(1)


def fetch(url: str, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        return
    print("download", url, flush=True)
    run(["curl", "-fL", "--retry", "3", "--progress-bar", "-o", str(dest), url], timeout=300)


def pip_download(args, dest: Path, index=PYPI):
    dest.mkdir(parents=True, exist_ok=True)
    cmd = [str(PY), "-m", "pip", "download", "--disable-pip-version-check",
           "--no-cache-dir", "--dest", str(dest),
           "--platform", "win_amd64", "--python-version", "311",
           "--implementation", "cp", "--abi", "cp311", "--abi", "abi3", "--abi", "none",
           "--only-binary=:all:"]
    if index:
        cmd += ["--index-url", index, "--trusted-host", re.sub(r"https?://([^/]+).*", r"\1", index)]
    cmd += args
    try:
        run(cmd, timeout=600)
        return True
    except subprocess.CalledProcessError as exc:
        print("pip download failed:", exc, flush=True)
        return False


def pypi_direct(pkg: str, ver: str, dest: Path, tags=("win_amd64",)):
    """Fallback: resolve wheels from the public PyPI JSON API and download them."""
    url = f"https://pypi.org/pypi/{pkg}/{ver}/json"
    with urllib.request.urlopen(url, timeout=30) as r:
        data = json.load(r)
    files = [u for u in data.get("urls", []) if u["filename"].endswith(".whl")
             and any(t in u["filename"] for t in tags)]
    if not files:
        raise RuntimeError(f"no wheel for {pkg}=={ver}")
    for item in files:
        dest.mkdir(parents=True, exist_ok=True)
        out = dest / item["filename"]
        fetch(item["url"], out)


def build_server_linux() -> Path:
    """Build the private API server that the desktop package starts on demand."""
    log("Linux PyInstaller local API server")
    distroot = BUILD / "server-dist"
    work = BUILD / "pyinstaller-server"
    exe = distroot / "liuli-dns-server"
    if exe.exists() and os.environ.get("REUSE_SERVER") == "1":
        print("reuse", exe, flush=True)
        return exe
    cmd = [str(PY), "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile",
           "--console", "--name", "liuli-dns-server", "--paths", str(ROOT),
           "--distpath", str(distroot), "--workpath", str(work), "--specpath", str(work),
           "--add-data", f"{ROOT / 'backend/app/admin/templates'}:backend/app/admin/templates",
           "--hidden-import", "backend.app.main",
           "--hidden-import", "backend.app.admin",
           "--hidden-import", "uvicorn.logging",
           "--hidden-import", "uvicorn.loops.auto",
           "--hidden-import", "uvicorn.protocols.http.auto",
           "--hidden-import", "uvicorn.protocols.websockets.auto",
           "--hidden-import", "uvicorn.lifespan.on",
           "--exclude-module", "psycopg",
           "--exclude-module", "psycopg2",
           str(ROOT / "server_entry.py")]
    run(cmd, timeout=1200)
    if not exe.exists():
        die(f"missing local server binary: {exe}")
    print("SERVER:", exe, exe.stat().st_size, flush=True)
    return exe


def build_deb():
    log("Linux PyInstaller onedir")
    server_exe = build_server_linux()

    distroot = BUILD / "dist-linux"
    work = BUILD / "pyinstaller-linux"
    qml = ROOT / "client" / "app" / "qml"
    res = ROOT / "client" / "resources"
    hidden = [
        "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtQml", "PySide6.QtQuick",
        "PySide6.QtQuickControls2", "PySide6.QtNetwork", "PySide6.QtSvg",
        "PySide6.QtWidgets", "keyring.backends.Windows", "keyring.backends.SecretService",
        "keyring.backends.fail", "keyring.backends.macOS",
    ]
    cmd = [str(PY), "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
           "--name", "liuli-dns", "--paths", str(ROOT),
           "--distpath", str(distroot), "--workpath", str(work), "--specpath", str(work),
           "--add-data", f"{qml}:client/app/qml",
           "--add-data", f"{res}:client/resources",
           "--exclude-module", "tkinter",
           "--exclude-module", "PySide6.QtWebEngineCore",
           "--exclude-module", "PySide6.QtWebEngineWidgets",
           "--exclude-module", "PySide6.QtWebChannel"]
    for h in hidden:
        cmd += ["--hidden-import", h]
    cmd += [str(ROOT / "packaging" / "entry.py")]
    appdir = distroot / "liuli-dns"
    exe = appdir / "liuli-dns"
    if not exe.exists() or os.environ.get("REUSE_LINUX") != "1":
        run(cmd, timeout=1200)

    appdir = distroot / "liuli-dns"
    exe = appdir / "liuli-dns"
    if not exe.exists():
        die(f"missing PyInstaller output: {exe}")
    log("smoke-test PyInstaller app")
    shot = BUILD / "deb-smoke"
    shutil.rmtree(shot, ignore_errors=True)
    shot.mkdir(parents=True)
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "xcb"
    try:
        run(["xvfb-run", "-a", "-s", "-screen 0 1440x900x24", str(exe),
             "--demo", "--screenshot", str(shot)], timeout=45, env=env)
    except Exception as exc:
        print("WARN: smoke test failed", exc, flush=True)
    pngs = list(shot.glob("*.png"))
    print(f"smoke screenshots: {len(pngs)}", flush=True)
    if not pngs:
        print("WARN: no screenshot produced; Debian package still built", flush=True)

    log("assemble Debian package")
    pkg = BUILD / "deb-root"
    shutil.rmtree(pkg, ignore_errors=True)
    bindir = pkg / "usr" / "lib" / "liuli-dns"
    shutil.copytree(appdir, bindir)
    shutil.copy2(server_exe, bindir / "liuli-dns-server")
    (bindir / "liuli-dns-server").chmod(0o755)
    tunnel_bin = BUILD / "tunnel-dist" / "liuli-tunnel"
    cloudflared_bin = BUILD / "cloudflared-linux-amd64"
    if tunnel_bin.exists():
        shutil.copy2(tunnel_bin, bindir / "liuli-tunnel")
        (bindir / "liuli-tunnel").chmod(0o755)
    if cloudflared_bin.exists():
        shutil.copy2(cloudflared_bin, bindir / "cloudflared")
        (bindir / "cloudflared").chmod(0o755)
    (pkg / "usr" / "bin").mkdir(parents=True)
    os.symlink("../lib/liuli-dns/liuli-dns", pkg / "usr" / "bin" / "liuli-dns")
    (pkg / "usr" / "share" / "applications").mkdir(parents=True)
    (pkg / "usr" / "share" / "applications" / "liuli-dns.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=LiuliDNS\n"
        "Comment=DNS hosting and management desktop client\n"
        "Exec=liuli-dns\nIcon=liuli-dns\nTerminal=false\n"
        "Categories=Network;Utility;\nStartupWMClass=LiuliDNS\n", encoding="utf-8")
    icon = ROOT / "client" / "resources" / "app-icon.png"
    icon_dir = pkg / "usr" / "share" / "icons" / "hicolor" / "512x512" / "apps"
    icon_dir.mkdir(parents=True)
    shutil.copy2(icon, icon_dir / "liuli-dns.png")
    doc = pkg / "usr" / "share" / "doc" / "liuli-dns"
    doc.mkdir(parents=True)
    shutil.copy2(ROOT / "LICENSE", doc / "copyright")
    if (ROOT / "README.md").exists():
        shutil.copy2(ROOT / "README.md", doc / "README.md")

    debian = pkg / "DEBIAN"
    debian.mkdir(parents=True)
    installed_kb = int(subprocess.check_output(["du", "-sk", str(pkg)], text=True).split()[0])
    control = f"""Package: liuli-dns
Version: {VERSION}
Section: utils
Priority: optional
Architecture: amd64
Maintainer: LiuliDNS Team <support@liuli-dns.com>
Installed-Size: {installed_kb}
Depends: libc6 (>= 2.35), libgl1, libegl1, libxkbcommon0, libxkbcommon-x11-0, libxcb-cursor0, libxcb-icccm4, libxcb-image0, libxcb-keysyms1, libxcb-render-util0, libxcb-shape0, libfontconfig1, libdbus-1-3, libnss3, libxcomposite1, libxdamage1, libxrandr2, libxi6, libxtst6
Recommends: libxcb-util1
Description: LiuliDNS desktop client
 DNS hosting, record management and diagnostics desktop client.
"""
    (debian / "control").write_text(control, encoding="utf-8")
    (debian / "postinst").write_text(
        "#!/bin/sh\nset -e\nif command -v update-desktop-database >/dev/null 2>&1; then update-desktop-database -q /usr/share/applications || true; fi\n"
        "if command -v gtk-update-icon-cache >/dev/null 2>&1; then gtk-update-icon-cache -q -t /usr/share/icons/hicolor || true; fi\nexit 0\n",
        encoding="utf-8")
    (debian / "postrm").write_text(
        "#!/bin/sh\nset -e\nif command -v update-desktop-database >/dev/null 2>&1; then update-desktop-database -q /usr/share/applications || true; fi\nexit 0\n",
        encoding="utf-8")
    for p in (debian / "postinst", debian / "postrm"):
        p.chmod(0o755)

    # md5sums, excluding DEBIAN metadata itself
    lines = []
    for f in pkg.rglob("*"):
        if f.is_file() and "DEBIAN" not in f.parts:
            rel = f.relative_to(pkg).as_posix()
            h = subprocess.check_output(["md5sum", str(f)], text=True).split()[0]
            lines.append(f"{h}  {rel}")
    (debian / "md5sums").write_text("\n".join(lines) + "\n", encoding="utf-8")
    subprocess.run(["chmod", "-R", "go-w", str(pkg)], check=True)

    RELEASE.mkdir(parents=True, exist_ok=True)
    out = RELEASE / f"liuli-dns_{VERSION}_amd64.deb"
    out.unlink(missing_ok=True)
    run(["dpkg-deb", "--build", "--root-owner-group", "-Zgzip", str(pkg), str(out)], timeout=600)
    run(["dpkg-deb", "-I", str(out)], timeout=30)
    print("DEB:", out, out.stat().st_size, flush=True)
    return out


def download_windows():
    log("download Windows embeddable Python + wheels")
    BUILD.mkdir(parents=True, exist_ok=True)
    fetch(f"{MIRROR}/python-3.11.9-embed-amd64.zip", EMBED)
    with zipfile.ZipFile(EMBED) as z:
        if "python.exe" not in z.namelist():
            die("embeddable zip missing python.exe")
    WHEELS.mkdir(parents=True, exist_ok=True)

    pyside = ["PySide6==6.8.1", "PySide6-Essentials==6.8.1", "shiboken6==6.8.1"]
    ok = pip_download(["--no-deps"] + pyside, WHEELS)
    if not ok or not list(WHEELS.glob("PySide6*.whl")):
        print("fallback to PyPI JSON for PySide6", flush=True)
        for pkg in ("PySide6", "PySide6-Essentials", "shiboken6"):
            pypi_direct(pkg, "6.8.1", WHEELS)

    req = BUILD / "requirements-win.txt"
    req.write_text(
        "httpx==0.28.1\nkeyring==25.6.0\npywin32-ctypes==0.2.3\n"
        "dnspython==2.7.0\ncryptography==42.0.8\n", encoding="utf-8")
    ok = pip_download(["-r", str(req)], WHEELS)
    if not ok:
        print("retry deps with default PyPI", flush=True)
        if not pip_download(["-r", str(req)], WHEELS, index=None):
            die("Windows dependency wheel download failed")

    server_req = ROOT / "packaging" / "requirements-win-server.txt"
    ok = pip_download(["-r", str(server_req)], WHEELS)
    if not ok:
        print("retry server deps with default PyPI", flush=True)
        if not pip_download(["-r", str(server_req)], WHEELS, index=None):
            die("Windows local-server dependency wheel download failed")

    # Optional VC runtime wheel, in case PySide6 does not bundle msvcp140.
    try:
        pip_download(["--no-deps", "msvc-runtime"], WHEELS)
    except Exception:
        pass
    wheels = sorted(WHEELS.glob("*.whl"))
    print(f"wheels: {len(wheels)}", flush=True)


def build_windows_stage():
    log("assemble Windows stage")
    shutil.rmtree(WIN_STAGE, ignore_errors=True)
    WIN_STAGE.mkdir(parents=True)
    WIN_RUNTIME.mkdir(parents=True)
    with zipfile.ZipFile(EMBED) as z:
        z.extractall(WIN_RUNTIME)

    site = WIN_RUNTIME / "Lib" / "site-packages"
    site.mkdir(parents=True)
    for whl in sorted(WHEELS.glob("*.whl")):
        print("unpack", whl.name, flush=True)
        with zipfile.ZipFile(whl) as z:
            z.extractall(site)

    # Make embeddable CPython import site-packages.
    pth = WIN_RUNTIME / "python311._pth"
    pth.write_text("python311.zip\n.\nLib\\site-packages\nimport site\n", encoding="utf-8")

    app = WIN_STAGE / "app"
    app.mkdir()
    shutil.copytree(ROOT / "client", app / "client",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
    shutil.copytree(ROOT / "backend", app / "backend",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo",
                                                  "tests", ".pytest_cache", "data"))
    shutil.copy2(ROOT / "server_entry.py", app / "server_entry.py")
    for name in ("liuli-tunnel.exe", "cloudflared.exe"):
        src = (BUILD / "tunnel-dist" / name) if name.startswith("liuli") else (BUILD / "cloudflared-windows-amd64.exe")
        if src.exists():
            shutil.copy2(src, WIN_RUNTIME / name)
            if name.startswith("liuli"):
                shutil.copy2(src, WIN_STAGE / name)
        else:
            print("WARN: missing Windows tunnel asset", src, flush=True)
    (app / "packaging").mkdir()
    shutil.copy2(ROOT / "packaging" / "entry.py", app / "packaging" / "entry.py")
    shutil.copy2(ROOT / "LICENSE", WIN_STAGE / "LICENSE")
    (WIN_STAGE / "README-Windows.txt").write_text(
        "LiuliDNS Windows desktop client + private local service\n\n"
        "Run LiuliDNS.exe. The bundled runtime is CPython 3.11.9 (embeddable)\n"
        "with PySide6 6.8.1. No Python installation is required.\n\n"
        "The client starts a private API on 127.0.0.1:8000 automatically.\n"
        "Email may be verified locally, but real-name status stays unverified\n"
        "until the platform review issues a one-time activation code. Domain\n"
        "creation is blocked until activation. All public hostnames use Cloudflare\n"
        "Tunnel; IPv4 origin is not supported. Free plan has no SLA.\n"
        "Data lives in %LOCALAPPDATA%\\LiuliDNS\\server.\n\n"
        "For public DNS hosting, point Settings -> Server to a separately\n"
        "deployed API; see docs/02-deploy.md.\n", encoding="utf-8")

    # Check the Qt runtime DLL dependencies; PySide6 normally bundles these.
    missing = []
    for dll in ("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll"):
        if not any(site.rglob(dll)) and not (WIN_RUNTIME / dll).exists():
            missing.append(dll)
    print("VC runtime missing:", missing, flush=True)
    if missing:
        # Copy any msvc-runtime wheel payload into runtime root if available.
        for whl in WHEELS.glob("msvc_runtime*.whl"):
            with zipfile.ZipFile(whl) as z:
                for n in z.namelist():
                    if n.lower().endswith((".dll",)):
                        target = WIN_RUNTIME / Path(n).name
                        target.write_bytes(z.read(n))
        print("copied msvc-runtime DLLs", flush=True)

    log("build native Windows launcher (NSIS)")
    launcher = BUILD / "launcher.nsi"
    launcher.write_text(f'''!include "MUI2.nsh"
Name "LiuliDNS"
OutFile "{WIN_STAGE / 'LiuliDNS.exe'}"
Icon "{ROOT / 'client/resources/app-icon.ico'}"
RequestExecutionLevel user
SilentInstall silent
AutoCloseWindow true
ShowInstDetails nevershow
VIProductVersion "{VERSION}.0"
VIAddVersionKey /LANG=1033 "ProductName" "LiuliDNS"
VIAddVersionKey /LANG=1033 "FileDescription" "LiuliDNS desktop client launcher"
VIAddVersionKey /LANG=1033 "FileVersion" "{VERSION}.0"
VIAddVersionKey /LANG=1033 "LegalCopyright" "LiuliDNS"
Section
  SetOutPath "$EXEDIR"
  Exec '"$EXEDIR\\runtime\\pythonw.exe" "$EXEDIR\\app\\packaging\\entry.py"'
SectionEnd
''', encoding="utf-8")
    run(["makensis", "-V2", str(launcher)], timeout=120, cwd=ROOT)
    if not (WIN_STAGE / "LiuliDNS.exe").exists():
        die("launcher build failed")
    subprocess.run(["file", str(WIN_STAGE / "LiuliDNS.exe")], check=False)

    log("build Windows installer (NSIS)")
    nsi = BUILD / "installer-win.nsi"
    stage = str(WIN_STAGE)
    nsi.write_text(f'''!include "MUI2.nsh"
!include "FileFunc.nsh"
Unicode true
Name "LiuliDNS"
OutFile "{RELEASE / f'LiuliDNS-Setup-{VERSION}.exe'}"
InstallDir "$LOCALAPPDATA\\Programs\\LiuliDNS"
InstallDirRegKey HKCU "Software\\LiuliDNS" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
SetCompressorDictSize 32
XPStyle on
VIProductVersion "{VERSION}.0"
VIAddVersionKey /LANG=1033 "ProductName" "LiuliDNS"
VIAddVersionKey /LANG=1033 "CompanyName" "LiuliDNS"
VIAddVersionKey /LANG=1033 "FileDescription" "LiuliDNS desktop client installer"
VIAddVersionKey /LANG=1033 "FileVersion" "{VERSION}.0"
VIAddVersionKey /LANG=1033 "LegalCopyright" "LiuliDNS"
!define MUI_ICON "{ROOT / 'client/resources/app-icon.ico'}"
!define MUI_UNICON "{ROOT / 'client/resources/app-icon.ico'}"
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\\LiuliDNS.exe"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "{ROOT / 'LICENSE'}"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"
!insertmacro MUI_LANGUAGE "SimpChinese"
Section "LiuliDNS (required)" SecMain
  SectionIn RO
  SetOutPath "$INSTDIR"
  File /r "{stage}\\*"
  WriteRegStr HKCU "Software\\LiuliDNS" "InstallDir" "$INSTDIR"
  WriteUninstaller "$INSTDIR\\Uninstall.exe"
  CreateDirectory "$SMPROGRAMS\\LiuliDNS"
  CreateShortcut "$SMPROGRAMS\\LiuliDNS\\LiuliDNS.lnk" "$INSTDIR\\LiuliDNS.exe" "" "$INSTDIR\\LiuliDNS.exe" 0
  CreateShortcut "$SMPROGRAMS\\LiuliDNS\\Uninstall.lnk" "$INSTDIR\\Uninstall.exe"
  CreateShortcut "$DESKTOP\\LiuliDNS.lnk" "$INSTDIR\\LiuliDNS.exe" "" "$INSTDIR\\LiuliDNS.exe" 0
  WriteRegStr HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\LiuliDNS" "DisplayName" "LiuliDNS"
  WriteRegStr HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\LiuliDNS" "DisplayVersion" "{VERSION}"
  WriteRegStr HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\LiuliDNS" "Publisher" "LiuliDNS"
  WriteRegStr HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\LiuliDNS" "UninstallString" '"$INSTDIR\\Uninstall.exe"'
  WriteRegDWORD HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\LiuliDNS" "NoModify" 1
  WriteRegDWORD HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\LiuliDNS" "NoRepair" 1
SectionEnd
Section "Uninstall"
  Delete "$DESKTOP\\LiuliDNS.lnk"
  Delete "$SMPROGRAMS\\LiuliDNS\\LiuliDNS.lnk"
  Delete "$SMPROGRAMS\\LiuliDNS\\Uninstall.lnk"
  RMDir "$SMPROGRAMS\\LiuliDNS"
  DeleteRegKey HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\LiuliDNS"
  DeleteRegKey HKCU "Software\\LiuliDNS"
  RMDir /r "$INSTDIR"
SectionEnd
''', encoding="utf-8")
    run(["makensis", "-V2", str(nsi)], timeout=600, cwd=ROOT)

    out = RELEASE / f"LiuliDNS-Setup-{VERSION}.exe"
    if not out.exists():
        die("installer build failed")
    print("EXE:", out, out.stat().st_size, flush=True)

    log("portable zip")
    pz = RELEASE / f"LiuliDNS-{VERSION}-windows-x64-portable.zip"
    pz.unlink(missing_ok=True)
    run(["zip", "-qr", str(pz), "."], cwd=WIN_STAGE, timeout=300)
    print("ZIP:", pz, pz.stat().st_size, flush=True)
    return out, pz


def main():
    RELEASE.mkdir(parents=True, exist_ok=True)
    (BUILD / "logs").mkdir(parents=True, exist_ok=True)
    deb = build_deb()
    download_windows()
    exe, portable = build_windows_stage()
    sums = RELEASE / "SHA256SUMS.txt"
    files = [deb, exe, portable]
    lines = []
    for f in files:
        h = subprocess.check_output(["sha256sum", str(f)], text=True)
        lines.append(h.strip())
    sums.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log("DONE")
    for f in files:
        print(f"{f.name}\t{f.stat().st_size} bytes", flush=True)
    print(sums.read_text(), flush=True)


if __name__ == "__main__":
    main()
