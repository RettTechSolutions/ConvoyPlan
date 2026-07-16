import pytest

from app.services import smartmaps


class _FakeDB:
    """Minimaler AsyncSession-Ersatz über einem key→SystemSetting-Dict."""

    def __init__(self):
        self.store = {}

    async def execute(self, stmt):
        key = stmt.compile().params.get("key_1")
        row = self.store.get(key)

        class _Result:
            def scalar_one_or_none(self):
                return row

        return _Result()

    def add(self, obj):
        self.store[obj.key] = obj

    async def commit(self):
        pass


@pytest.fixture(autouse=True)
def _reset_state():
    smartmaps.reset()
    yield
    smartmaps.reset()


async def test_resolve_api_key_uses_env_without_db_override(monkeypatch):
    monkeypatch.setattr(smartmaps.settings, "smartmaps_api_key", "ENVKEY")
    db = _FakeDB()
    assert await smartmaps.resolve_api_key(db) == "ENVKEY"


async def test_resolve_api_key_db_overrides_env(monkeypatch):
    from app.models.settings import SystemSetting

    monkeypatch.setattr(smartmaps.settings, "smartmaps_api_key", "ENVKEY")
    db = _FakeDB()
    db.store[smartmaps.KEY_API] = SystemSetting(key=smartmaps.KEY_API, value="DBKEY")
    assert await smartmaps.resolve_api_key(db) == "DBKEY"


async def test_resolve_api_key_empty_db_row_clears_env(monkeypatch):
    from app.models.settings import SystemSetting

    # Ein leerer DB-Eintrag schaltet den Key bewusst ab (kein ENV-Fallback).
    monkeypatch.setattr(smartmaps.settings, "smartmaps_api_key", "ENVKEY")
    db = _FakeDB()
    db.store[smartmaps.KEY_API] = SystemSetting(key=smartmaps.KEY_API, value="")
    assert await smartmaps.resolve_api_key(db) == ""


async def test_reserve_quota_disabled_when_limit_zero():
    db = _FakeDB()
    assert await smartmaps.reserve_tile_quota(db, "2026", 0) is True
    assert await smartmaps.reserve_tile_quota(db, "2026", 0) is True
    # Deckel deaktiviert -> kein Zählerstand wird geführt
    await smartmaps.flush_pending(db)
    assert db.store == {}


async def test_reserve_quota_counts_up_and_caps():
    db = _FakeDB()
    assert await smartmaps.reserve_tile_quota(db, "2026", 3) is True
    assert await smartmaps.reserve_tile_quota(db, "2026", 3) is True
    assert await smartmaps.reserve_tile_quota(db, "2026", 3) is True
    # Deckel erreicht -> vierte Reservierung schlägt fehl
    assert await smartmaps.reserve_tile_quota(db, "2026", 3) is False


async def test_flush_pending_writes_new_row():
    db = _FakeDB()
    await smartmaps.reserve_tile_quota(db, "2026", 100)
    await smartmaps.reserve_tile_quota(db, "2026", 100)
    await smartmaps.flush_pending(db)
    assert db.store["smartmaps.tile_usage.2026"].value == "2"
    # Nach dem Flush sind keine weiteren Anfragen mehr pending
    assert await smartmaps.reserve_tile_quota(db, "2026", 100) is True
    await smartmaps.flush_pending(db)
    assert db.store["smartmaps.tile_usage.2026"].value == "3"


async def test_flush_pending_accumulates_on_existing_row():
    from app.models.settings import SystemSetting

    db = _FakeDB()
    db.store["smartmaps.tile_usage.2026"] = SystemSetting(key="smartmaps.tile_usage.2026", value="10")
    # Zähler noch nicht im Speicher geladen -> lazy-load beim ersten reserve
    assert await smartmaps.reserve_tile_quota(db, "2026", 12) is True
    assert await smartmaps.reserve_tile_quota(db, "2026", 12) is True
    # Deckel (12) durch die vorhandenen 10 + 2 pending erreicht
    assert await smartmaps.reserve_tile_quota(db, "2026", 12) is False
    await smartmaps.flush_pending(db)
    assert db.store["smartmaps.tile_usage.2026"].value == "12"


async def test_flush_pending_noop_when_nothing_pending():
    db = _FakeDB()
    await smartmaps.flush_pending(db)
    assert db.store == {}


async def test_reserve_quota_rejected_attempt_not_counted():
    db = _FakeDB()
    assert await smartmaps.reserve_tile_quota(db, "2026", 2) is True
    assert await smartmaps.reserve_tile_quota(db, "2026", 2) is True
    # Deckel erreicht -> abgelehnte Reservierung darf nicht mitzählen
    assert await smartmaps.reserve_tile_quota(db, "2026", 2) is False
    await smartmaps.flush_pending(db)
    assert db.store["smartmaps.tile_usage.2026"].value == "2"


async def test_flush_retains_counts_when_commit_fails():
    class _FailingDB(_FakeDB):
        async def commit(self):
            raise RuntimeError("commit boom")

    db = _FailingDB()
    await smartmaps.reserve_tile_quota(db, "2026", 100)
    await smartmaps.reserve_tile_quota(db, "2026", 100)
    with pytest.raises(RuntimeError):
        await smartmaps.flush_pending(db)
    # Nach dem fehlgeschlagenen Commit muessen die 2 Anfragen weiterhin pending
    # sein und ein erneuter Flush (mit funktionierender DB) sie schreiben.
    ok_db = _FakeDB()
    await smartmaps.flush_pending(ok_db)
    assert ok_db.store["smartmaps.tile_usage.2026"].value == "2"
