import re

from django.core.validators import RegexValidator

REGISTRATION_PATTERN = r"^(?:[A-Z]{2}\d{1,2}[A-Z]{0,3}\d{1,4}|\d{2}BH\d{4}[A-Z]{1,2})$"

registration_validator = RegexValidator(
    REGISTRATION_PATTERN, "Enter a valid Indian registration number, e.g. TN37AB1234."
)
phone_validator = RegexValidator(r"^\+?\d{10,13}$", "Enter a valid phone number.")


def normalize_registration(value: str) -> str:
    return re.sub(r"[\s\-]", "", value or "").upper()


def format_registration(value: str) -> str:
    """TN37AB1234 -> TN 37 AB 1234."""
    match = re.match(r"^([A-Z]{2})(\d{1,2})([A-Z]{0,3})(\d{1,4})$", value or "")
    return " ".join(p for p in match.groups() if p) if match else value
