"""Announcements: written once, read in each person's language, targeted by state or city
(riders by where they've ridden), with read rates; only managers can publish."""

import pytest

from apps.accounts.models import Role
from apps.announcements import services
from apps.announcements.models import Announcement

from ..conftest import make_rider, make_staff
from .helpers import book, drive_to_completion

pytestmark = pytest.mark.django_db

TEXT = {
    "en": {"title": "Heavy rain tomorrow", "body": "Drive slowly near flooded underpasses."},
    "ta": {"title": "நாளை கனமழை", "body": "வெள்ளம் உள்ள சுரங்கப்பாதைகளில் மெதுவாக ஓட்டுங்கள்."},
}


def test_drivers_in_the_state_read_it_in_their_language(api, make_driver, now):
    tamil = make_driver(now=now)
    tamil.user.language = "ta"
    tamil.user.save(update_fields=["language"])
    english = make_driver(now=now)
    manager = make_staff(Role.OPS_MANAGER)
    response = api(manager).post(
        "/api/v1/announcements/",
        {"audience": "DRIVERS", "state": "Tamil Nadu", "text": TEXT, "important": True},
        format="json",
    )
    assert response.status_code == 201 and response.json()["recipients"] == 2
    mine = api(tamil.user).get("/api/v1/announcements/mine/").json()
    assert mine[0]["title"] == "நாளை கனமழை" and not mine[0]["read"]
    assert (
        api(english.user).get("/api/v1/announcements/mine/").json()[0]["title"]
        == TEXT["en"]["title"]
    )
    api(tamil.user).post(f"/api/v1/announcements/{mine[0]['id']}/read/")
    report = api(manager).get("/api/v1/announcements/").json()[0]
    assert report["read"] == 1 and report["read_rate"] == 0.5
    assert api(make_staff(Role.SUPPORT_AGENT)).post("/api/v1/announcements/", {}).status_code == 403


def test_riders_are_reached_by_where_they_ride(mini, make_driver, now, chennai):
    make_driver(now=now)
    local, elsewhere = make_rider(), make_rider()
    drive_to_completion(book(local, mini, now=now), now=now)
    announcement = services.publish(
        user=make_staff(Role.OPS_MANAGER), audience="RIDERS", city=chennai, text={"en": TEXT["en"]}
    )
    assert announcement.recipients == 1
    assert services.inbox(local.user) and not services.inbox(elsewhere.user)
    with pytest.raises(Exception, match="English"):
        services.publish(user=None, audience="RIDERS", text={"ta": TEXT["ta"]})
    assert Announcement.objects.count() == 1
