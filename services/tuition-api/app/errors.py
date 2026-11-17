"""Common error format for every service error.

Every non-2xx response from this service has the body:
    {"error": {"code": "SOME_CODE", "message": "Human readable text", "details": {...} | [...] | null}}
"""

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

# Default codes for plain HTTP errors raised by the framework (unknown route, wrong method, ...).
_HTTP_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    503: "SERVICE_UNAVAILABLE",
}


class AppError(Exception):
    """Raise this from routes/services to return a well-formed error response."""

    def __init__(self, status_code: int, code: str, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def error_body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details}}


def _response(status_code: int, code: str, message: str, details: Any = None, headers: dict | None = None) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=jsonable_encoder(error_body(code, message, details)), headers=headers)


async def _app_error(_: Request, exc: AppError) -> JSONResponse:
    return _response(exc.status_code, exc.code, exc.message, exc.details)


async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    details = [
        {"field": ".".join(str(p) for p in err.get("loc", ()) if p != "body"), "message": err.get("msg"), "type": err.get("type")}
        for err in exc.errors()
    ]
    return _response(status.HTTP_422_UNPROCESSABLE_ENTITY, "VALIDATION_ERROR", "Request validation failed.", details)


async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = _HTTP_CODES.get(exc.status_code, "HTTP_ERROR")
    message = exc.detail if isinstance(exc.detail, str) else code.replace("_", " ").capitalize()
    return _response(exc.status_code, code, message, headers=getattr(exc, "headers", None))


async def _unhandled_error(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error", exc_info=exc)
    return _response(status.HTTP_500_INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", "An unexpected error occurred.")


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(Exception, _unhandled_error)
