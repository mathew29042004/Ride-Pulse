"""Two-step sign-in for staff: RFC 6238 codes, set-up with recovery codes, the sign-in
challenge, no code reuse, and wrong codes counting towards the lockout."""

import time

import pytest

from apps.accounts import two_factor
from apps.accounts.models import Role

from ..conftest import make_rider, make_staff

pytestmark = pytest.mark.django_db

PASSWORD = "pw-12345!"


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    from django.core.cache import cache

    cache.clear()  # sign-in rate limits are per IP: start each test with a clean slate


def test_codes_match_the_rfc_6238_example():
    # RFC 6238 appendix B: ASCII "12345678901234567890", T = 59 s → 94287082 (8 digits; 6 → 287082).
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    assert two_factor.code_at(secret, 59) == "287082"
    assert two_factor.code_at(secret, 1111111109) == "081804"


def _sign_in(client, email):
    return client.post("/api/v1/auth/token/", {"email": email, "password": PASSWORD}).json()


def test_set_up_then_sign_in_with_a_code(api):
    manager = make_staff(Role.OPS_MANAGER)
    client = api(manager)
    assert client.get("/api/v1/auth/2fa/").json() == {
        "enabled": False,
        "required": True,
        "recovery_codes_left": 0,
    }
    secret = client.post("/api/v1/auth/2fa/").json()["secret"]
    bad = client.post("/api/v1/auth/2fa/enable/", {"code": "000000"})
    assert bad.status_code == 422
    now = time.time()
    enabled = client.post("/api/v1/auth/2fa/enable/", {"code": two_factor.code_at(secret, now)})
    recovery = enabled.json()["recovery_codes"]
    assert len(recovery) == 10 and enabled.json()["enabled"]

    anonymous = api(None)
    first = _sign_in(anonymous, manager.email)
    assert first["two_factor_required"] and "access" not in first
    # The code that turned it on can't be used again (same 30 s step).
    reused = anonymous.post(
        "/api/v1/auth/2fa/verify/",
        {"challenge": first["challenge"], "code": two_factor.code_at(secret, now)},
    )
    assert reused.status_code == 400
    ok = anonymous.post(
        "/api/v1/auth/2fa/verify/",
        {"challenge": first["challenge"], "code": recovery[0]},
    )
    assert ok.status_code == 200 and ok.json()["access"]
    again = anonymous.post(
        "/api/v1/auth/2fa/verify/", {"challenge": first["challenge"], "code": recovery[0]}
    )
    assert again.status_code == 400  # a recovery code works once
    assert two_factor.status(manager)["recovery_codes_left"] == 9


def test_wrong_codes_lock_the_account_and_riders_are_unaffected(api):
    agent = make_staff(Role.SUPPORT_AGENT)
    two_factor.begin(agent)
    secret = two_factor.TwoFactor.objects.get(user=agent).secret
    two_factor.enable(agent, two_factor.code_at(secret))
    anonymous = api(None)
    challenge = _sign_in(anonymous, agent.email)["challenge"]
    codes = [
        anonymous.post("/api/v1/auth/2fa/verify/", {"challenge": challenge, "code": "123456"})
        for _ in range(5)
    ]
    # Locked after five wrong tries (the app answers lockouts with 429, like a rate limit).
    assert codes[-1].status_code == 429 and "locked" in str(codes[-1].json()).lower()
    rider = make_rider()
    assert "access" in _sign_in(anonymous, rider.user.email)  # one step for riders
    with pytest.raises(Exception, match="staff"):
        two_factor.begin(rider.user)
