"""Frozen-build entry point.

PyInstaller/Nuitka must start from this file rather than ``client/app/main.py``
because the latter uses package-relative imports.  This shim keeps the normal
module import path working after freezing.
"""

from __future__ import annotations

import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from client.app.main import main  # noqa: E402

if __name__ == "__main__":
    main()
