"""Typed access to the ``RIDE_PULSE`` business settings."""

from decimal import Decimal

from django.conf import settings


def _value(key: str):
    return settings.RIDE_PULSE[key]


def _decimal(key: str) -> Decimal:
    return Decimal(str(_value(key)))


def company_name() -> str:
    return _value("COMPANY_NAME")


def company_gstin() -> str:
    return _value("COMPANY_GSTIN")


def company_address() -> str:
    return _value("COMPANY_ADDRESS")


def support_email() -> str:
    return _value("SUPPORT_EMAIL")


def currency_symbol() -> str:
    return _value("CURRENCY_SYMBOL")


def gst_rate() -> Decimal:
    return _decimal("GST_RATE")


def platform_commission_percent() -> Decimal:
    return _decimal("PLATFORM_COMMISSION_PERCENT")


def dispatch_mode() -> str:
    return str(_value("DISPATCH_MODE")).upper()


def dispatch_radius_km() -> Decimal:
    return _decimal("DISPATCH_RADIUS_KM")


def dispatch_max_radius_km() -> Decimal:
    return _decimal("DISPATCH_MAX_RADIUS_KM")


def offer_timeout_seconds() -> int:
    return int(_value("OFFER_TIMEOUT_SECONDS"))


def request_timeout_seconds() -> int:
    return int(_value("REQUEST_TIMEOUT_SECONDS"))


def location_stale_seconds() -> int:
    return int(_value("LOCATION_STALE_SECONDS"))


def arrival_radius_meters() -> int:
    return int(_value("ARRIVAL_RADIUS_METERS"))


def free_cancellation_seconds() -> int:
    return int(_value("FREE_CANCELLATION_SECONDS"))


def max_driver_dues() -> Decimal:
    return _decimal("MAX_DRIVER_DUES")


def road_distance_factor() -> Decimal:
    return _decimal("ROAD_DISTANCE_FACTOR")


def surge_max_multiplier() -> Decimal:
    return _decimal("SURGE_MAX_MULTIPLIER")


def surge_window_minutes() -> int:
    return int(_value("SURGE_WINDOW_MINUTES"))


def surge_smoothing() -> Decimal:
    return _decimal("SURGE_SMOOTHING")


def upfront_distance_tolerance() -> Decimal:
    return _decimal("UPFRONT_DISTANCE_TOLERANCE")


def upfront_duration_tolerance() -> Decimal:
    return _decimal("UPFRONT_DURATION_TOLERANCE")


def payout_minimum() -> Decimal:
    return _decimal("PAYOUT_MINIMUM")


def referral_bonus() -> Decimal:
    return _decimal("REFERRAL_BONUS")


def driver_goals() -> list[tuple[int, Decimal]]:
    return [(int(trips), Decimal(bonus)) for trips, bonus in _value("DRIVER_GOALS")]


def going_home_rules() -> tuple[int, int]:
    """(uses per day, minutes per use)."""
    return int(_value("GOING_HOME_PER_DAY")), int(_value("GOING_HOME_MINUTES"))


def ride_pass_terms() -> dict:
    return {
        "price": _decimal("RIDE_PASS_PRICE"),
        "days": int(_value("RIDE_PASS_DAYS")),
        "percent": _decimal("RIDE_PASS_PERCENT"),
        "max_discount": _decimal("RIDE_PASS_MAX_DISCOUNT"),
    }


def app_url() -> str:
    return str(_value("APP_URL")).rstrip("/")


def night_safe_hours() -> tuple[int, int]:
    """(start, end) local hours of Night Safe mode, e.g. (22, 6)."""
    start, end = _value("NIGHT_SAFE_HOURS")
    return int(start), int(end)


def ride_check_rules(*, night: bool) -> dict:
    i = 1 if night else 0
    return {
        "stop_minutes": int(_value("RIDE_CHECK_STOP_MINUTES")[i]),
        "off_route_km": float(_value("RIDE_CHECK_OFF_ROUTE_KM")[i]),
        "answer_minutes": int(_value("RIDE_CHECK_ANSWER_MINUTES")),
    }


def fare_offer_rules() -> dict:
    low, high = _value("FARE_OFFER_RANGE")
    return {
        "min_ratio": Decimal(low),
        "max_ratio": Decimal(high),
        "counter_steps": [Decimal(step) for step in _value("COUNTER_STEPS")],
        "counter_valid_seconds": int(_value("COUNTER_VALID_SECONDS")),
    }


def sure_ride_terms() -> dict:
    return {
        "fee": _decimal("SURE_RIDE_FEE"),
        "refund": _decimal("SURE_RIDE_REFUND"),
        "buffer_minutes": int(_value("SURE_RIDE_BUFFER_MINUTES")),
        "min_minutes": int(_value("SURE_RIDE_MIN_MINUTES")),
    }


def rental_terms() -> dict:
    return {
        "packages": [(int(h), int(k)) for h, k in _value("RENTAL_PACKAGES")],
        "rates": {
            code: {key: Decimal(value) for key, value in rates.items()}
            for code, rates in _value("RENTAL_RATES").items()
        },
    }


def intercity_terms() -> dict:
    low, high = _value("INTERCITY_RANGE_KM")
    return {
        "per_km": {code: Decimal(v) for code, v in _value("INTERCITY_PER_KM").items()},
        "min_km_one_way": int(_value("INTERCITY_MIN_KM_ONE_WAY")),
        "min_km_per_day": int(_value("INTERCITY_MIN_KM_PER_DAY")),
        "allowance": _decimal("INTERCITY_DRIVER_ALLOWANCE"),
        "min_km": int(low),
        "max_km": int(high),
    }


def wellbeing_rules() -> dict:
    return {
        "max_minutes": int(_value("WELLBEING_MAX_DRIVING_MINUTES")),
        "break_minutes": int(_value("WELLBEING_BREAK_MINUTES")),
        "warn_minutes": int(_value("WELLBEING_WARN_MINUTES")),
        "bonus_after_minutes": int(_value("WELLBEING_BONUS_AFTER_MINUTES")),
        "rest_bonus": _decimal("WELLBEING_REST_BONUS"),
    }


def running_cost_per_km(ride_type_code: str) -> Decimal:
    return Decimal(str(_value("RUNNING_COST_PER_KM").get(ride_type_code, "6")))


def location_ping_retention_days() -> int:
    return int(_value("LOCATION_PING_RETENTION_DAYS"))


def ticket_sla_hours(priority: str) -> int:
    return int(_value("TICKET_SLA_HOURS")[priority])
