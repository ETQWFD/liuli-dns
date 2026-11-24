"""Refresh-token storage.

Windows: Windows Credential Locker via `keyring`. If keyring is unavailable
(Linux CI, locked-down machines), tokens stay in memory only — never plain files.
"""

from __future__ import annotations

import json

try:  # optional dependency
    import keyring  # type: ignore
except Exception:  # noqa: BLE001
    keyring = None

SERVICE = "LiuliDNS"
ACCOUNT = "refresh-session"


class TokenStore:
    def __init__(self) -> None:
        self._memory: tuple[str, str] | None = None
        self.persistent = False
        if keyring is not None:
            try:
                keyring.get_password(SERVICE, ACCOUNT)
                self.persistent = True
            except Exception:  # noqa: BLE001
                self.persistent = False

    def save(self, refresh_token: str, email: str) -> None:
        self._memory = (refresh_token, email)
        if self.persistent and keyring is not None:
            try:
                keyring.set_password(
                    SERVICE, ACCOUNT, json.dumps({"refresh": refresh_token, "email": email})
                )
            except Exception:  # noqa: BLE001
                self.persistent = False

    def load(self) -> tuple[str, str] | None:
        if self._memory:
            return self._memory
        if self.persistent and keyring is not None:
            try:
                raw = keyring.get_password(SERVICE, ACCOUNT)
                if raw:
                    data = json.loads(raw)
                    if data.get("refresh"):
                        self._memory = (data["refresh"], data.get("email", ""))
                        return self._memory
            except Exception:  # noqa: BLE001
                self.persistent = False
        return None

    def clear(self) -> None:
        self._memory = None
        if keyring is not None:
            try:
                keyring.delete_password(SERVICE, ACCOUNT)
            except Exception:  # noqa: BLE001
                pass
