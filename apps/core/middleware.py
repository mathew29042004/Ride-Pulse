import re
import uuid

from .context import current_ip, current_request_id, current_user

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9\-]{8,64}$")


class RequestContextMiddleware:
    """Tags each request with an id (echoed as ``X-Request-ID``) and exposes the user and IP to
    the audit trail and log records."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        incoming = request.headers.get("X-Request-ID", "")
        request_id = incoming if _REQUEST_ID_PATTERN.match(incoming) else uuid.uuid4().hex
        request.request_id = request_id

        tokens = [
            current_request_id.set(request_id),
            current_ip.set(request.META.get("REMOTE_ADDR")),
            # A lazy object: JWT-authenticated API users are resolved later by DRF, so views
            # that run through DRF re-bind it (see apps.core.api.ContextBindingMixin).
            current_user.set(getattr(request, "user", None)),
        ]
        try:
            response = self.get_response(request)
        finally:
            for var, token in zip(
                (current_request_id, current_ip, current_user), tokens, strict=True
            ):
                var.reset(token)
        response["X-Request-ID"] = request_id
        return response
