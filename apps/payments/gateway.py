"""A deterministic stand-in for a real payment gateway (Razorpay, Stripe, ...).

Any payer reference containing "fail" (e.g. ``fail@upi``) is declined, which lets tests and the
demo exercise the failure path on purpose.
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal

MAX_SINGLE_CHARGE = Decimal(100_000)


@dataclass(frozen=True)
class GatewayResult:
    succeeded: bool
    reference: str = ""
    failure_reason: str = ""


def charge(amount: Decimal, *, method: str, payer_reference: str = "") -> GatewayResult:
    if "fail" in payer_reference.lower():
        return GatewayResult(False, failure_reason="Declined by the issuing bank.")
    if amount > MAX_SINGLE_CHARGE:
        return GatewayResult(False, failure_reason="Amount exceeds the per-transaction limit.")
    return GatewayResult(True, reference=f"{method.lower()}_{uuid.uuid4().hex[:18]}")
