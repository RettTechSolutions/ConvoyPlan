"""Tests for license validation service."""
import base64
import json
from datetime import date, timedelta


def _sign_payload(payload: dict, priv_key) -> str:
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode()
    sig_bytes = priv_key.sign(payload_bytes)
    p_b64 = base64.urlsafe_b64encode(payload_bytes).decode().rstrip("=")
    s_b64 = base64.urlsafe_b64encode(sig_bytes).decode().rstrip("=")
    return f"{p_b64}.{s_b64}"


def _make_key():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    priv = Ed25519PrivateKey.generate()
    pub_b64 = base64.b64encode(priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
    return priv, pub_b64


def _valid_payload(domain: str = "") -> dict:
    return {
        "id": "test-uuid",
        "customer": "Test GmbH",
        "email": "test@test.de",
        "issued": date.today().isoformat(),
        "expires": (date.today() + timedelta(days=365)).isoformat(),
        "max_users": 10,
        "domain": domain,
    }


def test_empty_key():
    from app.services.license import validate_license
    info = validate_license("")
    assert not info.valid
    assert "No license" in info.error


def test_malformed_key():
    from app.services.license import validate_license
    info = validate_license("notvalidatall")
    assert not info.valid
    assert "Malformed" in info.error


def test_valid_license_no_domain(monkeypatch):
    import app.services.license as lic_mod
    priv, pub_b64 = _make_key()
    monkeypatch.setattr(lic_mod, "_PUBLIC_KEY_B64", pub_b64)

    key = _sign_payload(_valid_payload(domain=""), priv)
    info = lic_mod.validate_license(key, current_domain="convoy.fw-musterstadt.de")
    assert info.valid
    assert info.customer == "Test GmbH"
    assert not info.expired


def test_valid_license_matching_domain(monkeypatch):
    import app.services.license as lic_mod
    priv, pub_b64 = _make_key()
    monkeypatch.setattr(lic_mod, "_PUBLIC_KEY_B64", pub_b64)

    key = _sign_payload(_valid_payload(domain="convoy.fw-musterstadt.de"), priv)
    info = lic_mod.validate_license(key, current_domain="convoy.fw-musterstadt.de")
    assert info.valid
    assert info.domain == "convoy.fw-musterstadt.de"


def test_domain_mismatch_rejected(monkeypatch):
    import app.services.license as lic_mod
    priv, pub_b64 = _make_key()
    monkeypatch.setattr(lic_mod, "_PUBLIC_KEY_B64", pub_b64)

    key = _sign_payload(_valid_payload(domain="convoy.fw-musterstadt.de"), priv)
    info = lic_mod.validate_license(key, current_domain="convoy.fw-other.de")
    assert not info.valid
    assert "convoy.fw-musterstadt.de" in info.error


def test_domain_check_skipped_on_localhost(monkeypatch):
    import app.services.license as lic_mod
    priv, pub_b64 = _make_key()
    monkeypatch.setattr(lic_mod, "_PUBLIC_KEY_B64", pub_b64)

    key = _sign_payload(_valid_payload(domain="convoy.fw-musterstadt.de"), priv)
    # localhost installs are always allowed regardless of licensed domain
    info = lic_mod.validate_license(key, current_domain="localhost")
    assert info.valid


def test_www_prefix_ignored(monkeypatch):
    import app.services.license as lic_mod
    priv, pub_b64 = _make_key()
    monkeypatch.setattr(lic_mod, "_PUBLIC_KEY_B64", pub_b64)

    key = _sign_payload(_valid_payload(domain="convoy.fw-musterstadt.de"), priv)
    info = lic_mod.validate_license(key, current_domain="www.convoy.fw-musterstadt.de")
    assert info.valid


def test_expired_license(monkeypatch):
    import app.services.license as lic_mod
    priv, pub_b64 = _make_key()
    monkeypatch.setattr(lic_mod, "_PUBLIC_KEY_B64", pub_b64)

    payload = {**_valid_payload(), "issued": "2023-01-01", "expires": "2023-12-31"}
    info = lic_mod.validate_license(_sign_payload(payload, priv))
    assert not info.valid
    assert "expired" in info.error.lower()


def test_invalid_signature(monkeypatch):
    import app.services.license as lic_mod
    real_priv, pub_b64 = _make_key()
    other_priv, _ = _make_key()
    monkeypatch.setattr(lic_mod, "_PUBLIC_KEY_B64", pub_b64)

    key = _sign_payload(_valid_payload(), other_priv)
    info = lic_mod.validate_license(key)
    assert not info.valid
    assert "signature" in info.error.lower()
