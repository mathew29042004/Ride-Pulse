"""Razorpay (India's most common payment gateway) for wallet top-ups, in test or live mode.

Flow (Razorpay Standard Checkout):

1. The server creates an *order* for the amount (``create_order``); money can only be paid
   against an order, so the client can't change the amount.
2. The browser opens Razorpay Checkout with the order id; the rider pays by UPI, card, etc.
3. Checkout returns ``payment_id`` + ``signature``. The server recomputes the signature,
   HMAC-SHA256(order_id + "|" + payment_id, key_secret), before crediting anything.
4. A webhook (``payment.captured``) credits the wallet too, in case the browser closed before
   step 3. Both paths are idempotent, so the wallet is credited exactly once.

Enabled only when ``RAZORPAY_KEY_ID`` and ``RAZORPAY_KEY_SECRET`` are set; otherwise top-ups
use the built-in simulated gateway.
"""

import base64
import hashlib
import hmac
import json
import urllib.error
import urllib.request
from decimal import Decimal

from django.conf import settings

API = "https://api.razorpay.com/v1"
TIMEOUT_SECONDS = 8


class RazorpayError(Exception):
    pass


def enabled() -> bool:
    return bool(settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET)


def key_id() -> str:
    return settings.RAZORPAY_KEY_ID if enabled() else ""


def _post(path: str, body: dict) -> dict:
    auth = base64.b64encode(
        f"{settings.RAZORPAY_KEY_ID}:{settings.RAZORPAY_KEY_SECRET}".encode()
    ).decode()
    request = urllib.request.Request(
        f"{API}{path}",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        raise RazorpayError(f"Razorpay rejected the request ({exc.code}): {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RazorpayError(f"Couldn't reach Razorpay: {exc}") from exc


def create_order(amount: Decimal, *, receipt: str, notes: dict | None = None) -> str:
    """Create an order for ``amount`` rupees and return its id (``order_...``)."""
    order = _post(
        "/orders",
        {
            "amount": int((amount * 100).to_integral_value()),  # paise
            "currency": "INR",
            "receipt": receipt[:40],
            "notes": notes or {},
        },
    )
    return order["id"]


def _sign(message: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def payment_signature_valid(order_id: str, payment_id: str, signature: str) -> bool:
    expected = _sign(f"{order_id}|{payment_id}".encode(), settings.RAZORPAY_KEY_SECRET)
    return bool(signature) and hmac.compare_digest(expected, signature)


def webhook_signature_valid(body: bytes, signature: str) -> bool:
    secret = settings.RAZORPAY_WEBHOOK_SECRET
    return bool(secret and signature) and hmac.compare_digest(_sign(body, secret), signature)
