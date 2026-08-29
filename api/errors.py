"""RFC 7807 problem+json errors — PRD §5.1.

Every error this API returns is a :class:`ProblemDetail`, never a bare
``{"detail": "..."}`` or a stack trace. Routers raise :class:`ApiError`; the
handlers registered by :func:`register_exception_handlers` are the only place
that turns an exception into a response, so a router can never accidentally
leak an internal message by forgetting to catch something.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException as StarletteHTTPException

__all__ = ["ApiError", "ProblemDetail", "register_exception_handlers"]

_LOG = logging.getLogger("fc.api")

_PROBLEM_MEDIA_TYPE = "application/problem+json"


class ProblemDetail(BaseModel):
    """RFC 7807. ``extra="allow"`` is deliberate here and nowhere else in this
    codebase: the RFC is explicitly extensible (§3.2), and PRD §5.1's own
    example error carries a ``candidates`` member for an ambiguous match —
    the extension member IS the payload for that error, not an afterthought.
    """

    model_config = ConfigDict(extra="allow")

    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None


class ApiError(Exception):
    """The one way a router signals an error. Never raise a bare ``HTTPException``
    or return an error dict directly — both would bypass the RFC 7807 shape."""

    def __init__(
        self,
        status_code: int,
        title: str,
        detail: str | None = None,
        *,
        type_: str = "about:blank",
        **extensions: Any,
    ) -> None:
        super().__init__(detail or title)
        self.status_code = status_code
        self.title = title
        self.detail = detail
        self.type = type_
        self.extensions = extensions


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        problem = ProblemDetail(
            type=exc.type,
            title=exc.title,
            status=exc.status_code,
            detail=exc.detail,
            instance=str(request.url.path),
            **exc.extensions,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=problem.model_dump(exclude_none=True),
            media_type=_PROBLEM_MEDIA_TYPE,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        problem = ProblemDetail.model_validate(
            {
                "title": "validation failed",
                "status": 422,
                "detail": "the request did not match the expected schema",
                "instance": str(request.url.path),
                "errors": exc.errors(),
            }
        )
        return JSONResponse(
            status_code=422,
            content=problem.model_dump(exclude_none=True, mode="json"),
            media_type=_PROBLEM_MEDIA_TYPE,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        problem = ProblemDetail(
            title=str(exc.detail) if exc.detail else "request failed",
            status=exc.status_code,
            instance=str(request.url.path),
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=problem.model_dump(exclude_none=True),
            media_type=_PROBLEM_MEDIA_TYPE,
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Never leak the exception's own message: it may carry a SQL fragment,
        # a file path, or a stack-adjacent detail (CLAUDE.md: "Errors never
        # leak internal detail to the client"). The real message goes to the
        # server log only.
        _LOG.exception("unhandled error on %s", request.url.path)
        problem = ProblemDetail(
            title="internal error",
            status=500,
            detail="an unexpected error occurred",
            instance=str(request.url.path),
        )
        return JSONResponse(
            status_code=500,
            content=problem.model_dump(exclude_none=True),
            media_type=_PROBLEM_MEDIA_TYPE,
        )
