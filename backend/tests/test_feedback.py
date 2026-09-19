"""Melden aus der Anwendung — was angenommen, abgewiesen und gezeigt wird.

Die Zusagen, die hier festgehalten werden, sind die, die man einem Screenshot
der Oberfläche nicht ansieht:

- Die Herkunft einer Meldung (Organisation, Konto) kommt aus der **Sitzung**,
  nie aus dem Körper der Anfrage. Sonst könnte sich jedes Mitglied eine
  Meldung im Namen einer fremden Organisation schreiben.
- Ein „Bildschirmfoto" wird am **Inhalt** erkannt, nicht am angegebenen Typ.
- Meldungen liest nur ein Superadmin.
- Der Melder bekommt die gespeicherte Zeile nicht zurück — dort stehen
  Priorität und interne Notiz.
"""

import base64
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_db, require_superadmin
from app.main import app
from app.models.feedback import STATUS_NEU
from app.services import feedback as feedback_svc

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 64


def _data_url(rohdaten: bytes, typ: str = "image/png") -> str:
    return f"data:{typ};base64,{base64.b64encode(rohdaten).decode()}"


# ── Das Bildschirmfoto: Inhalt schlägt Behauptung ────────────────────────────


def test_screenshot_wird_am_inhalt_erkannt():
    """Ein PNG bleibt ein PNG, auch wenn die Data-URL „jpeg" behauptet.

    Die Endung entscheidet später über den Medientyp beim Ausliefern; käme sie
    aus der Angabe des Absenders, ließe sich der Browser des Betrachters über
    den Typ täuschen."""
    _, endung = feedback_svc.decode_screenshot(_data_url(PNG, "image/jpeg"))
    assert endung == ".png"


@pytest.mark.parametrize(
    "rohdaten,erwartet", [(PNG, ".png"), (JPEG, ".jpg"), (WEBP, ".webp")]
)
def test_die_drei_rasterformate_gehen_durch(rohdaten, erwartet):
    bytes_, endung = feedback_svc.decode_screenshot(_data_url(rohdaten))
    assert endung == erwartet and bytes_ == rohdaten


def test_kein_svg():
    """SVG ist das einzige Bildformat, das Skript tragen kann — und ein
    Bildschirmfoto ist nie eines."""
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    with pytest.raises(HTTPException) as exc:
        feedback_svc.decode_screenshot(f"data:image/svg+xml;base64,{base64.b64encode(svg).decode()}")
    assert exc.value.status_code == 400


def test_etwas_anderes_als_ein_bild_wird_abgewiesen():
    with pytest.raises(HTTPException) as exc:
        feedback_svc.decode_screenshot(_data_url(b"MZ\x90\x00 nicht wirklich ein Bild"))
    assert exc.value.status_code == 400


def test_zu_grosses_bild_wird_abgewiesen():
    """Gemessen wird nach dem Dekodieren: die Grenze gilt dem Bild, nicht der
    um ein Drittel längeren Base64-Zeichenkette."""
    zu_gross = PNG + b"\x00" * feedback_svc.MAX_SCREENSHOT_BYTES
    with pytest.raises(HTTPException) as exc:
        feedback_svc.decode_screenshot(_data_url(zu_gross))
    assert exc.value.status_code == 400


def test_kein_ausbruch_aus_dem_bildverzeichnis():
    """Der Dateiname wird zum Pfad zusammengesetzt — also auf den Namen
    reduziert, bevor er das tut."""
    pfad = feedback_svc.screenshot_path("../../etc/passwd")
    assert pfad.parent == feedback_svc.FEEDBACK_DIR
    assert pfad.name == "passwd"


def test_verschwundenes_bild_laesst_sich_loeschen():
    """Eine verwaiste Datei darf das Löschen der Meldung nicht scheitern
    lassen."""
    feedback_svc.delete_screenshot("gibt-es-nicht.png")  # kein Fehler
    feedback_svc.delete_screenshot(None)


# ── Das Formular: was Pflicht ist ────────────────────────────────────────────


@pytest.mark.parametrize(
    "koerper",
    [
        {"kind": "meinung", "title": "Titel", "description": "Lange genug beschrieben."},
        {"kind": "bug", "title": "ab", "description": "Lange genug beschrieben."},
        {"kind": "bug", "title": "Titel", "description": "zu kurz"},
        {"kind": "bug", "title": "Titel", "description": "Lang genug.", "severity": "egal"},
    ],
)
@pytest.mark.asyncio
async def test_unbrauchbare_meldungen_werden_abgewiesen(koerper):
    """Vor jedem Datenbankzugriff: eine abgelehnte Meldung hinterlässt nichts."""
    from app.api.routes import feedback as feedback_route

    db = AsyncMock()
    db.add = MagicMock()

    async def _db():
        yield db

    # Angemeldet — geprüft wird hier das Formular, nicht die Anmeldung.
    app.dependency_overrides[feedback_route.melder] = lambda: feedback_route.Melder(
        MagicMock(id=uuid.uuid4(), email="melder@example.org", full_name="", is_demo=False),
        None,
        None,
    )
    app.dependency_overrides[get_db] = _db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/feedback", json=koerper)
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 422
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_ohne_anmeldung_keine_meldung():
    """Der Melde-Dialog sitzt hinter der Anmeldung — anonym ist er ein
    offenes Textfeld auf einer BOS-Instanz."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/feedback",
            json={"kind": "bug", "title": "Titel", "description": "Lange genug beschrieben."},
        )
    assert resp.status_code == 401


# ── Die Herkunft kommt aus der Sitzung ───────────────────────────────────────


@pytest.mark.asyncio
async def test_herkunft_stammt_aus_der_sitzung_nicht_aus_dem_koerper(monkeypatch):
    """Mitgeschickte Angaben zu Organisation oder Konto ändern nichts.

    Das Schema kennt die Felder gar nicht; entscheidend ist, dass sie auch
    nicht auf einem Umweg in die Zeile kommen."""
    from app.api.routes import feedback as feedback_route

    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = "melderin@example.org"
    user.full_name = "Mira Melderin"
    user.is_demo = False

    org = MagicMock()
    org.id = uuid.uuid4()
    org.slug = "kreis-nord"
    org.name = "Kreis Nord"

    app.dependency_overrides[feedback_route.melder] = lambda: feedback_route.Melder(
        user, org, "planer"
    )

    gespeichert = {}
    db = AsyncMock()
    db.add = MagicMock(side_effect=lambda zeile: gespeichert.setdefault("zeile", zeile))

    async def _refresh(zeile):
        zeile.created_at = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        )

    db.refresh.side_effect = _refresh

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    monkeypatch.setattr(feedback_route.audit, "record", AsyncMock())
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/feedback",
                json={
                    "kind": "bug",
                    "title": "Route rechnet nicht neu",
                    "description": "Nach dem Speichern bleibt die alte Route stehen.",
                    "severity": "hoch",
                    # Untergeschoben — darf nichts bewirken:
                    "org_id": str(uuid.uuid4()),
                    "reporter_email": "fremde@example.org",
                    "status": "erledigt",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 201
    zeile = gespeichert["zeile"]
    assert zeile.org_id == org.id and zeile.org_slug == "kreis-nord"
    assert zeile.reporter_email == "melderin@example.org"
    assert zeile.reporter_role == "planer"
    # Neu, nicht „erledigt": den Status setzt der Betreiber, nicht der Melder.
    assert zeile.status == STATUS_NEU
    # Die Einschätzung des Melders ist der Ausgangspunkt der Priorität — eine
    # als „hoch" gemeldete Störung startet nicht auf „normal".
    assert zeile.severity == "hoch" and zeile.priority == "hoch"


@pytest.mark.asyncio
async def test_die_quittung_verraet_den_datensatz_nicht(monkeypatch):
    """Zurück geht nur die Kennung — nicht Notiz, Priorität oder Status."""
    from app.api.routes import feedback as feedback_route

    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = "melder@example.org"
    user.full_name = ""
    user.is_demo = True

    app.dependency_overrides[feedback_route.melder] = lambda: feedback_route.Melder(
        user, None, None
    )

    db = AsyncMock()
    db.add = MagicMock()

    async def _refresh(zeile):
        zeile.created_at = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        )

    db.refresh.side_effect = _refresh

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    monkeypatch.setattr(feedback_route.audit, "record", AsyncMock())
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/feedback",
                json={
                    "kind": "feature",
                    "title": "Marschbefehl als PDF",
                    "description": "Wäre für die Übergabe an die Leitstelle praktisch.",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 201
    assert set(resp.json()) == {"id", "kind", "created_at"}


# ── Lesen darf nur der Betreiber ─────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "methode,pfad",
    [
        ("get", "/api/admin/feedback"),
        ("get", "/api/admin/feedback/stats"),
        ("get", f"/api/admin/feedback/{uuid.uuid4()}"),
        ("get", f"/api/admin/feedback/{uuid.uuid4()}/screenshot"),
        ("patch", f"/api/admin/feedback/{uuid.uuid4()}"),
        ("delete", f"/api/admin/feedback/{uuid.uuid4()}"),
    ],
)
async def test_meldungen_sind_nicht_ohne_superadmin_zu_haben(methode, pfad):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await getattr(client, methode)(pfad, **({"json": {}} if methode == "patch" else {}))
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_ein_fehlendes_bild_ist_kein_serverfehler():
    """Die Zeile weiß von einem Bild, das Volume nicht (Wiederherstellung ohne
    Volume). Das ist ein 404 auf das Bild, kein 500 auf die Meldung."""
    zeile = MagicMock()
    zeile.screenshot_name = "gibt-es-nicht.png"

    db = AsyncMock()
    db.get.return_value = zeile

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[require_superadmin] = lambda: MagicMock(is_superadmin=True)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/admin/feedback/{uuid.uuid4()}/screenshot")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 404


# ── Das Melden hängt nicht an der Lizenz ─────────────────────────────────────


def test_melden_bleibt_ohne_lizenz_erreichbar():
    """Der Demo-Modus ist der Zustand, in dem am ehesten jemand melden will.
    „Bitte Lizenz eingeben" wäre darauf die unbrauchbarste Antwort."""
    from app.middleware.license_guard import _EXEMPT_PREFIXES

    assert any("/api/feedback".startswith(p) for p in _EXEMPT_PREFIXES)
    # Das Sichten dagegen ist gewöhnliche Adminarbeit und bleibt lizenzpflichtig.
    assert not any("/api/admin/feedback".startswith(p) for p in _EXEMPT_PREFIXES)


# ── Modell und Migration dürfen nicht auseinanderlaufen ──────────────────────


def test_migration_und_modell_beschreiben_dieselbe_tabelle():
    """Die Spalten aus `0043` gegen die des Modells.

    Ohne diese Prüfung fällt eine neue Spalte, die nur im Modell steht, erst
    in Produktion auf — beim ersten `INSERT` gegen eine Tabelle, die sie nicht
    hat. Geprüft wird über den Quelltext der Migration, weil sie sich ohne
    Datenbank nicht ausführen lässt.
    """
    import ast
    from pathlib import Path

    from app.models.feedback import FeedbackReport

    quelle = Path(__file__).resolve().parents[1] / "alembic/versions/0043_feedback_reports.py"
    baum = ast.parse(quelle.read_text(encoding="utf-8"))

    spalten: set[str] = set()
    for knoten in ast.walk(baum):
        if not isinstance(knoten, ast.Call):
            continue
        name = getattr(knoten.func, "attr", None)
        if name != "Column" or not knoten.args:
            continue
        erstes = knoten.args[0]
        if isinstance(erstes, ast.Constant) and isinstance(erstes.value, str):
            spalten.add(erstes.value)

    assert spalten == {spalte.name for spalte in FeedbackReport.__table__.columns}


def test_die_migration_haengt_an_der_vorigen():
    """Eine Revision ohne Vorgänger wäre ein zweiter Kopf — Alembic bliebe
    beim nächsten `upgrade head` mit einer Fehlermeldung stehen."""
    import importlib.util
    from pathlib import Path

    pfad = Path(__file__).resolve().parents[1] / "alembic/versions/0043_feedback_reports.py"
    spec = importlib.util.spec_from_file_location("migration_0043", pfad)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    assert modul.revision == "0043" and modul.down_revision == "0042"
