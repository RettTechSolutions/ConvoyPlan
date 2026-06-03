from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import api_key as svc


def test_generate_key_roundtrip():
    gen = svc.generate_key()
    assert gen.full_key == f"cvp_{gen.prefix}_{gen.secret}"
    assert len(gen.prefix) == 8
    # The stored hash must verify the secret but never equal it.
    assert gen.key_hash != gen.secret
    import bcrypt
    assert bcrypt.checkpw(gen.secret.encode(), gen.key_hash.encode())


def test_parse_valid_and_invalid():
    gen = svc.generate_key()
    assert svc._parse(gen.full_key) == (gen.prefix, gen.secret)
    # secrets with underscores survive (partition on first "_" only)
    assert svc._parse("cvp_pre_a_b") == ("pre", "a_b")
    assert svc._parse("") is None
    assert svc._parse("noprefix_x") is None
    assert svc._parse("cvp_onlyprefix") is None


def test_is_expired():
    key = MagicMock()
    key.expires_at = None
    assert svc.is_expired(key) is False
    key.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    assert svc.is_expired(key) is True
    key.expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    assert svc.is_expired(key) is False


@pytest.mark.asyncio
async def test_resolve_key_rejects_revoked():
    gen = svc.generate_key()
    key = MagicMock()
    key.prefix = gen.prefix
    key.key_hash = gen.key_hash
    key.revoked = True

    result = MagicMock()
    result.scalar_one_or_none.return_value = key
    db = AsyncMock()
    db.execute.return_value = result

    assert await svc.resolve_key(db, gen.full_key) is None


@pytest.mark.asyncio
async def test_resolve_key_rejects_wrong_secret():
    gen = svc.generate_key()
    key = MagicMock()
    key.prefix = gen.prefix
    key.key_hash = gen.key_hash
    key.revoked = False

    result = MagicMock()
    result.scalar_one_or_none.return_value = key
    db = AsyncMock()
    db.execute.return_value = result

    # Same prefix but a different secret must not validate.
    assert await svc.resolve_key(db, f"cvp_{gen.prefix}_wrongsecret") is None


@pytest.mark.asyncio
async def test_resolve_key_accepts_valid():
    gen = svc.generate_key()
    key = MagicMock()
    key.prefix = gen.prefix
    key.key_hash = gen.key_hash
    key.revoked = False
    key.expires_at = None
    key.last_used_at = None

    result = MagicMock()
    result.scalar_one_or_none.return_value = key
    db = AsyncMock()
    db.execute.return_value = result

    resolved = await svc.resolve_key(db, gen.full_key)
    assert resolved is key
    # last_used_at refreshed and committed
    assert key.last_used_at is not None
    db.commit.assert_awaited()
