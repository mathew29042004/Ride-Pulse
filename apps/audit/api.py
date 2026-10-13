import django_filters
from rest_framework import mixins, serializers

from apps.accounts.roles import Cap
from apps.core.api import BaseViewSet

from .models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    actor_email = serializers.EmailField(source="actor.email", default=None, read_only=True)

    class Meta:
        model = AuditLog
        fields = [
            "id",
            "created_at",
            "actor",
            "actor_email",
            "action",
            "entity_type",
            "entity_id",
            "entity_label",
            "message",
            "changes",
            "ip_address",
            "request_id",
        ]


class AuditLogFilter(django_filters.FilterSet):
    since = django_filters.IsoDateTimeFilter(field_name="created_at", lookup_expr="gte")
    until = django_filters.IsoDateTimeFilter(field_name="created_at", lookup_expr="lt")

    class Meta:
        model = AuditLog
        fields = ["action", "entity_type", "entity_id", "actor"]


class AuditLogViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, BaseViewSet):
    """Read-only, append-only audit trail of every change in the system."""

    queryset = AuditLog.objects.select_related("actor")
    serializer_class = AuditLogSerializer
    filterset_class = AuditLogFilter
    search_fields = ["entity_label", "message", "request_id"]
    ordering_fields = ["created_at"]
    capabilities = {"*": Cap.AUDIT_VIEW}
