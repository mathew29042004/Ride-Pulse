"""Request-scoped context (current user, client IP, request id) without threading it everywhere.

Context variables are safe under both threaded WSGI workers and async views.
"""

from contextvars import ContextVar

current_user: ContextVar = ContextVar("current_user", default=None)
current_ip: ContextVar[str | None] = ContextVar("current_ip", default=None)
current_request_id: ContextVar[str] = ContextVar("current_request_id", default="-")


def get_current_user():
    user = current_user.get()
    return user if user is not None and getattr(user, "is_authenticated", False) else None
