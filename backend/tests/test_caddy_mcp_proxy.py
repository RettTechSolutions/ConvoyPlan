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
import errno
import re
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


@pytest.fixture
def certs(tmp_path, monkeypatch):
    """Ein echtes /certs im Temp-Verzeichnis.

    Bewusst kein gepatchtes ``write_text``: die interessante Eigenschaft des
    Schreibwegs ist, *wie* die Datei ersetzt wird, und das sähe ein Mock nicht."""
    monkeypatch.setattr(caddy_config, "CERTS_DIR", tmp_path)
    monkeypatch.setattr(caddy_config, "CADDYFILE_PATH", tmp_path / "Caddyfile")
    return tmp_path


def _setup_werte(vorhanden: bool = True):
    return patch.object(
        caddy_config, "_persisted_setup_values",
        AsyncMock(return_value=("web.example.de", "auto", "a@b.de") if vorhanden else None),
    )


async def test_reparatur_ohne_setup_werte_scheitert_mit_begruendung():
    db = AsyncMock()
    with _setup_werte(False):
        ergebnis = await caddy_config.repair_mcp_routes(db)
    assert ergebnis.erfolg is False
    assert "Setup-Assistenten" in ergebnis.meldung


async def test_reparatur_schreibt_und_laedt_nach(certs):
    db = AsyncMock()
    with (
        _setup_werte(),
        patch.object(caddy_config, "reload_caddy", AsyncMock(return_value=True)),
        patch.object(caddy_config, "mcp_routes_live", AsyncMock(return_value=True)),
    ):
        ergebnis = await caddy_config.repair_mcp_routes(db)

    assert ergebnis.erfolg is True, ergebnis.meldung
    assert ergebnis.dauerhaft is True
    # Beides muss passieren: die Datei überlebt den Neustart, das Nachladen
    # wirkt sofort. Eines allein wäre eine halbe Reparatur.
    geschrieben = (certs / "Caddyfile").read_text()
    assert caddy_config.has_mcp_routes(geschrieben)
    assert "web.example.de" in geschrieben


async def test_reparatur_meldet_fehlschlag_wenn_die_pfade_danach_fehlen(certs):
    """Geschrieben, geladen — und trotzdem nicht da. Das darf nicht als
    Erfolg durchgehen, sonst sucht der Betreiber an der falschen Stelle."""
    db = AsyncMock()
    with (
        _setup_werte(),
        patch.object(caddy_config, "reload_caddy", AsyncMock(return_value=True)),
        patch.object(caddy_config, "mcp_routes_live", AsyncMock(return_value=False)),
    ):
        ergebnis = await caddy_config.repair_mcp_routes(db)
    assert ergebnis.erfolg is False
    assert "fehlen" in ergebnis.meldung


async def test_reparatur_meldet_wenn_caddy_nicht_nachlaedt(certs):
    db = AsyncMock()
    with (
        _setup_werte(),
        patch.object(caddy_config, "reload_caddy", AsyncMock(return_value=False)),
    ):
        ergebnis = await caddy_config.repair_mcp_routes(db)
    assert ergebnis.erfolg is False
    assert "nächsten Start" in ergebnis.meldung


# ── Wenn /certs dem Backend nicht gehört ─────────────────────────────────
#
# Der Fall aus der Produktion: das Volume stammt aus der Zeit, als das Backend
# noch als root lief, und gehört seitdem root. „Proxy reparieren" endete mit
# „Permission denied" — und ließ eine Instanz zurück, deren MCP-Endpunkt
# unerreichbar blieb, obwohl das Nachladen gar keine Datei braucht.


def _eacces():
    return patch.object(
        caddy_config, "_caddyfile_schreiben",
        MagicMock(side_effect=PermissionError(errno.EACCES, "Permission denied")),
    )


async def test_ohne_schreibrecht_wird_trotzdem_nachgeladen(certs):
    """Erreichbar schlagen zwei Zeilen Fehlermeldung."""
    db = AsyncMock()
    reload = AsyncMock(return_value=True)
    with (
        _setup_werte(),
        _eacces(),
        patch.object(caddy_config, "reload_caddy", reload),
        patch.object(caddy_config, "mcp_routes_live", AsyncMock(return_value=True)),
    ):
        ergebnis = await caddy_config.repair_mcp_routes(db)

    reload.assert_awaited_once()
    assert ergebnis.erfolg is True, ergebnis.meldung


async def test_ohne_schreibrecht_ist_die_reparatur_nicht_dauerhaft(certs):
    """…und sagt das auch. Ein grüner Haken wäre hier gelogen: der nächste
    Neustart des Caddy-Containers wirft die Routen weg."""
    db = AsyncMock()
    with (
        _setup_werte(),
        _eacces(),
        patch.object(caddy_config, "reload_caddy", AsyncMock(return_value=True)),
        patch.object(caddy_config, "mcp_routes_live", AsyncMock(return_value=True)),
    ):
        ergebnis = await caddy_config.repair_mcp_routes(db)

    assert ergebnis.dauerhaft is False
    assert "Neustart" in ergebnis.meldung
    # Keine Rückfrage an jemanden, der sich dafür per SSH einloggen müsste,
    # sondern die Ursache und was die Instanz selbst dagegen tut.
    assert "/certs" in ergebnis.meldung
    assert "Update" in ergebnis.meldung


async def test_weder_schreiben_noch_laden_ist_ein_fehlschlag(certs):
    db = AsyncMock()
    with (
        _setup_werte(),
        _eacces(),
        patch.object(caddy_config, "reload_caddy", AsyncMock(return_value=False)),
    ):
        ergebnis = await caddy_config.repair_mcp_routes(db)
    assert ergebnis.erfolg is False
    assert "/certs" in ergebnis.meldung


async def test_der_start_laedt_auch_nach_wenn_er_nicht_schreiben_darf(certs):
    """Der eigentliche Grund, warum die betroffene Instanz nie von selbst
    genas: der Retrofit beim Start warf beim Schreibfehler hin und ließ das
    Nachladen aus — obwohl genau das ohne Datei auskommt und allein schon die
    Schnittstelle erreichbar gemacht hätte. Bei *jedem* Start aufs Neue."""
    (certs / "Caddyfile").write_text("# eine Caddyfile von vor dem MCP-Server\n")
    reload = AsyncMock(return_value=True)
    with (
        _setup_werte(),
        _eacces(),
        patch.object(caddy_config, "reload_caddy", reload),
    ):
        hinterlegt = await caddy_config.ensure_caddyfile_current(AsyncMock())

    reload.assert_awaited_once()
    geladen = reload.await_args.args[0]
    assert caddy_config.has_mcp_routes(geladen)
    # …und meldet trotzdem nicht „erledigt": hinterlegt ist nichts.
    assert hinterlegt is False


async def test_nach_erfolglosem_schreiben_bleibt_der_knopf_erreichbar():
    """Sonst wäre der Zustand „läuft, aber nicht hinterlegt" eine Sackgasse:
    die Diagnose meldete laufende Routen, das Portal verstecke den Knopf, und
    der nächste Neustart nähme die Routen wieder mit."""
    befund = await _diagnose(
        live=True,
        datei_text="# eine Caddyfile ohne MCP-Routen\n",
        setup=True,
    )
    assert befund.routen_aktiv is True
    assert befund.datei_hat_routen is False
    assert befund.reparierbar is True


# ── Der Schreibweg selbst ────────────────────────────────────────────────


def test_die_datei_wird_ersetzt_und_nicht_beschrieben(certs):
    """Der Grund, warum os.replace und nicht write_text: eine Datei, die
    jemand anderem gehört, lässt sich ersetzen, solange das Verzeichnis
    stimmt — überschreiben lässt sie sich nicht. Beobachtbar an der Inode."""
    ziel = certs / "Caddyfile"
    ziel.write_text("alt")
    vorher = ziel.stat().st_ino

    caddy_config._caddyfile_schreiben("neu")

    assert ziel.read_text() == "neu"
    assert ziel.stat().st_ino != vorher


def test_schreiben_laesst_keine_temporaerdateien_zurueck(certs):
    caddy_config._caddyfile_schreiben("neu")
    assert [p.name for p in certs.iterdir()] == ["Caddyfile"]


def test_ein_abgebrochener_schreibvorgang_laesst_die_alte_datei_stehen(certs):
    """Ein halbes Caddyfile fällt erst beim nächsten Caddy-Start auf — also
    dann, wenn niemand hinsieht."""
    ziel = certs / "Caddyfile"
    ziel.write_text("funktionierende alte Konfiguration")

    with (
        patch.object(caddy_config.os, "replace", side_effect=OSError("kaputt")),
        pytest.raises(OSError),
    ):
        caddy_config._caddyfile_schreiben("neu")

    assert ziel.read_text() == "funktionierende alte Konfiguration"
    assert [p.name for p in certs.iterdir()] == ["Caddyfile"]


def test_die_temporaerdatei_entsteht_neben_dem_ziel(tmp_path, monkeypatch):
    """CERTS_DIR und CADDYFILE_PATH können auseinanderfallen. Passiert das,
    darf der Schreibweg nicht ins *andere* Verzeichnis greifen: os.replace ist
    nur innerhalb eines Dateisystems atomar, und das Schreibrecht, auf das es
    hier ankommt, gilt für das Verzeichnis der Zieldatei.

    Gefunden von CI, nicht hier: lokal lief der Lauf als root und legte das
    unbeteiligte Verzeichnis kurzerhand an."""
    unerreichbar = tmp_path / "gibt-es-nicht" / "certs"
    ziel = tmp_path / "woanders" / "Caddyfile"
    ziel.parent.mkdir()
    monkeypatch.setattr(caddy_config, "CERTS_DIR", unerreichbar)
    monkeypatch.setattr(caddy_config, "CADDYFILE_PATH", ziel)

    caddy_config._caddyfile_schreiben("neu")

    assert ziel.read_text() == "neu"
    assert not unerreichbar.exists()


def test_die_geschriebene_datei_ist_lesbar(certs):
    """mkstemp legt mit 0600 an. Caddy läuft zwar als root, aber eine
    Konfigurationsdatei, die nur ihr Erzeuger lesen kann, ist eine Falle."""
    caddy_config._caddyfile_schreiben("neu")
    assert (certs / "Caddyfile").stat().st_mode & 0o044


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


# ── Die Voraussetzung dafür, dass das Backend überhaupt schreiben kann ───
#
# Auf gewachsenen Installationen gehört /certs noch root, weil Docker die
# Besitzrechte aus dem Image nur beim ersten Mount eines leeren Volumes
# überträgt. Caddys Entrypoint rückt das beim Start gerade — er ist der
# einzige Prozess an diesem Volume, der als root läuft. Beides hier geprüft,
# weil beides aus Versehen wieder verschwindet: der Mount, wenn jemand aus
# Vorsicht ein :ro ergänzt, und die uid, wenn sie im Dockerfile wandert.

_REPO = Path(__file__).resolve().parents[2]


def _backend_uid() -> str:
    dockerfile = (_REPO / "backend" / "Dockerfile").read_text()
    treffer = re.search(r"useradd --uid (\d+)", dockerfile)
    assert treffer, "backend/Dockerfile legt appuser nicht mehr per --uid an"
    return treffer.group(1)


def test_der_entrypoint_zieht_die_rechte_auf_den_benutzer_des_backends():
    """Eine abweichende uid wäre fatal *und* unsichtbar: der chown liefe
    durch, das Backend bliebe ausgesperrt."""
    entrypoint = (_REPO / "caddy" / "entrypoint.sh").read_text()
    uid = _backend_uid()
    assert f"chown -R {uid}:{uid} /certs" in entrypoint


def test_caddy_mountet_certs_nicht_nur_lesend():
    """Sonst scheitert der chown still und alles bleibt beim Alten."""
    compose = (_REPO / "docker-compose.yml").read_text()
    assert "cert_uploads:/certs:ro" not in compose


def test_der_chown_haelt_caddy_nicht_vom_starten_ab():
    """`set -e` steht ganz oben. Ohne aufgefangenen Fehlschlag brächte ein
    Dateisystem ohne chown den Reverse Proxy gar nicht erst hoch — aus einer
    fehlenden MCP-Route würde eine unerreichbare Instanz."""
    entrypoint = (_REPO / "caddy" / "entrypoint.sh").read_text()
    zeile = next(z for z in entrypoint.splitlines() if "chown -R" in z)
    assert zeile.rstrip().endswith("\\") or "||" in zeile
