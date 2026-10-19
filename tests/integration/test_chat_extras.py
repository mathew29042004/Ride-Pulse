"""Chat extras: sharing files (type and size checked; members only), typing notices, search
across your own conversations only, and team threads on support tickets."""

from datetime import date
from unittest import mock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounts.models import Role, StaffProfile
from apps.chat import services
from apps.core.exceptions import ActionNotPermitted, BusinessRuleViolation

from ..conftest import make_staff

pytestmark = pytest.mark.django_db

_ids = iter(range(1, 10_000))


@pytest.fixture(autouse=True)
def _media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


def hire(role, department="SUPPORT"):
    user = make_staff(role)
    StaffProfile.objects.create(
        user=user,
        employee_id=f"X{next(_ids):05d}",
        title=role.title(),
        department=department,
        state="Kerala",
        joined_on=date(2025, 1, 1),
    )
    return user


def test_files_typing_and_search(api):
    a, b, outsider = hire(Role.SUPPORT_AGENT), hire(Role.SUPPORT_AGENT), hire(Role.SUPPORT_AGENT)
    dm = services.open_direct(a, b.pk)
    with pytest.raises(BusinessRuleViolation, match="Share images"):
        services.send(dm, a, "", upload=SimpleUploadedFile("run.exe", b"MZ"))
    big = SimpleUploadedFile("big.pdf", b"x" * (services.MAX_FILE + 1))
    with pytest.raises(BusinessRuleViolation, match="10 MB"):
        services.send(dm, a, "", upload=big)

    client = api(a)
    sent = client.post(
        f"/api/v1/chat/{dm.pk}/upload/",
        {"file": SimpleUploadedFile("refund-policy.pdf", b"%PDF-1.4 hello"), "body": "the policy"},
        format="multipart",
    )
    assert sent.status_code == 201 and sent.json()["file"]["name"] == "refund-policy.pdf"
    url = sent.json()["file"]["url"]
    assert b"".join(api(b).get(url).streaming_content) == b"%PDF-1.4 hello"
    assert api(outsider).get(url).status_code == 403

    with mock.patch("apps.realtime.broadcast.user_event") as event:
        assert client.post(f"/api/v1/chat/{dm.pk}/typing/").status_code == 204
    event.assert_called_once()
    assert event.call_args.args[0] == b.pk and event.call_args.args[1] == "chat.typing"

    services.send(dm, b, "Refund approved for the Kochi airport trip")
    found = api(b).get("/api/v1/chat/search/?q=refund").json()
    assert {m["body"] for m in found} >= {
        "Refund approved for the Kochi airport trip",
        "the policy",
    }
    assert api(outsider).get("/api/v1/chat/search/?q=refund").json() == []


def test_ticket_threads_for_support_staff_only(api, rider):
    from apps.support import services as support

    agent, lead = hire(Role.SUPPORT_AGENT), hire(Role.SUPPORT_LEAD)
    ticket = support.open_ticket(
        user=rider.user,
        category="PAYMENT",
        subject="Charged twice",
        description="Charged twice for one ride.",
    )
    made = api(lead).post("/api/v1/chat/thread/", {"ticket_id": ticket.pk}, format="json")
    assert made.status_code == 200
    again = services.thread_for(agent, ticket_id=ticket.pk)
    assert again.pk == made.json()["id"] and again.kind == "TICKET"
    fleet = hire(Role.FLEET_EXECUTIVE, "FLEET")
    assert not fleet.has_capability("support.view")
    with pytest.raises(ActionNotPermitted):
        services.thread_for(fleet, ticket_id=ticket.pk)
