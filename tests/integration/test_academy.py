"""Driver Academy: passing the induction quiz is what lets a new driver go online; the
accessibility course makes them assist-trained; a fail records the score and shows what to review."""

import pytest

from apps.core.exceptions import BusinessRuleViolation
from apps.drivers import academy
from apps.drivers import services as drivers
from apps.drivers.academy_content import COURSES
from apps.drivers.models import DriverProfile

from ..conftest import T_NAGAR

pytestmark = pytest.mark.django_db


def right_answers(slug):
    return [correct for _, _, correct in COURSES[slug][5]]


def test_induction_unlocks_going_online(api, make_driver, now):
    driver = make_driver(now=now, online=False)
    DriverProfile.objects.filter(pk=driver.pk).update(induction_trained_on=None)
    driver.refresh_from_db()
    with pytest.raises(BusinessRuleViolation, match="induction"):
        drivers.go_online(driver, lat=T_NAGAR[0], lng=T_NAGAR[1], now=now)
    client = api(driver.user)
    listing = client.get("/api/v1/driver/academy/").json()
    assert next(c for c in listing if c["slug"] == "induction")["due"]
    course = client.get("/api/v1/driver/academy/induction/").json()
    assert course["lessons"] and "correct" not in str(course)  # no answers sent to the app
    wrong = [0] * len(course["questions"])
    failed = client.post(
        "/api/v1/driver/academy/induction/submit/", {"answers": wrong}, format="json"
    ).json()
    assert not failed["passed"] and failed["review"]
    passed = client.post(
        "/api/v1/driver/academy/induction/submit/",
        {"answers": right_answers("induction")},
        format="json",
    ).json()
    assert passed["passed"] and passed["score"] == 100
    driver.refresh_from_db()
    drivers.go_online(driver, lat=T_NAGAR[0], lng=T_NAGAR[1], now=now)


def test_accessibility_course_makes_a_driver_assist_trained(make_driver, now):
    driver = make_driver(now=now, online=False)
    assert not driver.assist_trained
    academy.submit(driver, "accessibility", right_answers("accessibility"))
    driver.refresh_from_db()
    assert driver.assist_trained
    with pytest.raises(BusinessRuleViolation, match="every question"):
        academy.submit(driver, "first-aid", [1])
