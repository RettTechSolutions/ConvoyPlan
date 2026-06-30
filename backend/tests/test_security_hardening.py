"""Tests for the security-hardening additions: password policy, JWT-secret
fail-closed check, and the in-process auth rate limiter."""

import uuid
from unittest.mock import MagicMock

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


# ── CSP / Caddyfile security headers (T4) ─────────────────────────────────────────

from app.api.routes.setup import _generate_caddyfile  # noqa: E402


def test_setup_caddyfile_has_security_headers_report_only():
    cf = _generate_caddyfile("convoy.example.de", "auto", "a@b.de")
    assert "Strict-Transport-Security" in cf
    assert "X-Content-Type-Options" in cf
    # Report-Only by default so the CSP can never break the map UI.
    assert "Content-Security-Policy-Report-Only" in cf
    assert "tile.openstreetmap.org" in cf
    assert "wss://convoy.example.de" in cf


def test_setup_caddyfile_csp_enforce_toggle(monkeypatch):
    monkeypatch.setenv("CSP_ENFORCE", "true")
    cf = _generate_caddyfile("x.de", "internal", "a@b.de")
    assert "Content-Security-Policy-Report-Only" not in cf
    assert 'Content-Security-Policy "' in cf
