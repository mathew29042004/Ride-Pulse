"""Domain errors and the API error envelope.

Services raise ``DomainError`` subclasses; the API layer turns them into a consistent JSON body::

    {"error": {"code": "invalid_transition", "message": "...", "field": null, "details": null}}
"""

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler


class DomainError(Exception):
    code = "domain_error"
    status_code = status.HTTP_400_BAD_REQUEST

    def __init__(self, message: str, *, code: str | None = None, field: str | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        self.field = field


class BusinessRuleViolation(DomainError):
    code = "business_rule_violation"
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY


class InvalidStateTransition(DomainError):
    code = "invalid_transition"
    status_code = status.HTTP_409_CONFLICT


class ConflictError(DomainError):
    code = "conflict"
    status_code = status.HTTP_409_CONFLICT


class ActionNotPermitted(DomainError):
    code = "permission_denied"
    status_code = status.HTTP_403_FORBIDDEN


def _envelope(code: str, message: str, *, field=None, details=None) -> dict:
    return {"error": {"code": code, "message": message, "field": field, "details": details}}


def api_exception_handler(exc, context):
    if isinstance(exc, DomainError):
        return Response(_envelope(exc.code, exc.message, field=exc.field), status=exc.status_code)

    if isinstance(exc, Http404):
        exc = exceptions.NotFound()
    elif isinstance(exc, DjangoPermissionDenied):
        exc = exceptions.PermissionDenied()

    response = exception_handler(exc, context)
    if response is None:
        return None
    if (
        isinstance(exc, exceptions.Throttled)
        and getattr(exc, "default_code", "") != "account_locked"
    ):
        from apps.reliability.security import throttled

        view = context.get("view")
        throttled(context.get("request"), getattr(view, "throttle_scope", "") or "", exc.wait)

    if isinstance(exc, exceptions.ValidationError):
        response.data = _envelope("validation_error", "Invalid input.", details=response.data)
    else:
        detail = response.data.get("detail", "") if isinstance(response.data, dict) else ""
        code = getattr(detail, "code", None) or getattr(exc, "default_code", "error")
        response.data = _envelope(code, str(detail) or str(exc))
    return response
