"""NPS: asked after enough trips, not again for 90 days (30 after 'not now'); the score is
promoters minus detractors; comment themes come from keyword rules."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import Role
from apps.riders.models import RiderProfile
from apps.trust import nps

from ..conftest import make_rider, make_staff

pytestmark = pytest.mark.django_db


def test_asking_answering_and_the_report(api):
    rider = make_rider()
    client = api(rider.user)
    assert client.get("/api/v1/nps/prompt/").json()["ask"] is False  # not enough trips yet
    RiderProfile.objects.filter(pk=rider.pk).update(completed_trips=5)
    assert client.get("/api/v1/nps/prompt/").json()["ask"] is True
    client.post("/api/v1/nps/snooze/")
    assert client.get("/api/v1/nps/prompt/").json()["ask"] is False
    assert nps.should_ask(rider.user, now=timezone.now() + timedelta(days=31))
    assert client.post("/api/v1/nps/answer/", {"score": 11}).status_code == 400
    client.post(
        "/api/v1/nps/answer/", {"score": 3, "comment": "Too expensive and the driver was rude"}
    )
    assert not nps.should_ask(rider.user, now=timezone.now() + timedelta(days=60))

    for score in (10, 9, 9, 8, 2):
        other = make_rider()
        RiderProfile.objects.filter(pk=other.pk).update(completed_trips=5)
        nps.answer(other.user, score=score, comment="Waited a long time" if score < 5 else "")
    report = api(make_staff(Role.OPS_MANAGER)).get("/api/v1/nps/report/").json()["RIDER"]
    # 6 answers: promoters 3 (10, 9, 9), detractors 2 (3, 2) → (3 − 2) / 6 = +17
    assert report["responses"] == 6 and report["nps"] == 17
    themes = {t["theme"] for t in report["detractor_themes"]}
    assert {"Price", "Driver behaviour", "Waiting time"} <= themes


def test_themes_match_whole_words():
    from apps.trust.nps import themes

    found = {t["theme"] for t in themes(["App crashed twice"])}
    assert found == {"App"}  # "crashed" isn't "rash" driving
