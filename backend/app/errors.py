"""Unified error envelope and exception handlers."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class AppError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status: int = 400,
        details: Any | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status = status
        self.details = details
        self.headers = headers or {}
        super().__init__(message)


# Machine-readable codes, stable for the desktop client.
E = {
    "VALIDATION": "VALIDATION",
    "AUTH_REQUIRED": "AUTH_REQUIRED",
    "AUTH_INVALID": "AUTH_INVALID",
    "AUTH_EMAIL_UNVERIFIED": "AUTH_EMAIL_UNVERIFIED",
    "AUTH_LOCKED": "AUTH_LOCKED",
    "CAPTCHA_REQUIRED": "CAPTCHA_REQUIRED",
    "CAPTCHA_INVALID": "CAPTCHA_INVALID",
    "REALNAME_REQUIRED": "REALNAME_REQUIRED",
    "REALNAME_INVALID_STATE": "REALNAME_INVALID_STATE",
    "CODE_INVALID": "CODE_INVALID",
    "CODE_USED": "CODE_USED",
    "CODE_REVOKED": "CODE_REVOKED",
    "CODE_LOCKED": "CODE_LOCKED",
    "DOMAIN_INVALID": "DOMAIN_INVALID",
    "DOMAIN_EXISTS": "DOMAIN_EXISTS",
    "DOMAIN_NOT_ACTIVE": "DOMAIN_NOT_ACTIVE",
    "DOMAIN_LIMIT": "DOMAIN_LIMIT",
    "DOMAIN_VERIFY_FAILED": "DOMAIN_VERIFY_FAILED",
    "DOMAIN_NS_PENDING": "DOMAIN_NS_PENDING",
    "CLOUDFLARE_NOT_CONFIGURED": "CLOUDFLARE_NOT_CONFIGURED",
    "CLOUDFLARE_API_ERROR": "CLOUDFLARE_API_ERROR",
    "TUNNEL_UNAVAILABLE": "TUNNEL_UNAVAILABLE",
    "FREE_DOMAIN_UNAVAILABLE": "FREE_DOMAIN_UNAVAILABLE",
    "UPSTREAM_INVALID": "UPSTREAM_INVALID",
    "RECORD_INVALID": "RECORD_INVALID",
    "RECORD_CONFLICT": "RECORD_CONFLICT",
    "CERT_INVALID": "CERT_INVALID",
    "CERT_KEY_MISMATCH": "CERT_KEY_MISMATCH",
    "CERT_DOMAIN_MISMATCH": "CERT_DOMAIN_MISMATCH",
    "CERT_EXPIRED": "CERT_EXPIRED",
    "CERT_NOT_CONFIGURED": "CERT_NOT_CONFIGURED",
    "IDEMPOTENCY_CONFLICT": "IDEMPOTENCY_CONFLICT",
    "RATE_LIMITED": "RATE_LIMITED",
    "FORBIDDEN": "FORBIDDEN",
    "NOT_FOUND": "NOT_FOUND",
    "CONFLICT": "CONFLICT",
    "INTERNAL": "INTERNAL",
}


def error_body(code: str, message: str, request_id: str, details: Any = None) -> dict:
    body: dict = {"ok": False, "error": {"code": code, "message": message}, "request_id": request_id}
    if details is not None:
        body["error"]["details"] = details
    return body


def ok(data: Any, request_id: str) -> dict:
    return {"ok": True, "data": data, "request_id": request_id}


def install_error_handlers(app: FastAPI) -> None:
    from .logging_setup import request_id_ctx

    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError):  # noqa: ANN001
        rid = request_id_ctx.get()
        return JSONResponse(
            error_body(exc.code, exc.message, rid, exc.details),
            status_code=exc.status,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):  # noqa: ANN001
        rid = request_id_ctx.get()
        details = [
            {"loc": ".".join(str(x) for x in e.get("loc", [])), "msg": e.get("msg", "")}
            for e in exc.errors()[:8]
        ]
        return JSONResponse(
            error_body(E["VALIDATION"], "请求参数不合法", rid, details), status_code=422
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):  # noqa: ANN001
        rid = request_id_ctx.get()
        from .logging_setup import log

        log.exception("unhandled error rid=%s path=%s", rid, request.url.path)
        return JSONResponse(
            error_body(E["INTERNAL"], "服务内部错误，请稍后重试", rid), status_code=500
        )
