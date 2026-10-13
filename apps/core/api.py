"""Shared building blocks for the REST API."""

from rest_framework import permissions, viewsets

from .context import current_user


class CapabilityPermission(permissions.BasePermission):
    """Deny-by-default role-based access control.

    * Staff need the capability mapped to the view action in ``view.capabilities``
      (``"*"`` is the fallback key).
    * Riders and drivers may only call actions listed in ``view.rider_actions`` /
      ``view.driver_actions``; ``EndUserScopedMixin`` limits them to their own records.

    An action with no mapping is refused for everybody.
    """

    message = "Your role does not allow this action."

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not (user and user.is_authenticated and user.is_active):
            return False
        action = getattr(view, "action", None) or request.method.lower()
        if user.is_rider:
            return action in getattr(view, "rider_actions", ())
        if user.is_driver:
            return action in getattr(view, "driver_actions", ())
        capabilities = getattr(view, "capabilities", {})
        required = capabilities.get(action, capabilities.get("*"))
        return required is not None and user.has_capability(required)


class ContextBindingMixin:
    """Publishes the DRF-authenticated user (JWT or session) to the audit context."""

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        current_user.set(request.user)


class EndUserScopedMixin:
    """Restricts querysets to the requesting rider's or driver's own records.

    ``rider_lookup`` / ``driver_lookup`` are ORM paths from the model to the rider or driver
    profile. ``None`` means that kind of user sees nothing.
    """

    rider_lookup: str | None = None
    driver_lookup: str | None = None

    def scope_queryset(self, queryset):
        user = self.request.user
        if user.is_rider:
            profile = getattr(user, "rider_profile", None)
            if profile is None or self.rider_lookup is None:
                return queryset.none()
            return queryset.filter(**{self.rider_lookup: profile})
        if user.is_driver:
            profile = getattr(user, "driver_profile", None)
            if profile is None or self.driver_lookup is None:
                return queryset.none()
            return queryset.filter(**{self.driver_lookup: profile})
        return queryset


class BaseViewSet(ContextBindingMixin, EndUserScopedMixin, viewsets.GenericViewSet):
    permission_classes = [CapabilityPermission]
    capabilities: dict[str, str] = {}
    rider_actions: tuple[str, ...] = ()
    driver_actions: tuple[str, ...] = ()

    def get_queryset(self):
        return self.scope_queryset(super().get_queryset())
