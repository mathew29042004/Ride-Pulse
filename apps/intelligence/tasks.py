from celery import shared_task

from . import alerts, briefing, demand, fraud


@shared_task(name="intelligence.check_alerts")
def check_alerts() -> dict:
    return alerts.check()


@shared_task(name="intelligence.morning_briefing")
def morning_briefing() -> str:
    return str(briefing.generate().day)


@shared_task(name="intelligence.nudge_drivers")
def nudge_drivers() -> int:
    return demand.nudge_drivers()


@shared_task(name="intelligence.fraud_scan")
def fraud_scan() -> dict:
    return fraud.scan()
