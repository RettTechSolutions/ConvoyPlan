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
