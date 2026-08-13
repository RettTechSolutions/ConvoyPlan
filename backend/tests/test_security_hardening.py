"""Tests for the security-hardening additions: password policy, JWT-secret
fail-closed check, and the in-process auth rate limiter."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import jwt as _jwt
import pytest
from fastapi import HTTPException

from app import main
from app.config import settings
from app.services import rate_limit as rl
from app.services.password import generate_password, validate_password


# ── Password policy ────────────────────────────────────────────────────────────

def test_validate_password_rejects_too_short():
    with pytest.raises(HTTPException) as exc:
        validate_password("Ab1xyz")
    assert exc.value.status_code == 400


def test_validate_password_rejects_no_digit():
    with pytest.raises(HTTPException):
        validate_password("abcdefghijk")  # letters only, >= 10 chars


def test_validate_password_rejects_no_letter():
    with pytest.raises(HTTPException):
        validate_password("1234567890")


def test_validate_password_accepts_compliant():
    validate_password("abcdef1ghij")  # 11 chars, letters + digit


def test_generated_password_satisfies_policy():
    validate_password(generate_password())


# ── JWT secret fail-closed ──────────────────────────────────────────────────────

def test_verify_security_config_rejects_default_in_production(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "jwt_secret", "changeme-in-production")
    with pytest.raises(RuntimeError):
        main._verify_security_config()


def test_verify_security_config_rejects_short_secret(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "jwt_secret", "too-short")
    with pytest.raises(RuntimeError):
        main._verify_security_config()


def test_verify_security_config_accepts_strong_secret(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "jwt_secret", "a" * 40)
    main._verify_security_config()  # must not raise


def test_verify_security_config_relaxed_in_development(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "jwt_secret", "changeme-in-production")
    main._verify_security_config()  # must not raise


# ── Rate limiter ─────────────────────────────────────────────────────────────────

class _Req:
    def __init__(self, ip: str):
        self.headers: dict[str, str] = {}
        self.client = type("C", (), {"host": ip})()


@pytest.mark.asyncio
async def test_rate_limit_blocks_after_threshold(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    rl.reset()
    dep = rl.rate_limit("login", max_attempts=2, window_seconds=60)
    req = _Req("203.0.113.5")

    await dep(req)  # no recorded failures yet → allowed
    rl.register_failure(req, "login")
    rl.register_failure(req, "login")

    with pytest.raises(HTTPException) as exc:
        await dep(req)
    assert exc.value.status_code == 429
    assert "Retry-After" in exc.value.headers


@pytest.mark.asyncio
async def test_rate_limit_isolated_per_ip(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    rl.reset()
    dep = rl.rate_limit("login", max_attempts=1, window_seconds=60)
    bad = _Req("198.51.100.1")
    good = _Req("198.51.100.2")

    rl.register_failure(bad, "login")
    with pytest.raises(HTTPException):
        await dep(bad)
    await dep(good)  # different IP is unaffected


@pytest.mark.asyncio
async def test_rate_limit_count_attempts_mode(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    rl.reset()
    dep = rl.rate_limit("password-reset", max_attempts=2, window_seconds=60, count_attempts=True)
    req = _Req("203.0.113.9")

    await dep(req)
    await dep(req)
    with pytest.raises(HTTPException) as exc:
        await dep(req)
    assert exc.value.status_code == 429


@pytest.mark.asyncio
async def test_rate_limit_disabled_is_noop(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    rl.reset()
    dep = rl.rate_limit("login", max_attempts=1, window_seconds=60)
    req = _Req("203.0.113.10")
    rl.register_failure(req, "login")
    rl.register_failure(req, "login")
    await dep(req)  # disabled → never blocks


def test_client_ip_prefers_forwarded_for():
    """XFF is preferred over the direct connection address (Caddy's Docker IP).
    When Caddy adds a single entry there is exactly one IP in the chain."""
    from app.services.audit import client_ip
    req = _Req("10.0.0.1")       # 10.0.0.1 = Caddy container's Docker IP
    req.headers = {"x-forwarded-for": "1.2.3.4"}   # single entry appended by Caddy
    assert client_ip(req) == "1.2.3.4"


def test_client_ip_reads_rightmost_xff_to_prevent_spoofing():
    """The rightmost XFF entry is used so a client cannot bypass rate limiting
    by injecting a forged leftmost entry before the IP Caddy appends.

    Chain:  X-Forwarded-For: <client-forged>, <real-ip-appended-by-Caddy>
    Only the rightmost (Caddy-controlled) value is trusted."""
    from app.services.audit import client_ip
    req = _Req("10.0.0.1")
    # Attacker sent X-Forwarded-For: 5.5.5.5; Caddy appended the real IP 1.2.3.4
    req.headers = {"x-forwarded-for": "5.5.5.5, 1.2.3.4"}
    assert client_ip(req) == "1.2.3.4"   # Caddy's value, not the forged one


# ── HIBP breach check (T8) ───────────────────────────────────────────────────────

import hashlib  # noqa: E402

from app.services import password as pw  # noqa: E402


class _MockResp:
    def __init__(self, text="", success=True, status_code=200):
        self.text = text
        self.is_success = success
        self.status_code = status_code


class _MockClient:
    def __init__(self, resp=None, exc=None):
        self._resp = resp
        self._exc = exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False

    async def get(self, _url):
        if self._exc:
            raise self._exc
        return self._resp


def _suffix_for(password: str) -> str:
    # Mirrors the HIBP k-anonymity digest in app.services.password; SHA-1 is
    # required by the API and not a security hash (usedforsecurity=False).
    return hashlib.sha1(password.encode(), usedforsecurity=False).hexdigest().upper()[5:]


@pytest.mark.asyncio
async def test_breach_check_rejects_pwned_password(monkeypatch):
    monkeypatch.setattr(settings, "password_breach_check_enabled", True)
    pwd = "password123"
    body = f"{_suffix_for(pwd)}:42\r\nAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA:1"
    monkeypatch.setattr(pw.httpx, "AsyncClient", lambda *a, **k: _MockClient(_MockResp(body)))
    with pytest.raises(HTTPException) as exc:
        await pw.assert_password_not_breached(pwd)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_breach_check_allows_clean_password(monkeypatch):
    monkeypatch.setattr(settings, "password_breach_check_enabled", True)
    body = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA:1\r\nBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB:2"
    monkeypatch.setattr(pw.httpx, "AsyncClient", lambda *a, **k: _MockClient(_MockResp(body)))
    await pw.assert_password_not_breached("a-very-unique-passphrase-9999")  # must not raise


@pytest.mark.asyncio
async def test_breach_check_fails_open_on_network_error(monkeypatch):
    monkeypatch.setattr(settings, "password_breach_check_enabled", True)
    monkeypatch.setattr(pw.httpx, "AsyncClient", lambda *a, **k: _MockClient(exc=RuntimeError("offline")))
    await pw.assert_password_not_breached("password123")  # network down → allowed


@pytest.mark.asyncio
async def test_breach_check_disabled_skips_network(monkeypatch):
    monkeypatch.setattr(settings, "password_breach_check_enabled", False)

    def _boom(*_a, **_k):
        raise AssertionError("network must not be called when disabled")

    monkeypatch.setattr(pw.httpx, "AsyncClient", _boom)
    await pw.assert_password_not_breached("password123")  # disabled → no call


# ── CORS origin resolution (T9) ──────────────────────────────────────────────────

def test_cors_explicit_list(monkeypatch):
    monkeypatch.setattr(settings, "cors_origins", "https://a.example, https://b.example")
    assert main._resolve_cors_origins() == ["https://a.example", "https://b.example"]


def test_cors_production_defaults_to_own_origin(monkeypatch):
    monkeypatch.setattr(settings, "cors_origins", "")
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "app_base_url", "https://convoy.example.de/")
    assert main._resolve_cors_origins() == ["https://convoy.example.de"]


def test_cors_development_allows_wildcard(monkeypatch):
    monkeypatch.setattr(settings, "cors_origins", "")
    monkeypatch.setattr(settings, "app_env", "development")
    assert main._resolve_cors_origins() == ["*"]


def test_cors_explicit_wildcard_allowed(monkeypatch):
    monkeypatch.setattr(settings, "cors_origins", "*")
    monkeypatch.setattr(settings, "app_env", "production")
    assert main._resolve_cors_origins() == ["*"]


# ── MFA secret encryption (T7) ────────────────────────────────────────────────────

from app.services import crypto  # noqa: E402


def test_encrypt_decrypt_roundtrip():
    secret = "JBSWY3DPEHPK3PXP"
    token = crypto.encrypt_secret(secret)
    assert token != secret
    assert crypto.decrypt_secret(token) == secret


def test_decrypt_legacy_plaintext_passthrough():
    # A non-Fernet value is treated as a legacy plaintext secret and returned as-is.
    assert crypto.decrypt_secret("JBSWY3DPEHPK3PXP") == "JBSWY3DPEHPK3PXP"


# ── Token versioning / JWT revocation (T6) ────────────────────────────────────────

from app.api import deps  # noqa: E402
from app.api.routes.auth import (  # noqa: E402
    create_mfa_pending_token,
    create_stream_ticket,
    create_token,
)


def test_token_carries_version_and_parses():
    sub = str(uuid.uuid4())
    td = deps.get_token_data(create_token(sub, False, token_version=7))
    assert td.token_version == 7


# ── MFA-pending token must never grant access (K1) ────────────────────────────────

def test_mfa_pending_token_rejected_as_access_token():
    """A token issued after the password step but before TOTP must NOT be
    accepted by get_token_data / get_current_user (CWE-287 MFA bypass)."""
    pending = create_mfa_pending_token(str(uuid.uuid4()), org_slug="acme")
    with pytest.raises(HTTPException) as exc:
        deps.get_token_data(pending)
    assert exc.value.status_code == 401


def test_access_token_carries_typ_access():
    import jwt as _jwt
    payload = _jwt.decode(
        create_token(str(uuid.uuid4()), False),
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
    )
    assert payload.get("typ") == "access"


def test_legacy_token_without_typ_still_accepted():
    """Tokens issued before the typ claim existed (no typ, no mfa_pending) must
    keep working so the fix does not log every active user out."""
    import jwt as _jwt
    from datetime import datetime, timedelta, timezone

    legacy = _jwt.encode(
        {"sub": str(uuid.uuid4()), "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    td = deps.get_token_data(legacy)  # must not raise
    assert td.token_version == 0


# ── Stream tickets (SSE/WS query-param auth) ──────────────────────────────────────

def test_stream_ticket_rejected_by_regular_api():
    """A stream ticket (typ=stream) must NOT be usable as a normal access token."""
    td = deps.get_token_data(create_token(str(uuid.uuid4()), False, token_version=3))
    ticket = create_stream_ticket(td)
    with pytest.raises(HTTPException) as exc:
        deps.get_token_data(ticket)
    assert exc.value.status_code == 401


def test_stream_ticket_accepted_by_stream_decoder():
    td = deps.get_token_data(create_token(str(uuid.uuid4()), False, token_version=3))
    ticket = create_stream_ticket(td)
    out = deps.decode_stream_token(ticket)
    assert out.user_id == td.user_id
    assert out.token_version == 3


def test_mfa_pending_rejected_by_stream_decoder():
    """The streaming paths (WS/SSE) must also reject mfa_pending tokens (K1)."""
    pending = create_mfa_pending_token(str(uuid.uuid4()))
    with pytest.raises(HTTPException):
        deps.decode_stream_token(pending)


# ── E-mail template SSTI guard (M3) ───────────────────────────────────────────────

from app.services.email import _safe_format  # noqa: E402


def test_safe_format_substitutes_known_keys():
    assert _safe_format("Hallo {name}, code {n}", {"name": "Bob", "n": "7"}) == "Hallo Bob, code 7"


def test_safe_format_leaves_unknown_keys_untouched():
    assert _safe_format("Hi {missing}", {"name": "Bob"}) == "Hi {missing}"


def test_safe_format_blocks_attribute_access():
    """{login_url.__class__...} must be left literal, never evaluated (SSTI)."""
    out = _safe_format("{login_url.__class__.__init__.__globals__}", {"login_url": "http://x"})
    assert out == "{login_url.__class__.__init__.__globals__}"


def test_ensure_token_current_rejects_stale():
    with pytest.raises(HTTPException) as exc:
        deps._ensure_token_current(MagicMock(token_version=1), MagicMock(token_version=2))
    assert exc.value.status_code == 401


def test_ensure_token_current_allows_match():
    deps._ensure_token_current(MagicMock(token_version=3), MagicMock(token_version=3))



def test_verify_security_config_rejects_alg_none(monkeypatch):
    """`alg=none` would disable signature verification entirely, letting anyone
    self-sign is_superadmin — rejected in every environment, dev included."""
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "jwt_algorithm", "none")
    with pytest.raises(RuntimeError):
        main._verify_security_config()


def test_verify_security_config_rejects_asymmetric_alg(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "jwt_secret", "a" * 40)
    monkeypatch.setattr(settings, "jwt_algorithm", "RS256")
    with pytest.raises(RuntimeError):
        main._verify_security_config()


def test_verify_security_config_accepts_hmac_algs(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "jwt_secret", "a" * 40)
    for alg in ("HS256", "HS384", "HS512"):
        monkeypatch.setattr(settings, "jwt_algorithm", alg)
        main._verify_security_config()

# ── CSP / Caddyfile security headers (T4) ─────────────────────────────────────────

from app.services import caddy_config  # noqa: E402
from app.services.caddy_config import generate_caddyfile  # noqa: E402


def test_setup_caddyfile_has_security_headers_report_only():
    cf = generate_caddyfile("convoy.example.de", "auto", "a@b.de")
    assert "Strict-Transport-Security" in cf
    assert "X-Content-Type-Options" in cf
    # Report-Only by default so the CSP can never break the map UI.
    assert "Content-Security-Policy-Report-Only" in cf
    assert "tile.openstreetmap.org" in cf
    assert "wss://convoy.example.de" in cf


def test_setup_caddyfile_csp_enforce_toggle(monkeypatch):
    monkeypatch.setenv("CSP_ENFORCE", "true")
    cf = generate_caddyfile("x.de", "internal", "a@b.de")
    assert "Content-Security-Policy-Report-Only" not in cf
    assert 'Content-Security-Policy "' in cf


def test_generated_caddyfile_passes_the_header_self_check():
    assert caddy_config.has_security_headers(generate_caddyfile("x.de", "auto", "a@b.de"))


def test_has_security_headers_rejects_a_pre_hardening_caddyfile():
    """The config the setup wizard wrote before the header block existed — the
    exact file a long-running install still serves from /certs."""
    legacy = """{
    admin 0.0.0.0:2019
    email a@b.de
}

convoy.example.de {
    handle /api/* {
        reverse_proxy backend:8000
    }
    handle {
        reverse_proxy frontend:3000
    }
}
"""
    assert not caddy_config.has_security_headers(legacy)


@pytest.mark.asyncio
async def test_ensure_security_headers_rewrites_legacy_caddyfile(tmp_path, monkeypatch):
    caddyfile = tmp_path / "Caddyfile"
    caddyfile.write_text("convoy.example.de {\n    reverse_proxy frontend:3000\n}\n")
    monkeypatch.setattr(caddy_config, "CADDYFILE_PATH", caddyfile)
    monkeypatch.setattr(
        caddy_config, "_persisted_setup_values",
        AsyncMock(return_value=("convoy.example.de", "auto", "a@b.de")),
    )
    reload_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(caddy_config, "reload_caddy", reload_mock)

    assert await caddy_config.ensure_security_headers(MagicMock()) is True
    assert caddy_config.has_security_headers(caddyfile.read_text())
    assert "wss://convoy.example.de" in caddyfile.read_text()
    reload_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_ensure_security_headers_leaves_a_current_caddyfile_alone(tmp_path, monkeypatch):
    caddyfile = tmp_path / "Caddyfile"
    caddyfile.write_text(generate_caddyfile("convoy.example.de", "auto", "a@b.de"))
    monkeypatch.setattr(caddy_config, "CADDYFILE_PATH", caddyfile)
    before = caddyfile.read_text()
    reload_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(caddy_config, "reload_caddy", reload_mock)

    assert await caddy_config.ensure_security_headers(MagicMock()) is False
    assert caddyfile.read_text() == before
    reload_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_ensure_security_headers_noop_without_persisted_caddyfile(tmp_path, monkeypatch):
    """Env-var mode: Caddy generates its own (already hardened) config."""
    monkeypatch.setattr(caddy_config, "CADDYFILE_PATH", tmp_path / "absent")
    assert await caddy_config.ensure_security_headers(MagicMock()) is False


@pytest.mark.asyncio
async def test_ensure_security_headers_never_raises(tmp_path, monkeypatch):
    """A broken proxy config must not stop the backend from booting."""
    caddyfile = tmp_path / "Caddyfile"
    caddyfile.write_text("no headers here")
    monkeypatch.setattr(caddy_config, "CADDYFILE_PATH", caddyfile)
    monkeypatch.setattr(
        caddy_config, "_persisted_setup_values", AsyncMock(side_effect=RuntimeError("db down"))
    )
    assert await caddy_config.ensure_security_headers(MagicMock()) is False


# ── Upstream-quota throttles (demo sessions) ──────────────────────────────────

from app.api import quota  # noqa: E402


def _quota_request(ip: str = "203.0.113.7"):
    request = MagicMock()
    request.headers = {"x-forwarded-for": ip}
    return request


def _token(is_demo: bool, user_id: uuid.UUID | None = None) -> deps.TokenData:
    return deps.TokenData(user_id=user_id or uuid.uuid4(), is_demo=is_demo)


@pytest.mark.asyncio
async def test_quota_limit_blocks_once_the_hourly_budget_is_spent(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    rl.reset()
    dep = quota.quota_limit("traffic-test", limit=lambda is_demo: 2)
    token = _token(is_demo=False)

    await dep(_quota_request(), token)
    await dep(_quota_request(), token)
    with pytest.raises(HTTPException) as exc:
        await dep(_quota_request(), token)
    assert exc.value.status_code == 429
    assert "Retry-After" in exc.value.headers


@pytest.mark.asyncio
async def test_quota_limit_is_per_user(monkeypatch):
    """One caller exhausting their budget must not lock out everyone else."""
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    rl.reset()
    dep = quota.quota_limit("geocode-test", limit=lambda is_demo: 1)

    await dep(_quota_request(), _token(is_demo=False))
    await dep(_quota_request(), _token(is_demo=False))  # different user, own budget


@pytest.mark.asyncio
async def test_quota_limit_gives_demo_sessions_the_smaller_budget(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    rl.reset()
    dep = quota.quota_limit("routing-test", limit=lambda is_demo: 1 if is_demo else 50)

    await dep(_quota_request(), _token(is_demo=True))
    with pytest.raises(HTTPException) as exc:
        await dep(_quota_request(), _token(is_demo=True, user_id=uuid.uuid4()))
    # A *fresh* demo session from the same IP hits the shared demo-IP bucket, so
    # cycling demo tokens does not reset the budget.
    assert exc.value.status_code == 429


@pytest.mark.asyncio
async def test_quota_limit_demo_ip_bucket_is_per_ip(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    rl.reset()
    dep = quota.quota_limit("routing-test-2", limit=lambda is_demo: 1)

    await dep(_quota_request("198.51.100.1"), _token(is_demo=True))
    await dep(_quota_request("198.51.100.2"), _token(is_demo=True))


@pytest.mark.asyncio
async def test_quota_limit_rejection_does_not_consume_other_buckets(monkeypatch):
    """A demo request refused on the IP bucket must not also burn the (larger)
    per-user budget, otherwise the two limits compound unpredictably."""
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    rl.reset()
    dep = quota.quota_limit("mixed-test", limit=lambda is_demo: 1)
    ip = "192.0.2.50"

    await dep(_quota_request(ip), _token(is_demo=True))
    fresh = _token(is_demo=True)
    with pytest.raises(HTTPException):
        await dep(_quota_request(ip), fresh)
    # The blocked call was refused on the IP bucket; the new user's own budget
    # is untouched, so it still works from a different address.
    await dep(_quota_request("192.0.2.51"), fresh)


@pytest.mark.asyncio
async def test_quota_limit_disabled_is_noop(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    rl.reset()
    dep = quota.quota_limit("off-test", limit=lambda is_demo: 1)
    for _ in range(5):
        await dep(_quota_request(), _token(is_demo=True))


@pytest.mark.asyncio
async def test_quota_limit_zero_disables_that_class(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    rl.reset()
    dep = quota.quota_limit("zero-test", limit=lambda is_demo: 0 if is_demo else 1)
    for _ in range(5):
        await dep(_quota_request(), _token(is_demo=True))


def test_demo_token_marks_the_session_as_demo():
    """The throttles above rely on is_demo surviving the JWT round-trip."""
    token = _jwt.encode(
        {"sub": str(uuid.uuid4()), "typ": "access", "is_demo": True},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    assert deps._decode_token(token).is_demo is True


def test_regular_token_is_not_marked_as_demo():
    token = _jwt.encode(
        {"sub": str(uuid.uuid4()), "typ": "access"},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    assert deps._decode_token(token).is_demo is False


# ── Limiter bookkeeping ───────────────────────────────────────────────────────

def test_read_only_check_does_not_leave_an_entry_behind():
    rl.reset()
    assert rl.check("probe", 5, 60, record=False) is None
    assert "probe" not in rl._failures


def test_expired_keys_are_swept_instead_of_accumulating():
    """Quota keys include one per user — every ephemeral demo account included —
    so the counter dict must not grow for the life of the process."""
    rl.reset()
    for i in range(rl._SWEEP_INTERVAL_OPS):
        rl.check(f"stale:{i}", 5, 1, record=True)
    assert len(rl._failures) == rl._SWEEP_INTERVAL_OPS

    # Age every entry past its window, then trigger the next sweep.
    for dq in rl._failures.values():
        dq[0] -= 3600
    for i in range(rl._SWEEP_INTERVAL_OPS):
        rl.check(f"fresh:{i}", 5, 1, record=True)

    assert not any(k.startswith("stale:") for k in rl._failures)


def test_sweep_keeps_keys_that_are_still_within_their_window():
    rl.reset()
    rl.check("live", 5, 3600, record=True)
    for i in range(rl._SWEEP_INTERVAL_OPS):
        rl.check(f"filler:{i}", 5, 3600, record=True)
    assert "live" in rl._failures
    # And the surviving entry still counts toward the limit.
    assert len(rl._failures["live"]) == 1
