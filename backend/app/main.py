"""FastAPI application factory and middleware."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .config import get_settings
from .db import init_db
from .errors import AppError, E, error_body, install_error_handlers
from .jobs import maintenance_loop
from .logging_setup import request_id_ctx, setup_logging
from .ratelimit import client_ip, enforce
from . import admin
from .routers import auth, certificates, domains, meta, realname, records, tools

log = logging.getLogger("liuli.http")


def create_app() -> FastAPI:
    setup_logging()
    s = get_settings()
    dev = not s.is_prod

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # noqa: ANN001
        init_db()
        task = None
        if s.app_env != "test":
            task = asyncio.create_task(maintenance_loop())
        yield
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    app = FastAPI(
        title="LiuliDNS API",
        version=s.app_version,
        docs_url="/docs" if dev else None,
        redoc_url=None,
        openapi_url="/openapi.json" if dev else None,
        lifespan=lifespan,
    )
    install_error_handlers(app)

    @app.middleware("http")
    async def request_context(request: Request, call_next):  # noqa: ANN001
        rid = uuid.uuid4().hex[:16]
        token = request_id_ctx.set(rid)
        started = time.perf_counter()
        try:
            if s.server_role == "control" and request.url.path.startswith("/admin"):
                host = (request.headers.get("host") or "").split(":")[0].lower()
                admin_host = (urlsplit(s.admin_public_url).hostname or "").lower()
                allowed = {"127.0.0.1", "localhost", "::1"}
                if s.app_env == "test":
                    allowed.add("testserver")
                if admin_host:
                    allowed.add(admin_host)
                if host not in allowed:
                    # Keep the public API host from serving the operator UI.
                    return JSONResponse(status_code=404, content={"detail": "Not Found"})
            if request.url.path.startswith(s.api_prefix) and request.url.path not in (
                f"{s.api_prefix}/healthz", "/healthz",
            ):
                try:
                    enforce(f"global:ip:{client_ip(request)}", s.global_ip_per_minute, 60,
                            "请求过于频繁")
                    enforce("global:instance", s.global_instance_per_minute, 60, "服务繁忙")
                except AppError as exc:
                    return JSONResponse(
                        error_body(exc.code, exc.message, rid, exc.details),
                        status_code=exc.status, headers=exc.headers,
                    )
            response = await call_next(request)
            response.headers["X-Request-ID"] = rid
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Cache-Control"] = "no-store"
            if s.is_prod:
                response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
            log.info("http %s %s -> %s %.1fms", request.method, request.url.path,
                     response.status_code, (time.perf_counter() - started) * 1000)
            return response
        finally:
            request_id_ctx.reset(token)

    prefix = s.api_prefix
    app.include_router(meta.router, prefix=prefix)
    app.include_router(auth.router, prefix=prefix)
    app.include_router(realname.router, prefix=prefix)
    app.include_router(domains.router, prefix=prefix)
    app.include_router(records.router, prefix=prefix)
    app.include_router(certificates.router, prefix=prefix)
    app.include_router(certificates.extra_router, prefix=prefix)
    app.include_router(tools.router, prefix=prefix)
    app.include_router(admin.router)

    @app.get("/healthz")
    def root_health():
        return {"ok": True, "service": s.app_name}

    @app.get("/")
    def root():
        return {"name": s.app_name, "version": s.app_version, "api": prefix}

    return app


app = create_app()
