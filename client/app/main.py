"""Desktop entry point."""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtWidgets import QApplication, QSplashScreen

from .bridge import Bridge
from .core.crash import APP_VERSION, CrashManager
from .core.i18n import I18n
from .core.localservice import LocalService
from .core.settings import AppSettings
from .ui_theme import UiTheme

def _runtime_dirs() -> tuple[Path, Path]:
    """Locate bundled QML/resources for source, PyInstaller and Nuitka builds."""
    if getattr(sys, "frozen", False):  # PyInstaller onefile/onedir
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return base / "client" / "app", base / "client" / "resources"
    if "__compiled__" in globals():  # Nuitka standalone
        root = Path(sys.executable).resolve().parent
        return root / "client" / "app", root / "client" / "resources"
    source = Path(__file__).resolve().parent
    return source, source.parent / "resources"


APP_DIR, RES_DIR = _runtime_dirs()
QML_DIR = APP_DIR / "qml"


def ensure_assets() -> tuple[str, str]:
    RES_DIR.mkdir(parents=True, exist_ok=True)
    noise = RES_DIR / "noise.png"
    icon = RES_DIR / "app-icon.png"
    if not noise.exists():
        img = QImage(512, 512, QImage.Format_ARGB32_Premultiplied)
        img.fill(QColor(0, 0, 0, 0))
        p = QPainter(img)
        rnd = random.Random(7)
        for _ in range(26000):
            a = rnd.randint(2, 14)
            p.setPen(QPen(QColor(255, 255, 255, a), 1))
            p.drawPoint(rnd.randrange(512), rnd.randrange(512))
        p.end()
        img.save(str(noise))
    if not icon.exists():
        img = QImage(256, 256, QImage.Format_ARGB32_Premultiplied)
        img.fill(QColor(0, 0, 0, 0))
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor("#0b2230"))
        p.setPen(QPen(QColor("#5FE3C8"), 2))
        p.drawRoundedRect(8, 8, 240, 240, 54, 54)
        p.setPen(QColor("#8FFFF0"))
        f = QFont("Noto Sans CJK SC")
        f.setPixelSize(96)
        f.setBold(True)
        p.setFont(f)
        p.drawText(img.rect(), Qt.AlignCenter, "琉")
        p.end()
        img.save(str(icon))
    return str(noise), str(icon)


def choose_font() -> QFont:
    families = set(QFontDatabase.families())
    for name in ("Microsoft YaHei UI", "Microsoft YaHei", "Noto Sans CJK SC",
                 "PingFang SC", "Source Han Sans SC", "WenQuanYi Micro Hei"):
        if name in families:
            f = QFont(name)
            f.setPointSize(10)
            return f
    f = QFont()
    f.setPointSize(10)
    return f


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="LiuliDNS desktop client")
    p.add_argument("--demo", action="store_true", help="run with canned local data")
    p.add_argument("--screenshot", metavar="DIR", help="render pages to PNG and exit")
    p.add_argument("--page", default="", help="initial page")
    p.add_argument("--theme", choices=["glass", "native"], default="")
    p.add_argument("--lang", choices=["zh_CN", "en_US", "zh_TW"], default="")
    p.add_argument("--auth", action="store_true", help="screenshot the sign-in screen")
    p.add_argument("--tour", action="store_true", help="screenshot the onboarding tour")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    QApplication.setApplicationName("LiuliDNS")
    QApplication.setOrganizationName("Liuli")
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon())
    app.setFont(choose_font())
    noise, icon_path = ensure_assets()
    app.setWindowIcon(QIcon(icon_path))

    settings = AppSettings()
    if args.lang:
        settings.language = args.lang
    if args.theme:
        settings.glassMode = args.theme == "glass"
    screenshot = bool(args.screenshot)
    if screenshot:
        settings.glassMode = args.theme != "native"
        settings.onboardingDone = not args.tour

    crash = CrashManager()
    log = crash.setup_logging()
    crash.install()
    i18n = I18n(settings)
    bridge = Bridge(settings, crash)
    local_service = LocalService(settings)
    if not (args.auth or args.demo or screenshot or args.tour):
        # Start the bundled private API before QML asks for a captcha. The
        # splash keeps the first launch responsive while a cold API starts.
        splash = QSplashScreen(QPixmap(icon_path))
        splash.show()
        splash.showMessage("正在启动本机服务…", Qt.AlignBottom | Qt.AlignHCenter,
                           QColor("#8FFFF0"))
        app.processEvents()
        local_service.start(tick=app.processEvents)
        splash.close()
        if local_service.error:
            log.error("local service: %s", local_service.error)
    if args.auth:
        bridge.enable_demo()
        bridge.demo_guest()
    elif args.demo or screenshot:
        bridge.enable_demo()

    theme = UiTheme(settings, app)
    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()
    ctx.setContextProperty("Bridge", bridge)
    ctx.setContextProperty("LocalService", local_service)
    ctx.setContextProperty("uiTheme", theme)
    ctx.setContextProperty("Settings", settings)
    ctx.setContextProperty("I18n", i18n)
    ctx.setContextProperty("Crash", crash)
    ctx.setContextProperty("AppVersion", APP_VERSION)
    ctx.setContextProperty("NoiseUrl", QUrl.fromLocalFile(noise).toString())
    ctx.setContextProperty("IconUrl", QUrl.fromLocalFile(icon_path).toString())
    engine.addImportPath(str(QML_DIR))

    engine.load(QUrl.fromLocalFile(str(QML_DIR / "Main.qml")))
    if not engine.rootObjects():
        print("Failed to load QML", file=sys.stderr)
        return 2
    window = engine.rootObjects()[0]
    window.show()

    log.info("client started version=%s demo=%s", APP_VERSION, bridge.demo)
    QTimer.singleShot(300, bridge.bootstrap)

    if args.page:
        QTimer.singleShot(900, lambda: bridge.navigateTo.emit(args.page))

    if screenshot:
        out = Path(args.screenshot)
        out.mkdir(parents=True, exist_ok=True)
        if args.auth:
            pages = ["Auth"]
            names = ["08-auth"]
        elif args.tour:
            pages = ["Onboarding"]
            names = ["09-onboarding"]
        else:
            pages = ["Dashboard", "Domains", "Records", "Certificates", "Realname", "Tools", "Settings"]
            names = ["01-dashboard", "02-domains", "03-records", "04-certificates",
                     "05-realname", "06-tools", "07-settings"]

        def step(index: int = 0) -> None:
            if index >= len(pages):
                QTimer.singleShot(300, app.quit)
                return
            bridge.navigateTo.emit(pages[index])

            def snap() -> None:
                screen = QGuiApplication.primaryScreen()
                img: QImage = screen.grabWindow(int(window.winId())) if screen else QImage()
                path = out / f"{names[index]}.png"
                ok = (not img.isNull()) and img.save(str(path))
                log.info("screenshot %s ok=%s null=%s size=%sx%s", path, ok, img.isNull(), img.width(), img.height())

            QTimer.singleShot(850, snap)
            QTimer.singleShot(1500, lambda i=index: step(i + 1))

        QTimer.singleShot(1200, lambda: step(0))

    app.aboutToQuit.connect(bridge.shutdown)
    app.aboutToQuit.connect(local_service.stop)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
