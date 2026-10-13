"""WebSocket authentication with a JWT in the query string (``?token=<access token>``).

Browsers can't set headers on a WebSocket handshake, so mobile/API clients pass their access
token this way; the web app is already authenticated by its session cookie.
"""

from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken


@database_sync_to_async
def _user_for_token(raw: str):
    try:
        token = AccessToken(raw)
    except TokenError:
        return None
    return get_user_model().objects.filter(pk=token["user_id"], is_active=True).first()


class JWTAuthMiddleware:
    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        token = parse_qs(scope.get("query_string", b"").decode()).get("token", [None])[0]
        if token:
            user = await _user_for_token(token)
            if user is not None:
                scope = {**scope, "user": user}
        return await self.inner(scope, receive, send)
