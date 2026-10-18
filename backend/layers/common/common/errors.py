"""The contract's error shape: {"error": {"code": ..., "message": ...}} (D-06)."""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)

_CODES = {400: "VALIDATION_ERROR", 401: "UNAUTHORIZED", 403: "FORBIDDEN",
          404: "NOT_FOUND", 405: "VALIDATION_ERROR", 409: "DUPLICATE_FILE",
          413: "PAYLOAD_TOO_LARGE", 502: "INFERENCE_UNAVAILABLE"}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def api_error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status,
                        content={"error": {"code": code, "message": message}})


def _first_error(exc: RequestValidationError) -> str:
    errs = exc.errors()
    if not errs:
        return "invalid request"
    e = errs[0]
    # loc looks like ("body", "tags", "fox"); drop the "body" prefix.
    where = ".".join(str(p) for p in e.get("loc", ()) if p != "body")
    msg = e.get("msg", "invalid value").removeprefix("Value error, ")
    return f"{where}: {msg}" if where else msg


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api(request: Request, exc: ApiError):
        return api_error(exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)   # FastAPI's default is 422
    async def _bad_body(request: Request, exc: RequestValidationError):
        return api_error(400, "VALIDATION_ERROR", _first_error(exc))

    @app.exception_handler(StarletteHTTPException)   # unknown route, wrong method
    async def _http(request: Request, exc: StarletteHTTPException):
        return api_error(exc.status_code, _CODES.get(exc.status_code, "ERROR"), str(exc.detail))

    @app.exception_handler(Exception)
    async def _crash(request: Request, exc: Exception):
        log.exception("unhandled error")
        return api_error(500, "INTERNAL_ERROR", "internal error")
