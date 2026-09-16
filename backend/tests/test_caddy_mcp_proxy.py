"""Der Proxy-Selbstcheck hinter dem MCP-Schalter.

Hintergrund: der Schalter im Portal mountet die Routen im Backend, ans
Weiterleiten kommt er nicht heran. Auf einer produktiven Instanz hat das dazu
geführt, dass das Portal „An" samt Verbindungsadresse zeigte, während `/mcp`
von außen als HTML-404 des Frontends beantwortet wurde — der Reverse Proxy
kannte den Pfad nicht. Sichtbar war davon nirgends etwas.

Geprüft wird deshalb vor allem eines: dass die Diagnose die **laufende**
Konfiguration ansieht und nicht die Datei auf der Platte. Genau der Fall — die
Datei stimmt, der Container läuft noch mit der alten Konfiguration — war der
echte.
"""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import caddy_config

pytestmark = pytest.mark.asyncio


def _live_json(mit_mcp: bool) -> str:
    """Ein Ausschnitt, wie ihn Caddys Admin-API liefert."""
    pfade = list(caddy_config.REQUIRED_MCP_PATHS) if mit_mcp else ["/api/*"]
    eintraege = ", ".join(f'{{"path": ["{p}"]}}' for p in pfade)
    return '{"apps": {"http": {"servers": {"srv0": {"routes": [' + eintraege + "]}}}}}"


def _antwort(text: str):
    resp = MagicMock()
    resp.text = text
    resp.raise_for_status = MagicMock()
    return resp


def _client_mit(resp):
    client = AsyncMock()
    client.get.return_value = resp
    ctx = AsyncMock()
    ctx.__aenter__.return_value = client
    return ctx


# ── Die laufende Konfiguration ist die Wahrheit ──────────────────────────


async def test_erkennt_vorhandene_routen_in_der_laufenden_konfiguration():
    with patch("httpx.AsyncClient", return_value=_client_mit(_antwort(_live_json(True)))):
        assert await caddy_config.mcp_routes_live() is True


async def test_erkennt_fehlende_routen_in_der_laufenden_konfiguration():
    with patch("httpx.AsyncClient", return_value=_client_mit(_antwort(_live_json(False)))):
        assert await caddy_config.mcp_routes_live() is False


async def test_teilweise_vorhandene_routen_zaehlen_als_fehlend():
    """Alle Pfade oder keiner — ein halb konfigurierter Proxy ist kaputt."""
    unvollstaendig = '{"routes": [{"path": ["/mcp"]}, {"path": ["/token"]}]}'
    with patch("httpx.AsyncClient", return_value=_client_mit(_antwort(unvollstaendig))):
        assert await caddy_config.mcp_routes_live() is False


async def test_nicht_erreichbare_admin_api_ist_unbekannt_nicht_nein():
    """Der Unterschied ist wichtig: „weiß ich nicht" darf im Portal keine
    Fehlermeldung werden, und erst recht keine Reparatur auslösen."""
    ctx = AsyncMock()
    ctx.__aenter__.side_effect = OSError("connection refused")
    with patch("httpx.AsyncClient", return_value=ctx):
        assert await caddy_config.mcp_routes_live() is None


# ── Der Befund ───────────────────────────────────────────────────────────


async def _diagnose(live, datei_text: str | None, setup: bool):
    db = AsyncMock()
    with (
        patch.object(caddy_config, "mcp_routes_live", AsyncMock(return_value=live)),
        patch.object(
            caddy_config, "_persisted_setup_values",
            AsyncMock(return_value=("x.de", "auto", "a@b.de") if setup else None),
        ),
        patch.object(Path, "is_file", lambda self: datei_text is not None),
        patch.object(Path, "read_text", lambda self, **kw: datei_text or ""),
    ):
        return await caddy_config.diagnose_proxy(db)


async def test_der_echte_fall_datei_stimmt_container_laeuft_alt():
    """Die Datei trägt die Routen, der laufende Proxy nicht.

    Eine Diagnose, die nur die Datei liest, meldete hier „alles in Ordnung" —
    und genau das war der Zustand, der niemandem aufgefallen ist."""
    befund = await _diagnose(
        live=False,
        datei_text="\n".join(caddy_config.REQUIRED_MCP_ROUTES),
        setup=True,
    )
    assert befund.routen_aktiv is False
    assert befund.datei_hat_routen is True
    assert befund.reparierbar is True


async def test_ohne_persistierte_datei_ist_reparatur_moeglich():
    befund = await _diagnose(live=False, datei_text=None, setup=True)
    assert befund.persistierte_datei is False
    assert befund.reparierbar is True


async def test_ohne_setup_werte_ist_nichts_zu_reparieren():
    """Ohne Domain und TLS-Modus lässt sich kein Caddyfile erzeugen — dann
    soll das Portal keinen Knopf anbieten, der nichts tun kann."""
    befund = await _diagnose(live=False, datei_text=None, setup=False)
    assert befund.reparierbar is False


async def test_laufender_proxy_braucht_keine_reparatur():
    befund = await _diagnose(live=True, datei_text=None, setup=True)
    assert befund.reparierbar is False


async def test_unbekannter_zustand_loest_keine_reparatur_aus():
    """None ist nicht False. Sonst schriebe eine nicht erreichbare Admin-API
    einer funktionierenden Instanz die Proxy-Konfiguration um."""
    befund = await _diagnose(live=None, datei_text=None, setup=True)
    assert befund.routen_aktiv is None
    # reparierbar bleibt True (man *darf* es versuchen), aber das Portal
    # bietet es als Hinweis an, nicht als Fehler — siehe _proxy_hinweis.
    assert befund.reparierbar is True


# ── Die Reparatur ────────────────────────────────────────────────────────


async def test_reparatur_ohne_setup_werte_scheitert_mit_begruendung():
    db = AsyncMock()
    with patch.object(caddy_config, "_persisted_setup_values", AsyncMock(return_value=None)):
        erfolg, text = await caddy_config.repair_mcp_routes(db)
    assert erfolg is False
    assert "Setup-Assistenten" in text


async def test_reparatur_schreibt_und_laedt_nach():
    db = AsyncMock()
    geschrieben: dict[str, str] = {}
    with (
        patch.object(
            caddy_config, "_persisted_setup_values",
            AsyncMock(return_value=("web.example.de", "auto", "a@b.de")),
        ),
        patch.object(Path, "mkdir", lambda self, **kw: None),
        patch.object(Path, "write_text", lambda self, text, **kw: geschrieben.update(t=text)),
        patch.object(caddy_config, "reload_caddy", AsyncMock(return_value=True)),
        patch.object(caddy_config, "mcp_routes_live", AsyncMock(return_value=True)),
    ):
        erfolg, text = await caddy_config.repair_mcp_routes(db)

    assert erfolg is True, text
    # Beides muss passieren: die Datei überlebt den Neustart, das Nachladen
    # wirkt sofort. Eines allein wäre eine halbe Reparatur.
    assert caddy_config.has_mcp_routes(geschrieben["t"])
    assert "web.example.de" in geschrieben["t"]


async def test_reparatur_meldet_fehlschlag_wenn_die_pfade_danach_fehlen():
    """Geschrieben, geladen — und trotzdem nicht da. Das darf nicht als
    Erfolg durchgehen, sonst sucht der Betreiber an der falschen Stelle."""
    db = AsyncMock()
    with (
        patch.object(
            caddy_config, "_persisted_setup_values",
            AsyncMock(return_value=("web.example.de", "auto", "a@b.de")),
        ),
        patch.object(Path, "mkdir", lambda self, **kw: None),
        patch.object(Path, "write_text", lambda self, text, **kw: None),
        patch.object(caddy_config, "reload_caddy", AsyncMock(return_value=True)),
        patch.object(caddy_config, "mcp_routes_live", AsyncMock(return_value=False)),
    ):
        erfolg, text = await caddy_config.repair_mcp_routes(db)
    assert erfolg is False
    assert "fehlen" in text


async def test_reparatur_meldet_wenn_caddy_nicht_nachlaedt():
    db = AsyncMock()
    with (
        patch.object(
            caddy_config, "_persisted_setup_values",
            AsyncMock(return_value=("web.example.de", "auto", "a@b.de")),
        ),
        patch.object(Path, "mkdir", lambda self, **kw: None),
        patch.object(Path, "write_text", lambda self, text, **kw: None),
        patch.object(caddy_config, "reload_caddy", AsyncMock(return_value=False)),
    ):
        erfolg, text = await caddy_config.repair_mcp_routes(db)
    assert erfolg is False
    assert "nächsten Start" in text


# ── Die beiden Pfadlisten dürfen nicht auseinanderlaufen ─────────────────


def test_caddyfile_schreibweise_wird_aus_den_pfaden_abgeleitet():
    assert caddy_config.REQUIRED_MCP_ROUTES == tuple(
        f"handle {p}" for p in caddy_config.REQUIRED_MCP_PATHS
    )


def test_ein_erzeugtes_caddyfile_traegt_alle_pfade():
    """Die Gegenprobe zur Textsuche: was generate_caddyfile baut, muss von
    has_mcp_routes auch erkannt werden."""
    caddyfile = caddy_config.generate_caddyfile("web.example.de", "auto", "a@b.de")
    assert caddy_config.has_mcp_routes(caddyfile)
