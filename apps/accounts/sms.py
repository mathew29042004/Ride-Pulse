"""Sending SMS (login codes). ``SMS_BACKEND`` picks the provider:

* ``console`` (default): log the message. In DEBUG the login code is also returned to the
  app so the demo works without an SMS account.
* ``twilio``: Twilio Messages API (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM).
* ``msg91``: MSG91 Flow API, India's common choice for DLT-registered OTP templates
  (MSG91_AUTH_KEY, MSG91_TEMPLATE_ID; the template has an ``##otp##`` variable).
"""

import base64
import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)
TIMEOUT_SECONDS = 8


class SMSError(Exception):
    pass


def backend() -> str:
    return getattr(settings, "SMS_BACKEND", "console")


def _send(request: urllib.request.Request) -> None:
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS):
            return
    except urllib.error.HTTPError as exc:
        raise SMSError(f"SMS provider rejected the message ({exc.code})") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise SMSError(f"Couldn't reach the SMS provider: {exc}") from exc


def send_text(phone: str, message: str) -> None:
    """A plain message (trip links for trusted contacts). MSG91 only sends DLT-approved
    templates, so with that backend these are logged rather than sent."""
    if backend() == "twilio":
        sid = settings.TWILIO_ACCOUNT_SID
        auth = base64.b64encode(f"{sid}:{settings.TWILIO_AUTH_TOKEN}".encode()).decode()
        body = urllib.parse.urlencode(
            {"To": f"+91{phone}", "From": settings.TWILIO_FROM, "Body": message}
        ).encode()
        _send(
            urllib.request.Request(
                f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
                data=body,
                headers={"Authorization": f"Basic {auth}"},
                method="POST",
            )
        )
    else:
        logger.warning("SMS to +91%s: %s", phone, message)


def send_login_code(phone: str, code: str) -> None:
    """Send a login code to a 10-digit Indian mobile number."""
    kind = backend()
    if kind == "twilio":
        sid = settings.TWILIO_ACCOUNT_SID
        auth = base64.b64encode(f"{sid}:{settings.TWILIO_AUTH_TOKEN}".encode()).decode()
        body = urllib.parse.urlencode(
            {
                "To": f"+91{phone}",
                "From": settings.TWILIO_FROM,
                "Body": f"{code} is your Ride Pulse login code. It expires in 5 minutes.",
            }
        ).encode()
        _send(
            urllib.request.Request(
                f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
                data=body,
                headers={"Authorization": f"Basic {auth}"},
                method="POST",
            )
        )
    elif kind == "msg91":
        _send(
            urllib.request.Request(
                "https://control.msg91.com/api/v5/flow/",
                data=json.dumps(
                    {
                        "template_id": settings.MSG91_TEMPLATE_ID,
                        "short_url": "0",
                        "recipients": [{"mobiles": f"91{phone}", "otp": code}],
                    }
                ).encode(),
                headers={"authkey": settings.MSG91_AUTH_KEY, "Content-Type": "application/json"},
                method="POST",
            )
        )
    else:
        # Never log the code itself outside development.
        shown = code if settings.DEBUG else "******"
        logger.warning("SMS to +91%s: login code %s", phone, shown)
