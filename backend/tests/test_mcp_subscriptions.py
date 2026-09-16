"""Live-Abonnements: Zustellung und Mandantentrennung.

Der Schwerpunkt liegt auf dem, was das SDK **nicht** prüft. ``ListenHandler``
honoriert jede angefragte Resource-URI; ob ein Abonnent sie sehen darf,
entscheidet allein unser Bus. Diese Tests fahren deshalb genau diesen Weg ab,
einmal direkt am Bus und einmal durch den echten ``ListenHandler`` hindurch —
letzteres, weil die Organisation beim Abonnieren aus einer Contextvar kommt
und die nur trägt, solange das SDK den Sender-Kontext durchreicht.
"""
import json
import uuid

import anyio
import pytest
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from mcp.server.subscriptions import ListenHandler
from mcp.shared.subscriptions import ResourceUpdated, ToolsListChanged
from mcp_types import SubscriptionFilter, SubscriptionsListenRequestParams

from app.mcp import subscriptions as subs
from app.services.tracking import tracking_manager
from tests.mcp_fixtures import (  # noqa: F401  (reset_db_engine ist autouse)
    call,
    connect,
    mcp_app,
    mcp_session,
    purge_clients,
    reset_db_engine,
    seeded,
    tool_payload,
)

pytestmark = pytest.mark.asyncio

ORG_A = str(uuid.uuid4())
ORG_B = str(uuid.uuid4())
KONVOI = str(uuid.uuid4())


def _als(org_id: str | None):
    """Die Contextvar setzen, die die Middleware des SDK sonst füllt."""
    if org_id is None:
        return auth_context_var.set(None)
    token = AccessToken(
        token="tok",
        client_id="client",
        scopes=["convoy:read"],
        claims={"org_id": org_id},
    )
    return auth_context_var.set(AuthenticatedUser(token))


@pytest.fixture(autouse=True)
def sauberer_bus():
    subs.reset_cache()
    subs.bus().reset()
    yield
    subs.reset_cache()
    subs.bus().reset()


# ── Der Bus ──────────────────────────────────────────────────────────────


async def test_eigene_organisation_wird_zugestellt():
    bus = subs.bus()
    empfangen = []
    marke = _als(ORG_A)
    try:
        bus.subscribe(empfangen.append)
    finally:
        auth_context_var.reset(marke)

    await bus.publish(ResourceUpdated(uri=subs.live_uri(ORG_A, KONVOI)))
    assert [e.uri for e in empfangen] == [subs.live_uri(ORG_A, KONVOI)]


async def test_fremde_organisation_wird_verworfen():
    """Der Kern der Sache: die URI einer fremden Organisation erreicht
    niemanden, auch wenn der Client sie ausdrücklich abonniert hat."""
    bus = subs.bus()
    empfangen = []
    marke = _als(ORG_B)
    try:
        bus.subscribe(empfangen.append)
    finally:
        auth_context_var.reset(marke)

    await bus.publish(ResourceUpdated(uri=subs.live_uri(ORG_A, KONVOI)))
    assert empfangen == []


async def test_ohne_token_keine_resource_ereignisse():
    """Fail-closed: ohne erkennbare Organisation gar keine Resource-Meldung."""
    bus = subs.bus()
    empfangen = []
    marke = _als(None)
    try:
        bus.subscribe(empfangen.append)
    finally:
        auth_context_var.reset(marke)

    await bus.publish(ResourceUpdated(uri=subs.live_uri(ORG_A, KONVOI)))
    assert empfangen == []
    # Listenänderungen tragen keine Daten und gehen trotzdem durch.
    await bus.publish(ToolsListChanged())
    assert empfangen == [ToolsListChanged()]


async def test_praefix_laesst_sich_nicht_vortaeuschen():
    """Ein Organisationsname, der mit der eigenen ID beginnt, reicht nicht.

    Ohne den abschließenden Schrägstrich im Vergleich würde
    ``.../org/<A>-fremd/...`` als eigene URI durchgehen."""
    bus = subs.bus()
    empfangen = []
    marke = _als(ORG_A)
    try:
        bus.subscribe(empfangen.append)
    finally:
        auth_context_var.reset(marke)

    await bus.publish(
        ResourceUpdated(uri=f"convoyplan://org/{ORG_A}-fremd/konvoi/{KONVOI}/live")
    )
    assert empfangen == []


async def test_abmelden_beendet_die_zustellung():
    bus = subs.bus()
    empfangen = []
    marke = _als(ORG_A)
    try:
        abmelden = bus.subscribe(empfangen.append)
    finally:
        auth_context_var.reset(marke)

    abmelden()
    abmelden()  # idempotent
    await bus.publish(ResourceUpdated(uri=subs.live_uri(ORG_A, KONVOI)))
    assert empfangen == []


async def test_ein_werfender_abonnent_stoppt_die_anderen_nicht():
    bus = subs.bus()
    empfangen = []

    def wirft(_event):
        raise RuntimeError("kaputt")

    marke = _als(ORG_A)
    try:
        bus.subscribe(wirft)
        bus.subscribe(empfangen.append)
    finally:
        auth_context_var.reset(marke)

    await bus.publish(ResourceUpdated(uri=subs.live_uri(ORG_A, KONVOI)))
    assert len(empfangen) == 1


# ── Der Veröffentlicher an der Live-Verfolgung ───────────────────────────


async def test_broadcast_erzeugt_ein_ereignis():
    subs.attach_tracking()
    subs.merke_konvoi(KONVOI, ORG_A)
    bus = subs.bus()
    empfangen = []
    marke = _als(ORG_A)
    try:
        bus.subscribe(empfangen.append)
    finally:
        auth_context_var.reset(marke)

    await tracking_manager.broadcast(KONVOI, {"type": "position", "lat": 48.1})
    assert [e.uri for e in empfangen] == [subs.live_uri(ORG_A, KONVOI)]
    # Der Inhalt der Meldung wandert ausdrücklich nicht mit.
    assert not hasattr(empfangen[0], "data")


async def test_unbekannter_konvoi_meldet_nichts():
    """Ohne bekannte Organisation gibt es keine URI — und also kein Ereignis."""
    subs.attach_tracking()
    bus = subs.bus()
    empfangen = []
    marke = _als(ORG_A)
    try:
        bus.subscribe(empfangen.append)
    finally:
        auth_context_var.reset(marke)

    await tracking_manager.broadcast(str(uuid.uuid4()), {"type": "position"})
    assert empfangen == []


async def test_beobachter_wird_nicht_doppelt_angemeldet():
    vorher = len(tracking_manager._listeners)
    subs.attach_tracking()
    subs.attach_tracking()
    subs.attach_tracking()
    assert len(tracking_manager._listeners) <= vorher + 1


def test_cache_bleibt_beschraenkt():
    for _ in range(subs._CACHE_MAX + 50):
        subs.merke_konvoi(uuid.uuid4(), ORG_A)
    assert len(subs._ORG_JE_KONVOI) == subs._CACHE_MAX


# ── Durch den echten ListenHandler ───────────────────────────────────────


class _FakeSession:
    def __init__(self) -> None:
        self.gesendet = []

    async def send_notification(self, notification, related_request_id=None):
        self.gesendet.append(notification)


class _FakeCtx:
    def __init__(self, request_id: int) -> None:
        self.request_id = request_id
        self.session = _FakeSession()


async def test_listen_handler_filtert_ueber_den_bus():
    """Der ganze Weg: Contextvar → subscribe → Filter → Notification.

    Fährt den ``ListenHandler`` des SDK unverändert, weil genau dort die
    Annahme steckt, auf der alles ruht: dass der Handler in der Aufgabe des
    Aufrufers läuft und die Auth-Contextvar dort noch gesetzt ist. Bricht das
    in einer neuen SDK-Version, fällt es hier auf und nicht im Betrieb."""
    bus = subs.bus()
    handler = ListenHandler(bus)
    ctx = _FakeCtx(request_id=7)
    params = SubscriptionsListenRequestParams(
        notifications=SubscriptionFilter(
            resource_subscriptions=[
                subs.live_uri(ORG_A, KONVOI),
                # Ausdrücklich mit abonniert — und trotzdem nie zugestellt.
                subs.live_uri(ORG_B, KONVOI),
            ]
        )
    )

    async with anyio.create_task_group() as tg:
        marke = _als(ORG_A)
        try:
            tg.start_soon(handler, ctx, params)
        finally:
            auth_context_var.reset(marke)

        # Dem Handler Gelegenheit geben, die Bestätigung zu senden und sich
        # am Bus anzumelden.
        for _ in range(10):
            await anyio.sleep(0)

        await bus.publish(ResourceUpdated(uri=subs.live_uri(ORG_B, KONVOI)))
        await bus.publish(ResourceUpdated(uri=subs.live_uri(ORG_A, KONVOI)))
        for _ in range(10):
            await anyio.sleep(0)

        handler.close()

    methoden = [n.method for n in ctx.session.gesendet]
    assert methoden[0] == "notifications/subscriptions/acknowledged"
    aktualisierungen = [
        n.params.uri
        for n in ctx.session.gesendet
        if n.method == "notifications/resources/updated"
    ]
    assert aktualisierungen == [subs.live_uri(ORG_A, KONVOI)]


def test_sdk_honoriert_weiterhin_ungeprueft():
    """Die Annahme festnageln, die den eigenen Bus überhaupt nötig macht.

    Wenn das SDK eines Tages selbst autorisiert, soll dieser Test brechen —
    dann lässt sich die Doppelung hier überdenken, statt sie mitzuschleppen."""
    from mcp.server.subscriptions import _honored_subset

    fremd = subs.live_uri(ORG_B, KONVOI)
    honoriert = _honored_subset(
        SubscriptionFilter(resource_subscriptions=[fremd])
    )
    assert honoriert.resource_subscriptions == [fremd]


# ── Die Resource selbst ─────────────────────────────────────────────────


async def test_live_resource_liest_den_eigenen_konvoi():
    async with mcp_app() as (_app, client):
        async with seeded() as fx:
            reg, tokens = await connect(client, fx.planer, fx.org_a)
            try:
                token = tokens["access_token"]
                session = await mcp_session(client, token)

                details = tool_payload(
                    await call(
                        client, token, session, "tools/call",
                        {"name": "konvoi_details",
                         "arguments": {"konvoi_id": str(fx.convoy_a.id)}},
                    )
                )
                uri = details["live_uri"]
                assert uri == subs.live_uri(fx.org_a.id, fx.convoy_a.id)

                antwort = await call(
                    client, token, session, "resources/read", {"uri": uri}
                )
                inhalt = antwort["result"]["contents"][0]
                daten = json.loads(inhalt["text"])
                assert daten["konvoi"] == fx.convoy_a.name
                assert daten["positionen"] == []
                assert daten["zusammenfassung"] == {"planned": 1}
            finally:
                await purge_clients([reg["client_id"]])


async def test_live_resource_einer_fremden_organisation_wird_abgelehnt():
    """Die Organisation in der URI ist eine Behauptung des Clients.

    Hier wird sie gegen die des Tokens geprüft — sonst wäre die URI-Form ein
    Schlüssel statt einer Adresse."""
    async with mcp_app() as (_app, client):
        async with seeded() as fx:
            reg, tokens = await connect(client, fx.planer, fx.org_a)
            try:
                token = tokens["access_token"]
                session = await mcp_session(client, token)
                antwort = await call(
                    client, token, session, "resources/read",
                    {"uri": subs.live_uri(fx.org_b.id, fx.convoy_b.id)},
                )
                assert "anderen Organisation" in antwort["error"]["message"], antwort
            finally:
                await purge_clients([reg["client_id"]])


async def test_live_resource_mit_eigener_org_aber_fremdem_konvoi():
    """Die eigene Organisation in der URI, aber ein Konvoi aus der anderen:
    die Ladeprüfung muss das weiterhin abfangen."""
    async with mcp_app() as (_app, client):
        async with seeded() as fx:
            reg, tokens = await connect(client, fx.planer, fx.org_a)
            try:
                token = tokens["access_token"]
                session = await mcp_session(client, token)
                antwort = await call(
                    client, token, session, "resources/read",
                    {"uri": subs.live_uri(fx.org_a.id, fx.convoy_b.id)},
                )
                assert "Kein Konvoi mit der ID" in antwort["error"]["message"], antwort
            finally:
                await purge_clients([reg["client_id"]])
