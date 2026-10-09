"""Positionsverlauf: nur für Konvois an einer aktiven Aktionsseite, ausgedünnt,
und an jeder Stelle, die Positionen schreibt.

Ein Verlauf jedes Einsatzes wäre ein Bewegungsprofil, das niemand bestellt
hat. Aufgezeichnet wird deshalb nur, solange ein Konvoi an einer
eingeschalteten, nicht abgelaufenen Seite hängt.
"""
import ast
import inspect
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.api.routes import geraete, track, tracking
from app.database import AsyncSessionLocal
from app.models.public_tracker import VehiclePositionTrail
from app.services import positionsverlauf as pv
from tests.aktionsseite_fixtures import (  # noqa: F401 — Fixtures, per Import aktiviert
    aktion,
    client,
    h,
    reset_db_engine,
    seite_anlegen,
)

T0 = datetime(2026, 12, 27, 18, 0, tzinfo=timezone.utc)


# ── Ausdünnen ──────────────────────────────────────────────────────────────


def test_erster_punkt_immer():
    assert pv.noetig(None, T0, 48.5, 12.1)


def test_hoechstens_einer_pro_minute():
    assert not pv.noetig((T0, 48.5, 12.1), T0 + timedelta(seconds=59), 48.5, 12.5)


def test_bewegt_jede_minute_stehend_alle_fuenf():
    letzter = (T0, 48.5, 12.1)
    assert pv.noetig(letzter, T0 + timedelta(minutes=1), 48.5, 12.11)  # ~740 m
    assert not pv.noetig(letzter, T0 + timedelta(minutes=4), 48.5, 12.1)
    assert pv.noetig(letzter, T0 + timedelta(minutes=5), 48.5, 12.1)


# ── Jede Schreibstelle zeichnet auf ────────────────────────────────────────


def _schreibende_funktionen(modul) -> dict[str, bool]:
    """Funktionen, die ``pg_insert(VehiclePosition)`` aufrufen — und ob sie
    auch ``positionsverlauf.aufzeichnen`` aufrufen."""
    baum = ast.parse(inspect.getsource(modul))
    ergebnis = {}
    for f in ast.walk(baum):
        if not isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        aufrufe = [n for n in ast.walk(f) if isinstance(n, ast.Call)]
        schreibt = any(
            isinstance(c.func, ast.Name) and c.func.id == "pg_insert"
            and c.args and isinstance(c.args[0], ast.Name) and c.args[0].id == "VehiclePosition"
            for c in aufrufe
        )
        if schreibt:
            ergebnis[f.name] = any(
                isinstance(c.func, ast.Attribute) and c.func.attr == "aufzeichnen"
                and isinstance(c.func.value, ast.Name) and c.func.value.id == "positionsverlauf"
                for c in aufrufe
            )
    return ergebnis


def test_jede_schreibstelle_zeichnet_auf():
    gefunden = {
        **_schreibende_funktionen(track),
        **_schreibende_funktionen(tracking),
        **_schreibende_funktionen(geraete),
    }
    # Heute vier: Fahrer-Link, REST, WebSocket, Ortungsgerät. Kommt eine dazu, steht sie hier.
    assert len(gefunden) == 4, gefunden
    assert all(gefunden.values()), gefunden


def test_keine_weitere_schreibstelle_ausserhalb():
    """Wer ``VehiclePosition`` an einer neuen Stelle schreibt, muss sie oben eintragen."""
    import pathlib

    app = pathlib.Path(track.__file__).resolve().parents[2]
    treffer = [
        str(p.relative_to(app))
        for p in app.rglob("*.py")
        if "pg_insert(VehiclePosition)" in p.read_text(encoding="utf-8")
    ]
    assert sorted(treffer) == ["api/routes/geraete.py", "api/routes/track.py", "api/routes/tracking.py"]


# ── Nur an aktiven Seiten ──────────────────────────────────────────────────


async def _verlauf(aktion) -> list[VehiclePositionTrail]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.execute(
                    select(VehiclePositionTrail).where(
                        VehiclePositionTrail.convoy_id == aktion.convoy_id
                    )
                )
            ).scalars().all()
        )


async def _melden(client, aktion, lon: float):
    r = await client.post(
        f"/api/convoys/{aktion.convoy_id}/positions",
        json={"vehicle_id": str(aktion.spitze), "lat": 48.5, "lon": lon},
        headers=h(aktion.admin),
    )
    assert r.status_code == 200, r.text


async def test_ohne_aktionsseite_kein_verlauf(aktion, client):
    await _melden(client, aktion, 12.1)
    assert await _verlauf(aktion) == []


async def test_mit_aktionsseite_wird_aufgezeichnet(aktion, client):
    await seite_anlegen(client, aktion)
    await _melden(client, aktion, 12.1)
    zeilen = await _verlauf(aktion)
    assert [(z.vehicle_id, z.lat, z.lon) for z in zeilen] == [(aktion.spitze, 48.5, 12.1)]
    # Gleich danach noch eine Meldung: zu dicht, kein zweiter Punkt.
    await _melden(client, aktion, 12.2)
    assert len(await _verlauf(aktion)) == 1


async def test_abgeschaltete_seite_zeichnet_nicht_auf(aktion, client):
    await seite_anlegen(client, aktion, enabled=False)
    await _melden(client, aktion, 12.1)
    assert await _verlauf(aktion) == []
