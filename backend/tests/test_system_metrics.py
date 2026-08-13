"""Tests der Systemübersicht: Hostkennzahlen, Docker-Report, Aktivitätsregistry,
Verdichtung, Berichtsexport und die Admin-Endpunkte."""

import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_db, require_superadmin
from app.config import settings
from app.main import app
from app.services import activity, docker_stats, host_metrics, system_metrics, system_report


# ── Testhilfen ───────────────────────────────────────────────────────────────

def _superadmin():
    user = MagicMock()
    user.is_superadmin = True
    return user


def _override_auth_and_db(db=None):
    app.dependency_overrides[require_superadmin] = _superadmin
    db = db or AsyncMock()

    async def _db_override():
        yield db

    app.dependency_overrides[get_db] = _db_override
    return db


@pytest.fixture(autouse=True)
def _clean_activity():
    activity.reset()
    yield
    activity.reset()
    app.dependency_overrides.clear()


# ── Hostkennzahlen ───────────────────────────────────────────────────────────

def test_cpu_percent_between_uses_idle_delta():
    previous = host_metrics.CpuTimes(total=1000.0, idle=800.0)
    current = host_metrics.CpuTimes(total=1200.0, idle=900.0)
    # 200 Ticks vergangen, davon 100 im Leerlauf → 50 % Auslastung.
    assert host_metrics.cpu_percent_between(previous, current) == 50.0


def test_cpu_percent_between_handles_missing_or_stale_samples():
    sample = host_metrics.CpuTimes(total=10.0, idle=5.0)
    assert host_metrics.cpu_percent_between(None, sample) is None
    assert host_metrics.cpu_percent_between(sample, None) is None
    # Kein Fortschritt zwischen zwei Messpunkten → kein aussagekräftiger Wert
    assert host_metrics.cpu_percent_between(sample, sample) is None


def test_read_memory_prefers_mem_available(tmp_path):
    meminfo = tmp_path / "meminfo"
    meminfo.write_text(
        "MemTotal:       1024 kB\n"
        "MemFree:         100 kB\n"
        "MemAvailable:    512 kB\n"
        "Cached:          300 kB\n"
        "SwapTotal:       200 kB\n"
        "SwapFree:        150 kB\n"
    )
    with patch.object(host_metrics, "_PROC", tmp_path):
        mem = host_metrics.read_memory()
    assert mem is not None
    assert mem.total_bytes == 1024 * 1024
    assert mem.available_bytes == 512 * 1024      # MemAvailable, nicht MemFree+Cached
    assert mem.used_bytes == 512 * 1024
    assert mem.percent == 50.0
    assert mem.swap_used_bytes == 50 * 1024


def test_read_memory_returns_none_without_procfs(tmp_path):
    with patch.object(host_metrics, "_PROC", tmp_path / "nirgendwo"):
        assert host_metrics.read_memory() is None


def test_read_pressure_parses_some_line(tmp_path):
    pressure_dir = tmp_path / "pressure"
    pressure_dir.mkdir()
    (pressure_dir / "io").write_text(
        "some avg10=1.23 avg60=0.45 avg300=0.10 total=99\n"
        "full avg10=0.50 avg60=0.20 avg300=0.05 total=42\n"
    )
    with patch.object(host_metrics, "_PROC", tmp_path):
        psi = host_metrics.read_pressure("io")
    assert psi == {"avg10": 1.23, "avg60": 0.45, "avg300": 0.10}


def test_read_pressure_missing_is_none(tmp_path):
    """Kernel ohne PSI (<4.20) darf die Erfassung nicht sprengen."""
    with patch.object(host_metrics, "_PROC", tmp_path):
        assert host_metrics.read_pressure("io") is None


def test_read_disk_io_skips_partitions_and_virtual_devices(tmp_path):
    # Felder: major minor name reads rd_merged rd_sectors rd_ms writes wr_merged
    #         wr_sectors wr_ms in_flight io_ms weighted_io_ms
    (tmp_path / "diskstats").write_text(
        "   8       0 sda 100 0 200 0 50 0 400 0 0 1000 0\n"
        "   8       1 sda1 100 0 999 0 50 0 999 0 0 999 0\n"
        "   7       0 loop0 1 0 999 0 1 0 999 0 0 999 0\n"
    )
    with patch.object(host_metrics, "_PROC", tmp_path):
        io = host_metrics.read_disk_io()
    assert io is not None
    # Nur sda zählt: 200 bzw. 400 Sektoren à 512 Byte.
    assert io.read_bytes == 200 * 512
    assert io.write_bytes == 400 * 512
    assert io.io_ms == 1000


def test_disk_io_rates_from_two_samples():
    previous = host_metrics.DiskIoCounters(read_bytes=0, write_bytes=0, io_ms=0, at=0.0)
    current = host_metrics.DiskIoCounters(read_bytes=2048, write_bytes=1024, io_ms=500, at=2.0)
    read, write, util = host_metrics.disk_io_rates(previous, current)
    assert read == 1024.0            # 2048 Byte in 2 s
    assert write == 512.0
    assert util == 25.0              # 500 ms busy in 2000 ms


def test_disk_usage_deduplicates_same_filesystem(tmp_path):
    nested = tmp_path / "unterordner"
    nested.mkdir()
    usage = host_metrics.disk_usage([str(tmp_path), str(nested), "/gibt/es/nicht"])
    # Beide Pfade liegen auf demselben Dateisystem → nur ein Eintrag, der
    # nicht existierende Pfad wird stillschweigend übersprungen.
    assert len(usage) == 1
    assert usage[0].path == str(tmp_path)


# ── Docker ───────────────────────────────────────────────────────────────────

def test_health_parsed_from_status_string():
    assert docker_stats._health_of({"Status": "Up 2 hours (healthy)"}) == "healthy"
    assert docker_stats._health_of({"Status": "Up 5 minutes (unhealthy)"}) == "unhealthy"
    assert docker_stats._health_of({"Status": "Up 3 seconds (health: starting)"}) == "starting"
    assert docker_stats._health_of({"Status": "Up 9 days"}) is None


def test_container_prefers_compose_service_name():
    info = docker_stats._parse_container({
        "Names": ["/convoyplan-backend-1"],
        "Image": "ghcr.io/x/backend:latest",
        "State": "running",
        "Status": "Up 1 hour (healthy)",
        "Labels": {"com.docker.compose.service": "backend"},
    })
    assert info.name == "backend"
    assert info.health == "healthy"


def test_report_counts_unhealthy_states():
    def _c(name, state, health):
        return docker_stats.ContainerInfo(
            name=name, image="i", state=state, status="", health=health,
            created_at=None, started_at=None, restart_count=None,
        )

    report = docker_stats.DockerReport(
        available=True,
        containers=[
            _c("a", "running", "healthy"),
            _c("b", "running", "unhealthy"),
            _c("c", "exited", None),
            _c("d", "running", "starting"),   # Hochlauf ist kein Problem
        ],
    )
    assert report.total == 4
    assert report.running == 3
    assert report.unhealthy == 2


def test_cpu_percent_from_stats_sample():
    stats = {
        "cpu_stats": {
            "cpu_usage": {"total_usage": 200},
            "system_cpu_usage": 2000,
            "online_cpus": 2,
        },
        "precpu_stats": {"cpu_usage": {"total_usage": 100}, "system_cpu_usage": 1000},
    }
    # 100 von 1000 System-Ticks auf 2 Kernen → 20 %
    assert docker_stats._cpu_percent(stats) == 20.0


def test_mem_usage_subtracts_page_cache():
    used, limit = docker_stats._mem_usage({
        "memory_stats": {"usage": 1000, "limit": 4000, "stats": {"inactive_file": 400}},
    })
    assert used == 600
    assert limit == 4000


@pytest.mark.asyncio
async def test_collect_reports_unavailable_when_disabled():
    previous = settings.docker_metrics_enabled
    settings.docker_metrics_enabled = False
    try:
        report = await docker_stats.collect()
    finally:
        settings.docker_metrics_enabled = previous
    assert report.available is False
    assert "deaktiviert" in (report.reason or "")


@pytest.mark.asyncio
async def test_collect_survives_unreachable_api():
    """Ist die Docker-API weg, bleibt der Rest der Übersicht nutzbar."""
    import httpx

    client = MagicMock()
    client.get = AsyncMock(side_effect=httpx.ConnectError("keine Verbindung"))
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    with patch.object(docker_stats, "_client", return_value=client):
        report = await docker_stats.collect()
    assert report.available is False
    assert "nicht erreichbar" in (report.reason or "")


# ── Aktivitätsregistry ───────────────────────────────────────────────────────

def test_active_users_counts_distinct_users_within_window():
    a, b = uuid.uuid4(), uuid.uuid4()
    org = uuid.uuid4()
    activity.touch(a, org)
    activity.touch(a, org)
    activity.touch(b, None)
    active = activity.active_users()
    assert len(active) == 2
    assert activity.snapshot()["active_users"] == 2
    assert activity.snapshot()["active_orgs"] == 1


def test_only_server_errors_count_as_errors():
    activity.record_request(status_code=200, duration_ms=10)
    activity.record_request(status_code=404, duration_ms=20)
    activity.record_request(status_code=500, duration_ms=30)
    counters, _ = activity.drain()
    assert counters.requests == 3
    assert counters.errors == 1
    assert counters.avg_response_ms == 20.0


def test_drain_resets_counters_and_returns_pending_users():
    user = uuid.uuid4()
    activity.touch(user)
    activity.record_request(status_code=200, duration_ms=5)

    counters, pending = activity.drain()
    assert counters.requests == 1
    assert [p.user_id for p in pending] == [user]

    # Zweiter Aufruf ohne neue Aktivität liefert nichts mehr …
    counters, pending = activity.drain()
    assert counters.requests == 0
    assert pending == []
    # … der Nutzer gilt aber weiter als aktiv (Fenster noch nicht abgelaufen).
    assert len(activity.active_users()) == 1


# ── Verdichtung und Aufbewahrung ─────────────────────────────────────────────

def test_choose_resolution_keeps_point_count_manageable():
    now = datetime.now(timezone.utc)
    # Explizite Angabe hat immer Vorrang.
    assert system_metrics.choose_resolution(now - timedelta(days=300), now, "raw") == "raw"
    # 6 Stunden bei 5-Minuten-Takt sind 72 Punkte → Rohdaten.
    assert system_metrics.choose_resolution(now - timedelta(hours=6), now, "auto") == "raw"
    # 30 Tage wären über 8000 Punkte → Stundenmittel.
    assert system_metrics.choose_resolution(now - timedelta(days=30), now, "auto") == "hour"
    # Ein Jahr → Tageswerte.
    assert system_metrics.choose_resolution(now - timedelta(days=365), now, "auto") == "day"


def test_counters_are_separated_from_gauges():
    """Zähler werden je Zeitfenster summiert, Messwerte gemittelt. Landet ein
    Zähler versehentlich bei den Messwerten, zeigte dieselbe Kurve bei Stunden-
    und bei Tagesauflösung verschiedene Einheiten."""
    gauges = set(system_metrics._GAUGE_FIELDS)
    counters = set(system_metrics._COUNTER_FIELDS)
    assert counters == {"requests", "request_errors", "logins"}
    assert not gauges & counters
    assert gauges | counters == set(system_metrics._SERIES_FIELDS)


def test_month_bounds_covers_full_month():
    assert system_metrics.month_bounds(2026, 2) == (date(2026, 2, 1), date(2026, 2, 28))
    assert system_metrics.month_bounds(2024, 2) == (date(2024, 2, 1), date(2024, 2, 29))
    assert system_metrics.month_bounds(2026, 12) == (date(2026, 12, 1), date(2026, 12, 31))


def test_aggregate_values_are_cast_to_column_types():
    from decimal import Decimal

    # avg() liefert in PostgreSQL Decimal — Float-Spalten brauchen float,
    # Zählerspalten int.
    assert system_metrics._to_number(Decimal("12.5"), "cpu_avg") == 12.5
    assert system_metrics._to_number(Decimal("7"), "unique_users") == 7
    assert isinstance(system_metrics._to_number(Decimal("7"), "unique_users"), int)
    assert system_metrics._to_number(None, "cpu_avg") is None


@pytest.mark.asyncio
async def test_purge_old_deletes_all_three_tables():
    db = AsyncMock()
    results = [MagicMock(rowcount=5), MagicMock(rowcount=2), MagicMock(rowcount=1)]
    db.execute.side_effect = results
    counts = await system_metrics.purge_old(db)
    assert counts == {"samples": 5, "daily": 2, "user_activity": 1}
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_rollup_day_skips_days_without_samples():
    db = AsyncMock()
    row = MagicMock()
    row._mapping = {"samples": 0}
    result = MagicMock()
    result.one.return_value = row
    db.execute.return_value = result
    assert await system_metrics.rollup_day(db, date(2026, 7, 1)) is None


# ── Berichtsexport ───────────────────────────────────────────────────────────

_REPORT = {
    "month": "2026-07",
    "from": "2026-07-01",
    "to": "2026-07-31",
    "generated_at": "2026-08-01T00:00:00+00:00",
    "days_covered": 2,
    "summary": {
        "cpu_percent_avg": 12.5,
        "cpu_percent_max": 88.0,
        "unique_users": 17,
        "logins": 120,
        "requests": 50000,
        "disk_used_end_bytes": 12_884_901_888,
    },
    "days": [
        {"t": "2026-07-01", "cpu_percent": 12.5, "unique_users": 5, "requests": 900},
        {"t": "2026-07-02", "cpu_percent": 15.0, "unique_users": 7, "requests": 1200},
    ],
    "usage_by_day": [],
}


def test_monthly_csv_uses_german_conventions():
    csv_text = system_report.monthly_report_csv(_REPORT)
    assert "Monat;Juli 2026" in csv_text
    # Semikolon als Trennzeichen, Komma als Dezimaltrenner — sonst zerlegt ein
    # deutsches Excel die Zahlen falsch.
    assert "CPU-Auslastung Ø;12,5 %" in csv_text
    assert "Eindeutige Benutzer;17" in csv_text
    assert "2026-07-01;12,5" in csv_text
    assert "12,0 GB" in csv_text


def test_monthly_csv_without_data_still_has_structure():
    empty = {**_REPORT, "days": [], "days_covered": 0, "summary": {}}
    csv_text = system_report.monthly_report_csv(empty)
    assert "Zusammenfassung" in csv_text
    assert "Tageswerte" in csv_text


def test_monthly_pdf_renders():
    pdf = system_report.monthly_report_pdf(_REPORT)
    assert pdf.startswith(b"%PDF-")
    assert len(pdf) > 1000


def test_monthly_pdf_renders_without_days():
    pdf = system_report.monthly_report_pdf({**_REPORT, "days": [], "days_covered": 0})
    assert pdf.startswith(b"%PDF-")


def test_series_csv_lists_all_fields():
    csv_text = system_report.series_csv({
        "resolution": "raw",
        "points": [{"t": "2026-07-01T00:00:00+00:00", "cpu_percent": 12.5, "active_users": 3}],
    })
    assert csv_text.splitlines()[0] == "t;cpu_percent;active_users"
    assert "12,50" in csv_text


# ── Endpunkte ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_overview_requires_superadmin():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/admin/system/overview")
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_overview_returns_all_sections():
    _override_auth_and_db()
    snapshot = {"checked_at": "2026-08-13T10:00:00+00:00", "host": {}, "docker": {}, "database": {}, "usage": {}}
    with patch.object(system_metrics, "live_snapshot", AsyncMock(return_value=snapshot)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/admin/system/overview")
    assert r.status_code == 200
    assert set(r.json()) >= {"host", "docker", "database", "usage"}


@pytest.mark.asyncio
async def test_history_rejects_unknown_range():
    _override_auth_and_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/admin/system/history?range=42y")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_history_passes_window_to_query():
    _override_auth_and_db()
    captured = {}

    async def _fake_query(_db, start, end, resolution):
        captured.update(start=start, end=end, resolution=resolution)
        return {"resolution": "raw", "from": start.isoformat(), "to": end.isoformat(), "points": []}

    with patch.object(system_metrics, "query_series", _fake_query):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/admin/system/history?range=7d")
    assert r.status_code == 200
    span = captured["end"] - captured["start"]
    assert timedelta(days=6, hours=23) < span <= timedelta(days=7)


@pytest.mark.asyncio
async def test_history_csv_export_sets_download_headers():
    _override_auth_and_db()
    series = {"resolution": "raw", "points": [{"t": "2026-08-13T10:00:00+00:00", "cpu_percent": 5.0}]}
    with patch.object(system_metrics, "query_series", AsyncMock(return_value=series)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/admin/system/history?range=24h&format=csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]


@pytest.mark.asyncio
async def test_monthly_report_rejects_malformed_month():
    _override_auth_and_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for month in ("2026-13", "Juli", "26-07"):
            r = await client.get(f"/api/admin/system/reports/monthly?month={month}")
            assert r.status_code == 400, month


@pytest.mark.asyncio
async def test_monthly_report_pdf_download():
    _override_auth_and_db()
    with patch.object(system_metrics, "monthly_report", AsyncMock(return_value=_REPORT)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/admin/system/reports/monthly?month=2026-07&format=pdf")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF-")


@pytest.mark.asyncio
async def test_report_months_always_offers_current_month():
    _override_auth_and_db()
    with patch.object(system_metrics, "available_months", AsyncMock(return_value=[])):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/admin/system/reports/months")
    assert r.status_code == 200
    data = r.json()
    assert data["months"] == [data["current"]]


@pytest.mark.asyncio
async def test_usage_endpoint_returns_day_rows():
    _override_auth_and_db()
    rows = [{"day": "2026-08-12", "users": 4, "orgs": 2, "requests": 900}]
    with patch.object(system_metrics, "user_activity_days", AsyncMock(return_value=rows)), \
         patch.object(system_metrics, "unique_users_between", AsyncMock(return_value=9)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/admin/system/usage?days=7")
    assert r.status_code == 200
    data = r.json()
    assert data["unique_users"] == 9
    assert data["days"] == rows


@pytest.mark.asyncio
async def test_containers_endpoint_reports_unavailable_gracefully():
    app.dependency_overrides[require_superadmin] = _superadmin
    report = docker_stats.DockerReport(available=False, reason="Docker-API nicht erreichbar")
    with patch.object(docker_stats, "collect", AsyncMock(return_value=report)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/admin/system/containers")
    assert r.status_code == 200
    assert r.json()["available"] is False
