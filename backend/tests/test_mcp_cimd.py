"""Client ID Metadata Documents und der SSRF-Schutz darunter.

Der überwiegende Teil dieser Datei prüft Ablehnungen. Das ist Absicht: bei
CIMD ruft der Server eine Adresse ab, die der Anfragende bestimmt — die
interessante Frage ist nicht, ob ein gültiges Dokument durchgeht, sondern ob
alles andere hängenbleibt.
"""
import ipaddress
from unittest.mock import AsyncMock, patch

import pytest

from app.config import settings
from app.services import oauth_provider, safe_fetch
from app.services.safe_fetch import UnsafeUrlError

GUELTIG = "https://client.invalid/mcp-client.json"


@pytest.fixture(autouse=True)
def cimd_an(monkeypatch):
    monkeypatch.setattr(settings, "mcp_allow_cimd", True)
    oauth_provider.reset_cimd_cache()
    yield
    oauth_provider.reset_cimd_cache()


def _dokument(**abweichungen) -> dict:
    basis = {
        "client_id": GUELTIG,
        "client_name": "Musterclient",
        "redirect_uris": ["http://127.0.0.1:33418/cb"],
        "grant_types": ["authorization_code", "refresh_token"],
    }
    basis.update(abweichungen)
    return basis


# ── Der SSRF-Schutz ──────────────────────────────────────────────────────


@pytest.mark.parametrize("url,grund", [
    ("http://client.invalid/c", "kein HTTPS"),
    ("ftp://client.invalid/c", "fremdes Schema"),
    ("https://127.0.0.1/c", "Loopback"),
    ("https://10.0.0.5/c", "privates Netz"),
    ("https://192.168.1.1/c", "privates Netz"),
    ("https://172.16.0.1/c", "privates Netz"),
    ("https://169.254.169.254/c", "Cloud-Metadatendienst"),
    ("https://[::1]/c", "Loopback über IPv6"),
    ("https://[::ffff:10.0.0.1]/c", "IPv4-gemappte IPv6-Adresse"),
    ("https://0.0.0.0/c", "unspezifiziert"),
    ("https://100.64.0.1/c", "Carrier-Grade NAT (RFC 6598)"),
    ("https://client.invalid/c#teil", "Fragment"),
    ("https://nutzer:geheim@client.invalid/c", "Zugangsdaten in der URL"),
])
def test_unsichere_adressen_werden_abgelehnt(url, grund):
    with pytest.raises(UnsafeUrlError):
        safe_fetch.pruefe_url(url)


def test_cgnat_bereich_wird_abgelehnt():
    """Der Bereich, den `is_private` tatsächlich nicht abdeckt.

    RFC 6598 (100.64.0.0/10, Carrier-Grade NAT) gilt Python **nicht** als
    privat. In Netzen, die CGNAT einsetzen, wären darüber erreichbare Hosts
    sonst offen — dieser Test hält fest, dass die Prüfung den Bereich eigens
    ausschließt und nicht auf `is_private` vertraut."""
    adresse = ipaddress.ip_address("100.64.0.1")
    assert adresse.is_private is False, "Annahme über ipaddress hat sich geändert"
    assert safe_fetch._ip_ist_oeffentlich(adresse) is False
    with pytest.raises(UnsafeUrlError):
        safe_fetch.pruefe_url("https://100.64.0.1/c")


def test_der_metadatendienst_bleibt_unerreichbar():
    """169.254.169.254 liefert bei vielen Cloud-Anbietern die Zugangsdaten der
    Instanz. Dass CPython ihn bereits unter `is_private` führt, ist ein
    angenehmer Zufall — die Prüfung nennt link-local trotzdem ausdrücklich."""
    assert safe_fetch._ip_ist_oeffentlich(ipaddress.ip_address("169.254.169.254")) is False


def test_ein_name_der_nach_innen_zeigt_wird_abgelehnt(monkeypatch):
    """Der eigentliche Angriff: eine harmlos aussehende Domain, die auf eine
    interne Adresse auflöst."""
    def _aufloesung(*_args, **_kwargs):
        return [(2, 1, 6, "", ("10.1.2.3", 443))]

    monkeypatch.setattr(safe_fetch.socket, "getaddrinfo", _aufloesung)
    with pytest.raises(UnsafeUrlError, match="10.1.2.3"):
        safe_fetch.pruefe_url("https://sieht-harmlos-aus.invalid/c")


def test_jede_aufgeloeste_adresse_wird_geprueft(monkeypatch):
    """Ein Name kann auf mehrere Adressen zeigen. Nur die erste zu prüfen
    genügt nicht — welche der Client-Stack nimmt, entscheidet nicht diese
    Funktion."""
    def _aufloesung(*_args, **_kwargs):
        return [
            (2, 1, 6, "", ("93.184.216.34", 443)),   # öffentlich
            (2, 1, 6, "", ("127.0.0.1", 443)),       # und daneben Loopback
        ]

    monkeypatch.setattr(safe_fetch.socket, "getaddrinfo", _aufloesung)
    with pytest.raises(UnsafeUrlError, match="127.0.0.1"):
        safe_fetch.pruefe_url("https://zwei-gesichter.invalid/c")


# ── Das Dokument selbst ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_gueltiges_dokument_wird_aufgeloest():
    with patch.object(safe_fetch, "fetch_json", AsyncMock(return_value=_dokument())):
        client = await oauth_provider.loese_cimd_auf(GUELTIG)
    assert client is not None
    assert client.client_id == GUELTIG
    assert client.client_name == "Musterclient"
    # Ein CIMD-Client ist per Konstruktion öffentlich: es gibt niemanden, der
    # ihm ein Secret hätte ausstellen können.
    assert client.client_secret is None
    assert client.token_endpoint_auth_method == "none"


@pytest.mark.asyncio
async def test_dokument_das_eine_fremde_client_id_behauptet_wird_abgelehnt():
    """Sonst könnte ein Dokument unter der eigenen Adresse eine fremde
    client_id behaupten — und damit deren erteilte Zustimmungen erben."""
    fremd = _dokument(client_id="https://jemand-anderes.invalid/client.json")
    with patch.object(safe_fetch, "fetch_json", AsyncMock(return_value=fremd)):
        assert await oauth_provider.loese_cimd_auf(GUELTIG) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("abweichung", [
    {"redirect_uris": []},
    {"redirect_uris": "kein-array"},
    {"redirect_uris": ["http://angreifer.invalid/steal"]},
    {"redirect_uris": ["https://gut.invalid/cb#fragment"]},
    {"redirect_uris": ["https://gut.invalid/*"]},
])
async def test_unbrauchbare_redirect_uris_werden_abgelehnt(abweichung):
    """Dieselbe Regel wie bei der Registrierung — ein anderer Weg hinein
    darf keine schwächeren Bedingungen haben."""
    with patch.object(
        safe_fetch, "fetch_json", AsyncMock(return_value=_dokument(**abweichung))
    ):
        assert await oauth_provider.loese_cimd_auf(GUELTIG) is None


@pytest.mark.asyncio
async def test_nicht_abrufbares_dokument_ergibt_keinen_client():
    with patch.object(
        safe_fetch, "fetch_json",
        AsyncMock(side_effect=UnsafeUrlError("nicht erreichbar")),
    ):
        assert await oauth_provider.loese_cimd_auf(GUELTIG) is None


@pytest.mark.asyncio
async def test_abgeschaltet_wird_gar_nicht_erst_abgerufen(monkeypatch):
    """Der Schalter muss den Netzzugriff verhindern, nicht bloß das
    Ergebnis verwerfen."""
    monkeypatch.setattr(settings, "mcp_allow_cimd", False)
    abrufer = AsyncMock(return_value=_dokument())
    with patch.object(safe_fetch, "fetch_json", abrufer):
        assert await oauth_provider.loese_cimd_auf(GUELTIG) is None
    abrufer.assert_not_awaited()


@pytest.mark.asyncio
async def test_zweiter_aufruf_kommt_aus_dem_zwischenspeicher():
    abrufer = AsyncMock(return_value=_dokument())
    with patch.object(safe_fetch, "fetch_json", abrufer):
        await oauth_provider.loese_cimd_auf(GUELTIG)
        await oauth_provider.loese_cimd_auf(GUELTIG)
    assert abrufer.await_count == 1


@pytest.mark.asyncio
async def test_der_zwischenspeicher_laesst_sich_leeren():
    """Damit eine zurückgezogene Veröffentlichung ohne Neustart wirkt."""
    abrufer = AsyncMock(return_value=_dokument())
    with patch.object(safe_fetch, "fetch_json", abrufer):
        await oauth_provider.loese_cimd_auf(GUELTIG)
        oauth_provider.reset_cimd_cache()
        await oauth_provider.loese_cimd_auf(GUELTIG)
    assert abrufer.await_count == 2


# ── Abgrenzung zur Registrierung ─────────────────────────────────────────


def test_nur_https_client_ids_gelten_als_dokument():
    assert oauth_provider.ist_cimd_client_id("https://client.invalid/c.json") is True
    assert oauth_provider.ist_cimd_client_id("http://client.invalid/c.json") is False
    assert oauth_provider.ist_cimd_client_id("a3f9c2e1b4d67890") is False


@pytest.mark.asyncio
async def test_get_client_trennt_die_beiden_wege():
    """Eine HTTPS-client_id steht nicht in der Datenbank — sie dort zu suchen
    wäre nicht nur zwecklos, sondern verwechselte zwei Vertrauensmodelle."""
    provider = oauth_provider.ConvoyPlanOAuthProvider()
    with patch.object(
        oauth_provider, "loese_cimd_auf", AsyncMock(return_value=None)
    ) as aufloeser:
        assert await provider.get_client(GUELTIG) is None
        aufloeser.assert_awaited_once_with(GUELTIG)


# ── Der Laufzeitschalter ─────────────────────────────────────────────────
#
# CIMD hing bis hierher allein an ``MCP_ALLOW_CIMD``: beim Start entschieden,
# danach unveränderlich. Wer ChatGPT anbinden wollte, musste die ``.env``
# anfassen und neu starten. Der Schalter im Portal nimmt das ab — und
# derselbe Vorrang gilt wie bei ``mcp.enabled``: die Zeile schlägt die
# Umgebung, in beide Richtungen.


@pytest.mark.asyncio
async def test_portalschalter_kann_cimd_gegen_die_umgebung_einschalten(monkeypatch):
    from app.database import AsyncSessionLocal
    from app.services import mcp_config

    monkeypatch.setattr(settings, "mcp_allow_cimd", False)
    async with AsyncSessionLocal() as db:
        await mcp_config.set_cimd_allowed(db, True)
    try:
        abrufer = AsyncMock(return_value=_dokument())
        with patch.object(safe_fetch, "fetch_json", abrufer):
            assert await oauth_provider.loese_cimd_auf(GUELTIG) is not None
        abrufer.assert_awaited_once()
    finally:
        await _schalter_aufraeumen()


@pytest.mark.asyncio
async def test_portalschalter_kann_cimd_gegen_die_umgebung_abschalten(monkeypatch):
    """Die wichtigere Richtung: zudrehen muss den Netzzugriff verhindern,
    auch wenn die Umgebung ihn erlaubt."""
    from app.database import AsyncSessionLocal
    from app.services import mcp_config

    monkeypatch.setattr(settings, "mcp_allow_cimd", True)
    async with AsyncSessionLocal() as db:
        await mcp_config.set_cimd_allowed(db, False)
    try:
        abrufer = AsyncMock(return_value=_dokument())
        with patch.object(safe_fetch, "fetch_json", abrufer):
            assert await oauth_provider.loese_cimd_auf(GUELTIG) is None
        abrufer.assert_not_awaited()
    finally:
        await _schalter_aufraeumen()


@pytest.mark.asyncio
async def test_abgeschaltet_hilft_auch_ein_gefuellter_zwischenspeicher_nicht():
    """Die Prüfung steht vor dem Cache. Stünde sie dahinter, liefe ein
    einmal abgerufenes Dokument nach dem Zudrehen weiter."""
    from app.database import AsyncSessionLocal
    from app.services import mcp_config

    abrufer = AsyncMock(return_value=_dokument())
    with patch.object(safe_fetch, "fetch_json", abrufer):
        assert await oauth_provider.loese_cimd_auf(GUELTIG) is not None

    async with AsyncSessionLocal() as db:
        await mcp_config.set_cimd_allowed(db, False)
    try:
        assert await oauth_provider.loese_cimd_auf(GUELTIG) is None
    finally:
        await _schalter_aufraeumen()


@pytest.mark.asyncio
async def test_die_metadaten_kuendigen_cimd_nach_dem_geltenden_zustand_an(monkeypatch):
    """Ohne die Ankündigung versucht es kein Client — die Funktion läge brach.

    Geprüft wird über den Endpunkt, nicht über die gebaute Struktur: das
    Dokument entstand früher beim Start, und genau deshalb hätte ein
    Umschalten im Portal daran nichts geändert."""
    from app.database import AsyncSessionLocal
    from app.services import mcp_config
    from tests.mcp_fixtures import mcp_app

    monkeypatch.setattr(settings, "mcp_allow_cimd", False)
    try:
        async with mcp_app() as (_app, client):
            body = (await client.get("/.well-known/oauth-authorization-server")).json()
            assert not body.get("client_id_metadata_document_supported")

            async with AsyncSessionLocal() as db:
                await mcp_config.set_cimd_allowed(db, True)

            # Dieselbe, weiterhin laufende App — kein Neustart dazwischen.
            body = (await client.get("/.well-known/oauth-authorization-server")).json()
            assert body["client_id_metadata_document_supported"] is True
    finally:
        await _schalter_aufraeumen()


async def _schalter_aufraeumen() -> None:
    """Die Einstellungszeile wieder entfernen — sonst färbt sie auf den
    nächsten Test ab, der sich auf die Umgebung verlässt."""
    from sqlalchemy import delete

    from app.database import AsyncSessionLocal
    from app.models.settings import SystemSetting
    from app.services import mcp_config

    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(SystemSetting).where(SystemSetting.key == mcp_config.MCP_ALLOW_CIMD_KEY)
        )
        await db.commit()
