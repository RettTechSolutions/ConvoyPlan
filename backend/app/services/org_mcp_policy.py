"""Die MCP-Richtlinie einer Organisation — lesen, setzen, anwenden.

Zwei Schalter übereinander, und sie beantworten verschiedene Fragen:

``services/mcp_config`` sagt, ob es die Schnittstelle auf dieser Instanz
**gibt** — abgeschaltet existiert nicht einmal eine Route. Das ist die
Entscheidung des Betreibers.

Hier steht die Entscheidung des Org-Admins: ob **seine** Organisation über
diese Schnittstelle erreichbar ist, mit welchem Ausschnitt der Daten und ob
nur lesend. Die beiden multiplizieren sich, sie ersetzen einander nicht: ein
eingeschalteter Instanzschalter erteilt keiner Organisation etwas, und eine
freigebige Organisation erreicht niemanden, solange die Instanz zu ist.

**Standard ist aus.** Keine Zeile in der Tabelle heißt: diese Organisation
nimmt nicht teil. Eine neu angelegte Organisation ist damit stumm, auch wenn
der Betreiber die Schnittstelle längst eingeschaltet hat — wer Daten
herausgibt, soll das getan haben und nicht geerbt.

Die Richtlinie wirkt an vier Stellen, und alle vier sind nötig:

1. **Zustimmungsbildschirm** (``api/routes/mcp_consent.py``) — eine
   gesperrte Organisation lässt sich nicht auswählen, und was sie nicht
   freigibt, steht dort nicht zum Ankreuzen.
2. **Werkzeugliste** (``mcp/mount.py``) — ein Modell sieht nur, was diese
   Organisation hergibt. Ein Werkzeug anzubieten und den Aufruf abzulehnen
   ist eine schlechtere Auskunft als eines, das es nicht gibt.
3. **Jeder Aufruf** (``mcp/context.py``) — maßgeblich ist diese Prüfung, die
   beiden davor sind Komfort. Sie liest bei jedem Aufruf frisch, damit ein
   Entzug sofort wirkt und nicht erst mit dem Ablauf eines Tokens.
4. **Abos** (``mcp/subscriptions.py``) — eine Live-Verbindung, die vor der
   Sperre aufgemacht wurde, darf nicht weiterlaufen.
"""
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.mcp import areas
from app.mcp import scopes as scope_svc
from app.models.org_mcp_policy import OrganizationMcpPolicy


@dataclass(frozen=True)
class Policy:
    """Was eine Organisation über die KI-Schnittstelle hergibt."""

    enabled: bool = False
    # Die freigegebenen Scopes, in der Reihenfolge von ``ALL_SCOPES``.
    scopes: tuple[str, ...] = ()
    bereiche: tuple[str, ...] = ()
    gesetzt: bool = field(default=False, compare=False)

    def erlaubt_scope(self, scope: str) -> bool:
        """Ob die Organisation diesen Scope überhaupt hergibt.

        Ausdrücklich **ohne** die Scope-Hierarchie aus ``mcp/scopes.py``.
        Die sagt, was ein erteiltes *Recht* einschließt — wer schreiben darf,
        darf auch lesen. Was eine Organisation **freigeben will**, ist eine
        andere Frage: „planen ja, Standorte nein" ist eine sinnvolle
        Einstellung, und mit Hierarchie ließe sie sich nicht halten, weil
        ``convoy:write`` dann ``fleet:status`` mitbrächte."""
        return self.enabled and scope in self.scopes

    def erlaubt_werkzeug(self, werkzeug: str) -> bool:
        """Ob ein Werkzeug unter dieser Richtlinie benutzbar ist.

        Beide Achsen als Und: der Bereich muss frei sein **und** der Scope,
        den das Werkzeug verlangt."""
        if not self.enabled:
            return False
        if not areas.erlaubt(werkzeug, self.bereiche):
            return False
        noetig = scope_svc.required_for_tool(werkzeug)
        return noetig is None or noetig in self.scopes

    def zuschneiden(self, gewaehlt) -> list[str]:
        """Eine Scope-Menge auf das zurechtschneiden, was die Org hergibt."""
        if not self.enabled:
            return []
        return [s for s in scope_svc.ALL_SCOPES if s in set(gewaehlt) and s in self.scopes]


# ``convoy:read`` ist keine Wahl, sondern die Grundlage. Ein Token ohne ihn
# kommt an ``/mcp`` nicht einmal vorbei (``AuthSettings.required_scopes``), die
# Verbindung käme also gar nicht zustande. Eine eingeschaltete Organisation
# trägt ihn deshalb immer; gewählt wird, was **darüber hinaus** geht —
# Statusmeldungen und Schreiben. Womit eine Verbindung tatsächlich in
# Berührung kommt, entscheiden die Bereiche.
BASIS_SCOPE = scope_svc.SCOPE_READ

# Der Ausgangszustand einer Organisation: aus, und nichts freigegeben.
AUS = Policy()

# Was beim Einschalten vorgeschlagen wird, wenn niemand etwas anderes wählt:
# alle Bereiche, aber nur lesend. Der vorsichtige Teil sitzt bei den Scopes —
# ein Assistent, der nichts sehen darf, ist kein sicherer Ausgangszustand,
# sondern ein kaputter.
STANDARD = Policy(
    enabled=True,
    scopes=(scope_svc.SCOPE_READ,),
    bereiche=tuple(areas.STANDARD_BEREICHE),
)


def _liste(roh: str, erlaubte: tuple[str, ...]) -> tuple[str, ...]:
    """Eine gespeicherte Zeichenkette in eine geordnete, geprüfte Liste.

    Unbekannte Einträge fallen heraus statt durchzugehen. Sie entstehen, wenn
    ein Bereich oder Scope aus dem Code verschwindet, während die Zeile
    stehen bleibt — und eine Freigabe für etwas, das niemand mehr kennt,
    gehört nicht ausgewertet, sondern ignoriert."""
    vorhanden = set(roh.split())
    return tuple(e for e in erlaubte if e in vorhanden)


def aus_zeile(zeile: OrganizationMcpPolicy | None) -> Policy:
    """Eine gespeicherte Zeile in die geltende Richtlinie übersetzen.

    ``None`` heißt keine Zeile und damit aus. Öffentlich, weil das Adminportal
    Organisationen und Richtlinien in *einer* Abfrage verbindet (LEFT JOIN) und
    das Ergebnis selbst übersetzen muss — eine Abfrage je Organisation wäre bei
    dreißig Organisationen dreißig Rundreisen."""
    if zeile is None:
        return AUS
    return Policy(
        enabled=zeile.enabled,
        scopes=_liste(zeile.scopes or "", scope_svc.ALL_SCOPES),
        bereiche=_liste(zeile.bereiche or "", areas.ALL_BEREICHE),
        gesetzt=True,
    )


async def fuer_org(db: AsyncSession, org_id: uuid.UUID) -> Policy:
    """Die geltende Richtlinie einer Organisation. Keine Zeile heißt aus."""
    zeile = await db.get(OrganizationMcpPolicy, org_id)
    return aus_zeile(zeile)


async def fuer_orgs(
    db: AsyncSession, org_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Policy]:
    """Die Richtlinien mehrerer Organisationen in einem Zugriff.

    Für den Zustimmungsbildschirm: er zeigt alle Mitgliedschaften des
    Benutzers, und eine Abfrage je Zeile wäre eine Abfrage zu viel."""
    if not org_ids:
        return {}
    zeilen = (
        await db.execute(
            select(OrganizationMcpPolicy).where(
                OrganizationMcpPolicy.organization_id.in_(org_ids)
            )
        )
    ).scalars().all()
    gefunden = {z.organization_id: aus_zeile(z) for z in zeilen}
    return {org_id: gefunden.get(org_id, AUS) for org_id in org_ids}


async def setzen(
    db: AsyncSession,
    org_id: uuid.UUID,
    *,
    enabled: bool,
    scopes,
    bereiche,
    actor_id: uuid.UUID | None = None,
) -> Policy:
    """Die Richtlinie schreiben. Committet nicht — das tut der Aufrufer.

    Unbekannte Einträge fallen still heraus, statt die Anfrage abzuweisen:
    die Oberfläche schickt, was sie kennt, und ein Client, der sich etwas
    ausdenkt, bekommt dadurch nichts. Geordnet wird nach ``ALL_SCOPES`` und
    ``ALL_BEREICHE``, damit zwei gleiche Einstellungen auch gleich in der
    Zeile stehen.

    ``convoy:read`` kommt bei eingeschalteter Richtlinie dazu, auch wenn er
    nicht mitgeschickt wurde — ohne ihn gäbe es keine Verbindung, die die
    übrigen Freigaben nutzen könnte (siehe ``BASIS_SCOPE``)."""
    gewuenscht = set(scopes)
    if enabled:
        gewuenscht.add(BASIS_SCOPE)
    geprueft_scopes = [s for s in scope_svc.ALL_SCOPES if s in gewuenscht]
    geprueft_bereiche = [b for b in areas.ALL_BEREICHE if b in set(bereiche)]

    zeile = await db.get(OrganizationMcpPolicy, org_id)
    if zeile is None:
        zeile = OrganizationMcpPolicy(organization_id=org_id)
        db.add(zeile)
    zeile.enabled = enabled
    zeile.scopes = " ".join(geprueft_scopes)
    zeile.bereiche = " ".join(geprueft_bereiche)
    zeile.updated_by_id = actor_id
    await db.flush()
    return Policy(
        enabled=enabled,
        scopes=tuple(geprueft_scopes),
        bereiche=tuple(geprueft_bereiche),
        gesetzt=True,
    )
