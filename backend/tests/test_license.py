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


def _valid_payload(instance_id: str = "") -> dict:
    return {
        "id": "test-uuid",
        "customer": "Test GmbH",
        "email": "test@test.de",
        "issued": date.today().isoformat(),
        "expires": (date.today() + timedelta(days=365)).isoformat(),
        "max_users": 10,
        "instance_id": instance_id,
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


def test_valid_license_no_instance_binding(monkeypatch):
    import app.services.license as lic_mod
    priv, pub_b64 = _make_key()
    monkeypatch.setattr(lic_mod, "_PUBLIC_KEY_B64", pub_b64)

    key = _sign_payload(_valid_payload(instance_id=""), priv)
    # License without instance_id is valid on any installation
    info = lic_mod.validate_license(key, instance_id="some-random-uuid")
    assert info.valid
    assert info.customer == "Test GmbH"


def test_valid_license_matching_instance(monkeypatch):
    import app.services.license as lic_mod
    priv, pub_b64 = _make_key()
    monkeypatch.setattr(lic_mod, "_PUBLIC_KEY_B64", pub_b64)

    iid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    key = _sign_payload(_valid_payload(instance_id=iid), priv)
    info = lic_mod.validate_license(key, instance_id=iid)
    assert info.valid
    assert info.instance_id == iid


def test_instance_mismatch_rejected(monkeypatch):
    import app.services.license as lic_mod
    priv, pub_b64 = _make_key()
    monkeypatch.setattr(lic_mod, "_PUBLIC_KEY_B64", pub_b64)

    key = _sign_payload(_valid_payload(instance_id="correct-instance-id"), priv)
    info = lic_mod.validate_license(key, instance_id="other-instance-id")
    assert not info.valid
    assert "not valid for this installation" in info.error


def test_instance_check_skipped_when_no_local_id(monkeypatch):
    import app.services.license as lic_mod
    priv, pub_b64 = _make_key()
    monkeypatch.setattr(lic_mod, "_PUBLIC_KEY_B64", pub_b64)

    key = _sign_payload(_valid_payload(instance_id="bound-to-this"), priv)
    # If instance_id not yet available (first boot), skip binding check
    info = lic_mod.validate_license(key, instance_id="")
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


# ── HTTP endpoint tests ──────────────────────────────────────────────────────

import pytest


@pytest.mark.asyncio
async def test_license_mode_endpoint_demo_mode():
    """GET /api/license/mode returns demo_mode=true when no key is stored."""
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from unittest.mock import patch, AsyncMock

    with patch("app.api.routes.license.get_saved_license_key", new=AsyncMock(return_value="")), \
         patch("app.api.routes.license.get_or_create_instance_id", new=AsyncMock(return_value="test-id")):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/license/mode")

    assert r.status_code == 200
    data = r.json()
    assert "demo_mode" in data
    assert data["demo_mode"] is True


@pytest.mark.asyncio
async def test_license_mode_endpoint_licensed(monkeypatch):
    """GET /api/license/mode returns demo_mode=false when a valid key is stored."""
    import base64
    import json
    from datetime import date, timedelta
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from unittest.mock import patch, AsyncMock
    import app.services.license as lic_mod
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    priv = Ed25519PrivateKey.generate()
    pub_b64 = base64.b64encode(
        priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    ).decode()
    monkeypatch.setattr(lic_mod, "_PUBLIC_KEY_B64", pub_b64)

    payload = {
        "expires": (date.today() + timedelta(days=365)).isoformat(),
        "instance_id": "",
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    sig = priv.sign(payload_bytes)
    p64 = base64.urlsafe_b64encode(payload_bytes).decode().rstrip("=")
    s64 = base64.urlsafe_b64encode(sig).decode().rstrip("=")
    valid_key = f"{p64}.{s64}"

    with patch("app.api.routes.license.get_saved_license_key", new=AsyncMock(return_value=valid_key)), \
         patch("app.api.routes.license.get_or_create_instance_id", new=AsyncMock(return_value="")):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/license/mode")

    assert r.status_code == 200
    assert r.json()["demo_mode"] is False
