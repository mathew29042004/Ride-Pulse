from celery import shared_task

from . import alerts, briefing, context, demand, fraud


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


@shared_task(name="intelligence.refresh_weather")
def refresh_weather() -> dict:
    return context.refresh_weather()


@shared_task(name="intelligence.refresh_forecast_accuracy")
def refresh_forecast_accuracy() -> dict:
    """Keep the platform-wide forecast accuracy (and method choice) fresh."""
    return demand.refresh_accuracy(None)
