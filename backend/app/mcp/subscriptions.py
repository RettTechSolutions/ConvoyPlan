"""Live-Abonnements: der Konvoi meldet sich, statt abgefragt zu werden.

Auf der Wire-Revision 2026-07-28 eröffnet ein Client mit
``subscriptions/listen`` einen Strom und nennt darin die Resource-URIs, über
deren Änderung er unterrichtet werden will. Für ConvoyPlan ist das die
interessanteste Neuerung des Protokolls: wer eine Marschkolonne begleitet,
will nicht im Sekundentakt ``fahrzeugpositionen_abrufen`` aufrufen, sondern
erfahren, *wenn* sich etwas bewegt.

**Das SDK prüft dabei nichts.** ``ListenHandler`` honoriert jede angefragte
URI unbesehen — es gibt keinen Autorisierungshaken, und aus Sicht des SDK
ist das auch richtig so: eine Subscription auf eine nicht existierende URI
ist zulässig und feuert eben nie. Für einen mandantenfähigen Server ist es
trotzdem ein Leck: ein Client, der die URI eines fremden Konvois errät,
bekäme zwar nie dessen Daten (die Leseprüfung unten hält), wohl aber die
Nachricht *dass* sich dort gerade etwas tut. Bei einem Einsatz ist schon das
eine Auskunft.

Gelöst über die **Form der URI**: die Organisation steht darin.

    convoyplan://org/{org_id}/konvoi/{konvoi_id}/live

Damit ist die Zustellprüfung ein reiner Präfixvergleich gegen die
Organisation, für die das Token erteilt wurde — ohne Datenbankzugriff, ohne
Cache, ohne Zeitfenster, in dem sie danebenliegen könnte. Eine fremde URI
passt schlicht nicht.

Was der Strom trägt, ist bewusst wenig: ein ``notifications/resources/updated``
mit der URI, sonst nichts. Der Client liest die Resource danach selbst — und
dabei greift wieder die volle Prüfung aus ``mcp_context()``. Ein Ereignis ist
ein Anstoß, keine Übermittlung.
"""
import json
import logging
import uuid
from collections import OrderedDict
from collections.abc import Callable

import anyio.lowlevel
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.shared.subscriptions import ResourceUpdated, ServerEvent

from app.mcp import areas
from app.mcp.context import McpError, mcp_context
from app.mcp.scopes import SCOPE_READ
from app.services.tracking import tracking_manager

logger = logging.getLogger(__name__)

URI_PRAEFIX = "convoyplan://org/"


def live_uri(org_id, konvoi_id) -> str:
    """Die Live-URI eines Konvois."""
    return f"{URI_PRAEFIX}{org_id}/konvoi/{konvoi_id}/live"


# --------------------------------------------------------------------------
# Konvoi -> Organisation
# --------------------------------------------------------------------------
# Der Veröffentlicher sitzt in ``TrackingManager.broadcast`` und kennt nur die
# Konvoi-ID; für die URI fehlt ihm die Organisation. Ein Datenbankzugriff
# käme dort nicht in Frage: der Broadcast verteilt GPS-Positionen an die
# Fahrzeuge eines laufenden Einsatzes, und das ist der letzte Pfad, in den
# eine Abfrage gehört.
#
# Die Zuordnung ist stattdessen gemerkt. Sie kann nicht veralten: ein Konvoi
# bekommt seine ``organization_id`` beim Anlegen und behält sie — es gibt
# keinen Weg, ihn einer anderen Organisation zuzuschlagen. Gefüllt wird sie
# beim Lesen (siehe ``tools_read._load_convoy``), und genau das ist auch die
# einzige Stelle, an der ein Client die URI überhaupt erfährt. Ein Konvoi,
# den über diese Schnittstelle noch nie jemand angesehen hat, meldet nichts —
# fail-closed, und zwar ohne Sonderfall.
_ORG_JE_KONVOI: "OrderedDict[str, str]" = OrderedDict()
_CACHE_MAX = 4096


def merke_konvoi(konvoi_id, org_id) -> None:
    """Die Organisation eines Konvois für den Veröffentlicher hinterlegen."""
    key = str(konvoi_id)
    _ORG_JE_KONVOI.pop(key, None)
    _ORG_JE_KONVOI[key] = str(org_id)
    while len(_ORG_JE_KONVOI) > _CACHE_MAX:
        _ORG_JE_KONVOI.popitem(last=False)


def org_fuer_konvoi(konvoi_id) -> str | None:
    return _ORG_JE_KONVOI.get(str(konvoi_id))


def reset_cache() -> None:
    """Nur für Tests."""
    _ORG_JE_KONVOI.clear()


# --------------------------------------------------------------------------
# Der Bus
# --------------------------------------------------------------------------


class OrgScopedSubscriptionBus:
    """``SubscriptionBus`` mit Mandantentrennung in der Zustellung.

    ``subscribe()`` wird vom ``ListenHandler`` aus der Aufgabe heraus
    gerufen, die auch die Anfrage bearbeitet — die Contextvars des Aufrufers
    sind dort gesetzt (das SDK reicht den Sender-Kontext über
    ``ContextSendStream`` durch). Damit lässt sich die Organisation genau
    einmal, beim Abonnieren, festhalten und jedes spätere Ereignis dagegen
    prüfen.

    Festgehalten wird die Organisation **des Tokens**, nicht die aus der
    Datenbank: ``subscribe()`` ist synchron, eine Rückfrage ist dort nicht
    möglich. Verliert jemand seine Mitgliedschaft, während sein Strom offen
    ist, erfährt er bis zum Ablauf des Tokens (15 Minuten) weiterhin, *dass*
    sich in seiner früheren Organisation etwas bewegt — lesen kann er nichts
    davon, denn das geht wieder durch ``mcp_context()``. Ein bewusst in Kauf
    genommener Rest, kein Versehen.
    """

    def __init__(self) -> None:
        self._listeners: dict[object, Callable[[ServerEvent], None]] = {}

    def subscribe(self, listener: Callable[[ServerEvent], None]) -> Callable[[], None]:
        org_id = self._org_des_aufrufers()
        token = object()

        def gefiltert(event: ServerEvent) -> None:
            if _zustellbar(org_id, event):
                listener(event)

        self._listeners[token] = gefiltert

        def unsubscribe() -> None:
            self._listeners.pop(token, None)

        return unsubscribe

    async def publish(self, event: ServerEvent) -> None:
        """Die Schnittstelle, die das SDK erwartet."""
        self.publish_nowait(event)
        # Wie die Vorlage des SDK: ein Schwall aus einer Aufgabe soll den
        # Strömen Gelegenheit geben, zwischendurch zu leeren.
        await anyio.lowlevel.checkpoint()

    def publish_nowait(self, event: ServerEvent) -> None:
        """Dasselbe, synchron — für Veröffentlicher ohne Event-Loop-Anschluss.

        Die Zustellung selbst ist ohnehin synchron (der ``ListenHandler``
        legt das Ereignis mit ``send_nowait`` in seinen Puffer), es gibt also
        nichts zu erwarten. Das erspart dem Broadcast der Live-Verfolgung,
        eine Aufgabe zu starten, die niemand abwartet."""
        for zustellen in list(self._listeners.values()):
            try:
                zustellen(event)
            except Exception:
                logger.exception("MCP-Abonnent hat geworfen — übersprungen")

    @staticmethod
    def _org_des_aufrufers() -> str | None:
        token = get_access_token()
        if token is None:
            return None
        return (token.claims or {}).get("org_id")

    def reset(self) -> None:
        """Nur für Tests."""
        self._listeners.clear()


def _zustellbar(org_id: str | None, event: ServerEvent) -> bool:
    """Ob ein Ereignis an einen Abonnenten dieser Organisation gehen darf.

    Fail-closed: eine ``ResourceUpdated`` ohne bekannte Organisation oder mit
    einer URI, die nicht auf die eigene zeigt, wird verworfen. Die
    Listenänderungen (Tools, Prompts, Resources) tragen keinerlei Daten und
    gehen an alle."""
    if not isinstance(event, ResourceUpdated):
        return True
    if org_id is None:
        return False
    return event.uri.startswith(f"{URI_PRAEFIX}{org_id}/")


_bus = OrgScopedSubscriptionBus()


def bus() -> OrgScopedSubscriptionBus:
    return _bus


# --------------------------------------------------------------------------
# Der Veröffentlicher
# --------------------------------------------------------------------------


def _bei_broadcast(konvoi_id: str, _data: dict) -> None:
    """Jede Live-Meldung eines Konvois in ein Abo-Ereignis übersetzen.

    Läuft synchron im Broadcast der Live-Verfolgung und darf deshalb weder
    blockieren noch werfen. Der Inhalt der Meldung wird bewusst nicht
    weitergereicht: ein Ereignis sagt nur, dass es etwas Neues gibt."""
    org_id = org_fuer_konvoi(konvoi_id)
    if org_id is None:
        return
    _bus.publish_nowait(ResourceUpdated(uri=live_uri(org_id, konvoi_id)))


def attach_tracking() -> None:
    """Den Veröffentlicher an die Live-Verfolgung hängen."""
    tracking_manager.add_broadcast_listener(_bei_broadcast)


# --------------------------------------------------------------------------
# Die Resource
# --------------------------------------------------------------------------


async def live_payload(org_id: str, konvoi_id: str) -> dict:
    """Den Live-Stand eines Konvois lesen — mit voller Zugriffsprüfung.

    Die Organisation aus der URI wird gegen die des Tokens geprüft und nicht
    etwa übernommen: die URI kommt vom Client, und was von dort kommt, ist
    eine Behauptung."""
    # Verzögert importiert: ``tools_read`` meldet seinerseits Konvois hier an,
    # ein Import auf Modulebene wäre ein Zirkel.
    from app.mcp.tools_read import _load_convoy, _positionen, _status

    async with mcp_context() as ctx:
        ctx.require(SCOPE_READ)
        # Live-Positionen sind der empfindlichste Teil: an ihnen hängen die
        # Standorte von Besatzungen. Eine Organisation, die den Bereich Status
        # nicht freigibt, gibt ihn auch hier nicht her — sonst wäre das Abo
        # der Weg an der Freigabe vorbei.
        ctx.require_bereich(areas.BEREICH_STATUS)
        try:
            gefragte_org = uuid.UUID(org_id)
        except ValueError:
            raise McpError(f"„{org_id}“ ist keine gültige Organisations-ID.")
        if gefragte_org != ctx.organization.id:
            raise McpError(
                "Diese Resource gehört zu einer anderen Organisation. Diese "
                "Verbindung gilt für "
                f"„{ctx.organization.name}“ ({ctx.organization.id})."
            )

        convoy = await _load_convoy(ctx, konvoi_id)
        positionen = await _positionen(ctx, convoy)
        zusammenfassung, fahrzeuge, staerke = _status(convoy)
        return {
            "konvoi": convoy.name,
            "konvoi_status": convoy.status,
            "zusammenfassung": zusammenfassung,
            "staerke": staerke,
            "fahrzeuge": fahrzeuge,
            "positionen": positionen,
        }


def register(mcp) -> None:
    """Die Live-Resource am Server anmelden."""

    @mcp.resource(
        "convoyplan://org/{org_id}/konvoi/{konvoi_id}/live",
        name="Konvoi (live)",
        description=(
            "Der aktuelle Marschstand eines Konvois: Fahrzeugstatus und die "
            "zuletzt gemeldeten Positionen. Diese Resource lässt sich "
            "abonnieren — dann meldet der Server, sobald sich etwas bewegt, "
            "statt dass abgefragt werden muss. Die URI steht bei "
            "`konvoi_details` unter „live_uri“."
        ),
        mime_type="application/json",
    )
    async def konvoi_live(org_id: str, konvoi_id: str) -> str:
        return json.dumps(
            await live_payload(org_id, konvoi_id), ensure_ascii=False
        )
