"""UI theme constants exposed to QML (no secrets, purely visual)."""

from __future__ import annotations

from PySide6.QtCore import Property, QObject, Signal

from .core.settings import AppSettings


class UiTheme(QObject):
    glassChanged = Signal()

    def __init__(self, settings: AppSettings, parent=None):  # noqa: ANN001
        super().__init__(parent)
        self._settings = settings
        settings.glassModeChanged.connect(self.glassChanged)

    @Property(bool, notify=glassChanged)
    def glass(self) -> bool:
        return self._settings.glassMode

    @Property(str, constant=True)
    def accent(self) -> str:
        return "#5FE3C8"

    @Property(str, constant=True)
    def accent2(self) -> str:
        return "#7CA8FF"

    @Property(str, constant=True)
    def text(self) -> str:
        return "#E9F7FA"

    @Property(str, constant=True)
    def muted(self) -> str:
        return "#8FB3C2"

    @Property(str, constant=True)
    def danger(self) -> str:
        return "#FF8A8A"

    @Property(str, constant=True)
    def warning(self) -> str:
        return "#FFD37A"

    @Property(str, constant=True)
    def cardNative(self) -> str:
        return "#121C24"

    @Property(str, constant=True)
    def borderNative(self) -> str:
        return "#26343E"
