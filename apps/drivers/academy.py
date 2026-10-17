"""Driver Academy: take a course, pass its quiz (80%), get a certificate. The induction course
records the training the Aggregator Guidelines require before the first ride (refreshed every
year); the accessibility course makes a driver "assist trained"."""

from datetime import date, timedelta

from django.db import models
from django.utils import timezone

from apps.core.exceptions import BusinessRuleViolation

from .academy_content import COURSES

PASS_PERCENT = 80


class CourseResult(models.Model):
    driver = models.ForeignKey(
        "drivers.DriverProfile", on_delete=models.CASCADE, related_name="course_results"
    )
    course = models.SlugField(max_length=40)
    score = models.PositiveSmallIntegerField()  # percent
    passed = models.BooleanField()
    taken_at = models.DateTimeField()

    class Meta:
        app_label = "drivers"
        ordering = ["-taken_at"]
        indexes = [models.Index(fields=["driver", "course"], name="academy_driver_course")]

    def __str__(self) -> str:
        return f"{self.driver_id} {self.course} {self.score}%"


def _course(slug: str):
    if slug not in COURSES:
        raise BusinessRuleViolation("No such course.")
    return COURSES[slug]


def public(slug: str) -> dict:
    """The course without the answers."""
    title, minutes, required, _, lessons, quiz = _course(slug)
    return {
        "slug": slug,
        "title": title,
        "minutes": minutes,
        "required": required,
        "lessons": [{"title": t, "body": b} for t, b in lessons],
        "questions": [{"question": q, "options": o} for q, o, _ in quiz],
    }


def catalogue(driver) -> list[dict]:
    best = {}
    for result in CourseResult.objects.filter(driver=driver, passed=True).order_by("taken_at"):
        best[result.course] = result
    rows = []
    for slug, (title, minutes, required, _, lessons, quiz) in COURSES.items():
        passed = best.get(slug)
        due = slug == "induction" and (
            driver.induction_trained_on is None
            or driver.induction_trained_on < timezone.localdate() - timedelta(days=365)
        )
        rows.append(
            {
                "slug": slug,
                "title": title,
                "minutes": minutes,
                "required": required,
                "lessons": len(lessons),
                "questions": len(quiz),
                "passed_on": passed.taken_at.date().isoformat() if passed else None,
                "score": passed.score if passed else None,
                "due": due,
            }
        )
    return rows


def submit(driver, slug: str, answers: list[int], *, now=None) -> dict:
    now = now or timezone.now()
    _, _, _, effect, _, quiz = _course(slug)
    if len(answers) != len(quiz):
        raise BusinessRuleViolation("Answer every question.", field="answers")
    right = sum(1 for (_, _, correct), given in zip(quiz, answers, strict=True) if given == correct)
    score = round(100 * right / len(quiz))
    passed = score >= PASS_PERCENT
    CourseResult.objects.create(
        driver=driver, course=slug, score=score, passed=passed, taken_at=now
    )
    if passed and effect:
        from .models import DriverProfile

        today: date = timezone.localdate(now)
        field = {"induction": {"induction_trained_on": today}, "assist": {"assist_trained": True}}
        DriverProfile.objects.filter(pk=driver.pk).update(**field[effect])
    wrong = [
        {"question": q, "answer": o[c]}
        for (q, o, c), given in zip(quiz, answers, strict=True)
        if given != c
    ]
    return {"score": score, "passed": passed, "pass_percent": PASS_PERCENT, "review": wrong}


def stats() -> dict:
    """For ops: completions per course."""
    from django.db.models import Count

    rows = dict(
        CourseResult.objects.filter(passed=True)
        .values("course")
        .annotate(n=Count("driver", distinct=True))
        .values_list("course", "n")
    )
    return {
        slug: {"title": c[0], "drivers_passed": rows.get(slug, 0)} for slug, c in COURSES.items()
    }
