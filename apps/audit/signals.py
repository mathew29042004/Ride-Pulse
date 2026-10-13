from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .mixins import AuditedModel
from .models import AuditAction
from .services import log_event


@receiver(post_save, dispatch_uid="audit_post_save")
def audit_post_save(sender, instance, created, raw=False, **kwargs):
    if raw or not isinstance(instance, AuditedModel):
        return
    changes = instance.audit_changes(created=created)
    if created or changes:
        log_event(AuditAction.CREATE if created else AuditAction.UPDATE, instance, changes=changes)
    instance.refresh_audit_snapshot()


@receiver(post_delete, dispatch_uid="audit_post_delete")
def audit_post_delete(sender, instance, **kwargs):
    if isinstance(instance, AuditedModel):
        log_event(AuditAction.DELETE, instance)
