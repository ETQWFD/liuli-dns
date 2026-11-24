from __future__ import annotations

from typing import Any

from .errors import ok
from .logging_setup import request_id_ctx


def ok_(data: Any) -> dict:
    return ok(data, request_id_ctx.get())
