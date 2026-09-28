"""Read-only snapshot API; requests never collect data or migrate the database."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Request
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .contracts import ScreeningPage
from .database import SchemaUnavailable, database_engine, require_schema
from .logging import logger
from .repository import SnapshotNotFound, screenings_page
from .settings import Settings


class RequestLogging:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid4().hex  # Never trust a caller-supplied correlation ID.
        scope.setdefault("state", {})["request_id"] = request_id
        start = perf_counter()
        status = 500
        started = False

        async def send_response(message: Message) -> None:
            nonlocal status, started
            if message["type"] == "http.response.start":
                started = True
                status = message["status"]
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (b"x-request-id", request_id.encode("ascii")),
                        (b"cache-control", b"no-store"),
                        (b"x-content-type-options", b"nosniff"),
                    ]
                )
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_response)
        except Exception as exc:
            logger.error(
                "request_failed",
                extra={
                    "request_id": request_id,
                    "error_type": type(exc).__name__,
                },
            )
            if started:
                # A partial response cannot safely be replaced by another response.
                raise
            response = JSONResponse(
                {"detail": "Internal server error", "request_id": request_id},
                status_code=500,
            )
            await response(scope, receive, send_response)
        finally:
            logger.info(
                "request_completed",
                extra={
                    "request_id": request_id,
                    "status_code": status,
                    "duration_ms": round((perf_counter() - start) * 1000, 3),
                },
            )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("api_started")
    try:
        yield
    finally:
        logger.info("api_stopped")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_environment()
    # Engine construction is lazy: a missing database does not create a file.
    engine = database_engine(settings.database_path, readonly=True)

    @asynccontextmanager
    async def app_lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            async with lifespan(app):
                yield
        finally:
            engine.dispose()

    app = FastAPI(
        title="Warsaw Cinema API",
        lifespan=app_lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(RequestLogging)

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    def unavailable(exc: Exception, request: Request) -> HTTPException:
        logger.error(
            "database_unavailable",
            extra={
                "error_type": type(exc).__name__,
                "request_id": request.state.request_id,
            },
        )
        return HTTPException(
            status_code=503, detail="Database unavailable or schema incompatible"
        )

    @app.get("/health/ready")
    def ready(request: Request) -> dict[str, str]:
        try:
            with engine.connect() as connection:
                require_schema(connection)
        except (SQLAlchemyError, SchemaUnavailable) as exc:
            raise unavailable(exc, request) from None
        return {"status": "ready"}

    @app.get("/api/v1/screenings", response_model=ScreeningPage)
    def screenings(
        request: Request,
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0, le=50000),
        cinema_id: str | None = Query(default=None, min_length=1, max_length=100),
        snapshot_id: str | None = Query(default=None, pattern="^[a-f0-9]{64}$"),
    ) -> ScreeningPage:
        try:
            return screenings_page(
                engine,
                limit=limit,
                offset=offset,
                cinema_id=cinema_id,
                snapshot_id=snapshot_id,
            )
        except SnapshotNotFound:
            raise HTTPException(status_code=404, detail="Snapshot not found") from None
        except (SQLAlchemyError, SchemaUnavailable) as exc:
            raise unavailable(exc, request) from None

    return app
