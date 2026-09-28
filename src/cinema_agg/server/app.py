"""Liveness only: no database, collector or claims about data freshness."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .logging import logger


class RequestLogging:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid4().hex  # Never trust a caller-supplied correlation ID.
        start = perf_counter()
        status = 500
        started = False

        async def send_response(message: Message) -> None:
            nonlocal status, started
            if message["type"] == "http.response.start":
                started = True
                status = message["status"]
                headers = list(message.get("headers", []))
                headers.extend([
                    (b"x-request-id", request_id.encode("ascii")),
                    (b"cache-control", b"no-store"),
                    (b"x-content-type-options", b"nosniff"),
                ])
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_response)
        except Exception as exc:
            logger.error("request_failed", extra={
                "request_id": request_id, "error_type": type(exc).__name__,
            })
            if started:
                # A partial response cannot safely be replaced by another response.
                raise
            response = JSONResponse(
                {"detail": "Internal server error", "request_id": request_id},
                status_code=500,
            )
            await response(scope, receive, send_response)
        finally:
            logger.info("request_completed", extra={
                "request_id": request_id,
                "status_code": status,
                "duration_ms": round((perf_counter() - start) * 1000, 3),
            })


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("api_started")
    try:
        yield
    finally:
        logger.info("api_stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Warsaw Cinema API", lifespan=lifespan,
        docs_url=None, redoc_url=None, openapi_url=None,
    )
    app.add_middleware(RequestLogging)

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    return app
