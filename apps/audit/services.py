from django.db import models

from apps.core.context import current_ip, current_request_id, get_current_user

from .mixins import json_safe
from .models import AuditAction, AuditLog


def entity_type_of(instance: models.Model) -> str:
    return f"{instance._meta.app_label}.{instance._meta.model_name}"


def log_event(
    action: str,
    instance: models.Model,
    *,
    message: str = "",
    changes: dict | None = None,
    actor=None,
) -> AuditLog:
    request_id = current_request_id.get()
    return AuditLog.objects.create(
        actor=actor or get_current_user(),
        action=action,
        entity_type=entity_type_of(instance),
        entity_id=str(instance.pk),
        entity_label=str(instance)[:200],
        message=message[:255],
        changes=json_safe(changes or {}),
        ip_address=current_ip.get(),
        request_id="" if request_id == "-" else request_id,
    )


def log_transition(instance, from_status: str, to_status: str, *, actor=None, note: str = ""):
    return log_event(
        AuditAction.TRANSITION,
        instance,
        message=note or f"{from_status} → {to_status}",
        changes={"status": [from_status, to_status]},
        actor=actor,
    )


def history_for(instance: models.Model):
    return AuditLog.objects.filter(
        entity_type=entity_type_of(instance), entity_id=str(instance.pk)
    ).select_related("actor")
