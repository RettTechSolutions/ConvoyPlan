"""Tests for license validation service."""
import base64
import json
from datetime import date, timedelta

import pytest


def _sign_payload(payload: dict, priv_key) -> str:
    """Return a license string signed with the given Ed25519 private key."""
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

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


def test_valid_license(monkeypatch):
    import app.services.license as lic_mod

    priv, pub_b64 = _make_key()
    monkeypatch.setattr(lic_mod, "_PUBLIC_KEY_B64", pub_b64)

    payload = {
        "id": "test-uuid",
        "customer": "Test GmbH",
        "email": "test@test.de",
        "issued": date.today().isoformat(),
        "expires": (date.today() + timedelta(days=365)).isoformat(),
        "max_users": 10,
    }
    key = _sign_payload(payload, priv)

    info = lic_mod.validate_license(key)
    assert info.valid
    assert info.customer == "Test GmbH"
    assert info.max_users == 10
    assert not info.expired


def test_expired_license(monkeypatch):
    import app.services.license as lic_mod

    priv, pub_b64 = _make_key()
    monkeypatch.setattr(lic_mod, "_PUBLIC_KEY_B64", pub_b64)

    payload = {
        "id": "x", "customer": "X", "email": "x@x.de",
        "issued": "2023-01-01",
        "expires": "2023-12-31",
        "max_users": 5,
    }
    key = _sign_payload(payload, priv)

    info = lic_mod.validate_license(key)
    assert not info.valid
    assert "expired" in info.error.lower()


def test_invalid_signature(monkeypatch):
    import app.services.license as lic_mod

    real_priv, pub_b64 = _make_key()
    other_priv, _ = _make_key()
    monkeypatch.setattr(lic_mod, "_PUBLIC_KEY_B64", pub_b64)

    payload = {
        "id": "x", "customer": "X", "email": "x@x.de",
        "issued": date.today().isoformat(),
        "expires": "2099-01-01",
        "max_users": 5,
    }
    key = _sign_payload(payload, other_priv)  # signed with wrong key

    info = lic_mod.validate_license(key)
    assert not info.valid
    assert "signature" in info.error.lower()
