"""Die öffentliche OpenAPI-Teilmenge und die Resource-Metadaten der REST-API.

Der Kern dieser Suite ist **eine** Zusage: was hier veröffentlicht wird, ist
ausdrücklich veröffentlicht worden. ``/docs`` und die vollständige Beschreibung
bleiben in Produktion abgeschaltet (siehe ``test_docs_gate.py``); das Dokument
unter ``/api/public/openapi.json`` ist eine bewusst kuratierte Teilmenge und
darf nicht durch eine neue Route, einen vergessenen Guard oder einen
ausschweifenden Docstring über ihren Rand hinauswachsen.

Geprüft wird deshalb nicht nur, dass das Dokument entsteht, sondern was **nicht**
darin steht: keine geschützten Pfade, keine Schemata der geschützten Endpunkte,
keine Docstring-Interna und nicht die genaue Build-Version.
"""
from httpx import ASGITransport, AsyncClient

from app.api.routes.public_meta import PUBLIC_OPERATIONS, build_public_openapi
from app.config import settings
from app.main import app


BASE = "https://public-api-test.convoyplan.invalid"

#: Diese Endpunkte tragen in der vollständigen Beschreibung ein
#: Sicherheitsschema, sind aber trotzdem öffentlich: sie werten ein Token
#: *optional* aus und antworten ohne eines mit weniger Inhalt statt mit 401.
#: Jeder weitere Eintrag hier gehört begründet — er ist die Ausnahme von der
#: Prüfung, die sonst einen vergessenen Guard fände.
OPTIONALE_ANMELDUNG = {("/api/version", "get")}


def _document() -> dict:
    return build_public_openapi(app, BASE)


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url=BASE)


# ── Die Liste stimmt mit der App überein ─────────────────────────────────


def test_jede_gelistete_operation_existiert():
    """Ein Eintrag, den es nicht mehr gibt, verschwindet sonst stillschweigend
    aus dem Dokument — und ein Agent sucht einen Endpunkt, den niemand
    abgeschafft haben wollte."""
    spec = app.openapi()
    fehlend = [
        f"{method.upper()} {path}"
        for path, method in PUBLIC_OPERATIONS
        if path not in spec["paths"] or method not in spec["paths"][path]
    ]
    assert fehlend == [], f"In PUBLIC_OPERATIONS gelistet, aber nicht (mehr) vorhanden: {fehlend}"


def test_keine_gelistete_operation_haengt_an_einem_guard():
    """Die Gegenrichtung: was hier als öffentlich steht, muss es auch sein.

    FastAPI trägt für jeden Endpunkt hinter einer Security-Dependency ein
    ``security`` in die Beschreibung ein. Findet sich das bei einem gelisteten
    Endpunkt, ist entweder die Liste falsch — oder jemand hat einen Guard
    ergänzt und diese Datei nicht gesehen.
    """
    spec = app.openapi()
    bewacht = [
        f"{method.upper()} {path}"
        for path, method in PUBLIC_OPERATIONS
        if (path, method) not in OPTIONALE_ANMELDUNG
        and spec["paths"].get(path, {}).get(method, {}).get("security")
    ]
    assert bewacht == [], (
        "Als öffentlich gelistet, hängt aber an einer Security-Dependency: "
        f"{bewacht}. Entweder aus PUBLIC_OPERATIONS entfernen oder — wenn die "
        "Anmeldung dort optional ist — in OPTIONALE_ANMELDUNG begründen."
    )


# ── Was im Dokument steht ────────────────────────────────────────────────


def test_dokument_enthaelt_ausschliesslich_gelistete_operationen():
    doc = _document()
    enthalten = {
        (path, method)
        for path, operations in doc["paths"].items()
        for method in operations
        if method != "parameters"
    }
    assert enthalten == set(PUBLIC_OPERATIONS)


def test_kein_geschuetzter_pfad_im_dokument():
    """Stichprobe auf das, was am teuersten wäre: die Administration und die
    Organisationsdaten."""
    doc = _document()
    for pfad in doc["paths"]:
        assert not pfad.startswith("/api/admin"), pfad
        assert not pfad.startswith("/api/convoys"), pfad
        assert not pfad.startswith("/api/vehicles"), pfad
        assert not pfad.startswith("/api/users"), pfad


def test_jede_operation_ist_fuer_function_calling_brauchbar():
    """Eindeutige ``operationId``, Zusammenfassung und Beschreibung an jeder
    Operation — ohne das kann ein Modell daraus keine aufrufbare Funktion
    ableiten."""
    doc = _document()
    ids: list[str] = []
    for pfad, operationen in doc["paths"].items():
        for methode, operation in operationen.items():
            if methode == "parameters":
                continue
            assert operation.get("operationId"), f"{methode} {pfad} ohne operationId"
            assert operation.get("summary"), f"{methode} {pfad} ohne summary"
            assert len(operation.get("description", "")) > 40, f"{methode} {pfad} ohne Beschreibung"
            assert operation.get("responses"), f"{methode} {pfad} ohne Antwortschema"
            ids.append(operation["operationId"])
    assert len(ids) == len(set(ids)), f"operationId doppelt vergeben: {ids}"


def test_operationen_sind_als_anmeldefrei_ausgewiesen():
    doc = _document()
    for operationen in doc["paths"].values():
        for methode, operation in operationen.items():
            if methode == "parameters":
                continue
            assert operation["security"] == []


def test_beschreibungen_kommen_aus_der_liste_nicht_aus_den_docstrings():
    """Docstrings erklären in diesem Projekt Entscheidungen — welcher Fehler
    dahinterstand, welche Enumeration erschwert werden soll. Das gehört nicht
    in ein Dokument, das ohne Anmeldung ausgeliefert wird."""
    doc = _document()
    spec = app.openapi()
    for (pfad, methode), kuratiert in PUBLIC_OPERATIONS.items():
        veroeffentlicht = doc["paths"][pfad][methode]["description"]
        assert veroeffentlicht == kuratiert["description"]
        original = spec["paths"][pfad][methode].get("description")
        if original and original != kuratiert["description"]:
            assert original not in veroeffentlicht


def test_sicherheitsschemata_sind_vollstaendig_beschrieben():
    """Ein Agent soll aus dem Dokument erfahren, wie er an ein Token kommt —
    das ist der Grund, warum die Schemata trotz fehlender geschützter Pfade
    darin stehen."""
    schemes = _document()["components"]["securitySchemes"]
    assert set(schemes) == {"bearerAuth", "apiKeyAuth", "oauth2"}
    assert schemes["apiKeyAuth"]["name"] == "X-API-Key"
    flow = schemes["oauth2"]["flows"]["authorizationCode"]
    assert flow["authorizationUrl"] == f"{BASE}/authorize"
    assert "convoy:read" in flow["scopes"]


def test_nur_referenzierte_schemata():
    """Ohne das Ausdünnen trüge das Dokument die Modelle sämtlicher geschützter
    Endpunkte mit sich."""
    doc = _document()
    serialisiert = repr(doc["paths"])
    for name in doc["components"]["schemas"]:
        assert name in serialisiert or any(
            name in repr(s) for s in doc["components"]["schemas"].values()
        ), f"{name} wird von keinem übernommenen Pfad gebraucht"
    # Stichprobe: ein Modell, das nur geschützte Endpunkte benutzen.
    assert "ConvoyResponse" not in doc["components"]["schemas"]


def test_version_verraet_den_build_nicht(monkeypatch):
    """``/api/version`` hält den ``git describe``-String vor anonymen Aufrufern
    zurück, weil er den genauen Commit einer unveröffentlichten Instanz
    verrät. Ein offenes Dokument darf ihn nicht hintenherum nachreichen."""
    monkeypatch.setattr(settings, "app_version", "2026.6.0-4-g37b9dad")
    assert _document()["info"]["version"] == "2026.6.0"


def test_server_url_kommt_aus_der_anfrage():
    assert _document()["servers"] == [{"url": BASE, "description": "Diese Instanz"}]


# ── Über HTTP ────────────────────────────────────────────────────────────


async def test_openapi_ohne_anmeldung_erreichbar():
    async with _client() as client:
        resp = await client.get(
            "/api/public/openapi.json", headers={"x-public-base-url": BASE}
        )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/vnd.oai.openapi+json")
    doc = resp.json()
    assert doc["openapi"].startswith("3.")
    assert doc["servers"][0]["url"] == BASE


async def test_fremder_base_url_header_wird_nicht_uebernommen():
    """Der Header ist Eingabe des Aufrufers, auch wenn er vom eigenen Frontend
    kommt. Was nicht wie eine Adresse aussieht, fliegt raus — sonst stünde in
    ``servers`` und in jeder OAuth-URL, was der Aufrufer hineinschreibt."""
    async with _client() as client:
        resp = await client.get(
            "/api/public/openapi.json",
            headers={"x-public-base-url": "https://boese.example/pfad?x=1"},
        )
    assert resp.status_code == 200
    assert resp.json()["servers"][0]["url"] == settings.app_base_url.rstrip("/")


async def test_protected_resource_metadata_der_rest_api():
    """RFC 9728 an der Wurzel. Nicht zu verwechseln mit der des MCP-Servers
    unter ``/.well-known/oauth-protected-resource/mcp``: die entsteht erst mit
    eingeschalteter KI-Schnittstelle, diese hier ist immer da."""
    async with _client() as client:
        resp = await client.get("/.well-known/oauth-protected-resource")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["resource"].endswith("/api")
    assert payload["bearer_methods_supported"] == ["header"]
    # Bei abgeschaltetem MCP gibt es keinen erreichbaren Autorisierungsserver;
    # ein Verweis auf einen 404 wäre schlimmer als gar keiner.
    from app.mcp import mount as mcp_mount

    if not mcp_mount.ist_aktiv():
        assert payload["authorization_servers"] == []
