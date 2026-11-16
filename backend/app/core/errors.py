"""Consistent application errors (ADD iteration 1: consistent error format).

Services raise these; app.main converts them into
{"error": {"code": ..., "message": ...}} with the right HTTP status.
"""
from __future__ import annotations


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, code: str | None = None, details: dict | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        self.details = details or {}


class ValidationFailed(AppError):
    status_code = 400
    code = "validation_failed"


class Unauthorized(AppError):
    status_code = 401
    code = "unauthorized"


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class ServiceUnavailable(AppError):
    status_code = 503
    code = "service_unavailable"
