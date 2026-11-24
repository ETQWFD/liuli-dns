"""Persistent user preferences via QSettings (no secrets stored here)."""

from __future__ import annotations

from PySide6.QtCore import Property, QObject, QSettings, Signal, Slot


class AppSettings(QObject):
    glassModeChanged = Signal()
    languageChanged = Signal()
    apiBaseChanged = Signal()
    labPortChanged = Signal()
    onboardingChanged = Signal()
    reduceMotionChanged = Signal()

    def __init__(self, parent=None):  # noqa: ANN001
        super().__init__(parent)
        self._s = QSettings("Liuli", "LiuliDNS")

    def _bool(self, key: str, default: bool) -> bool:
        v = self._s.value(key, default)
        return str(v).lower() in ("true", "1", "yes") if not isinstance(v, bool) else v

    @Property(bool, notify=glassModeChanged)
    def glassMode(self) -> bool:
        return self._bool("ui/glass", True)

    @glassMode.setter
    def glassMode(self, value: bool) -> None:
        self._s.setValue("ui/glass", bool(value))
        self.glassModeChanged.emit()

    @Property(bool, notify=reduceMotionChanged)
    def reduceMotion(self) -> bool:
        return self._bool("ui/reduceMotion", False)

    @reduceMotion.setter
    def reduceMotion(self, value: bool) -> None:
        self._s.setValue("ui/reduceMotion", bool(value))
        self.reduceMotionChanged.emit()

    @Property(str, notify=languageChanged)
    def language(self) -> str:
        return str(self._s.value("ui/language", "zh_CN"))

    @language.setter
    def language(self, value: str) -> None:
        if value not in ("zh_CN", "en_US", "zh_TW"):
            value = "zh_CN"
        self._s.setValue("ui/language", value)
        self.languageChanged.emit()

    @Property(str, notify=apiBaseChanged)
    def apiBase(self) -> str:
        return str(self._s.value("server/apiBase", "http://127.0.0.1:8000/api/v1"))

    @apiBase.setter
    def apiBase(self, value: str) -> None:
        self._s.setValue("server/apiBase", (value or "").strip())
        self.apiBaseChanged.emit()

    @Property(int, notify=labPortChanged)
    def labPort(self) -> int:
        try:
            return int(self._s.value("lab/port", 8765))
        except (TypeError, ValueError):
            return 8765

    @labPort.setter
    def labPort(self, value: int) -> None:
        self._s.setValue("lab/port", int(value))
        self.labPortChanged.emit()

    @Property(bool, notify=onboardingChanged)
    def onboardingDone(self) -> bool:
        return self._bool("ui/onboardingDone", False)

    @onboardingDone.setter
    def onboardingDone(self, value: bool) -> None:
        self._s.setValue("ui/onboardingDone", bool(value))
        self.onboardingChanged.emit()

    @Slot()
    def resetOnboarding(self) -> None:
        self.onboardingDone = False

    @Slot(result=str)
    def qsettingsPath(self) -> str:
        return self._s.fileName()
