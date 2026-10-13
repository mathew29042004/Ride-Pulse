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


def normalize_indian_mobile(value: str) -> str:
    """'+91 98765-43210', '098765 43210' or '9876543210' -> '9876543210'.

    Raises ValueError unless it's a valid Indian mobile number (10 digits starting 6-9).
    """
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if not re.fullmatch(r"[6-9]\d{9}", digits):
        raise ValueError("Enter a valid 10-digit Indian mobile number.")
    return digits
