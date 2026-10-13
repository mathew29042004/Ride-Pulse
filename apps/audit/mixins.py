import json

from django.core.serializers.json import DjangoJSONEncoder
from django.db import models


def json_safe(value):
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder))


class AuditedModel(models.Model):
    """Records field-level diffs of every save to the audit trail.

    The values loaded from the database are snapshotted in ``from_db`` and compared on save, so
    no extra query is needed to compute what changed.
    """

    audit_exclude: tuple[str, ...] = ("created_at", "updated_at")

    class Meta:
        abstract = True

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        instance._audit_snapshot = dict(zip(field_names, values, strict=True))
        return instance

    def _audited_fields(self):
        return [f for f in self._meta.concrete_fields if f.name not in self.audit_exclude]

    def audit_changes(self, *, created: bool) -> dict:
        snapshot = getattr(self, "_audit_snapshot", None)
        deferred = self.get_deferred_fields()
        changes = {}
        for field in self._audited_fields():
            if field.attname in deferred:  # reading it would cost a query; it can't have changed
                continue
            new = getattr(self, field.attname)
            if created or snapshot is None:
                if new not in (None, "", [], {}):
                    changes[field.name] = [None, json_safe(new)]
            elif field.attname in snapshot and snapshot[field.attname] != new:
                changes[field.name] = [json_safe(snapshot[field.attname]), json_safe(new)]
        return changes

    def refresh_audit_snapshot(self) -> None:
        deferred = self.get_deferred_fields()
        self._audit_snapshot = {
            f.attname: getattr(self, f.attname)
            for f in self._audited_fields()
            if f.attname not in deferred
        }
