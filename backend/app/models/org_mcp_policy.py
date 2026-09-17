"""Die MCP-Richtlinie einer Organisation.

Der Schalter im Adminportal entscheidet, ob es die Schnittstelle auf dieser
Instanz überhaupt gibt. Diese Zeile entscheidet, ob eine **Organisation** sie
benutzt, und in welchem Umfang. Beides ist nötig: der Betreiber der Instanz
und der Admin einer Organisation sind selten dieselbe Person, und wessen
Daten herausgehen, entscheidet nicht, wer die Software betreibt.

Keine Zeile heißt **aus**. Das ist der Grund für eine eigene Tabelle statt
zweier Spalten an ``organizations``: der Ausgangszustand steht damit an einer
Stelle (``services/org_mcp_policy.STANDARD``) und nicht in einem
``server_default``, das bei der nächsten Migration jemand anders liest.

Gespeichert wird, was freigegeben ist, als Liste — nicht als Höchstwert. Eine
Organisation, die Schreiben erlaubt aber Statusmeldungen nicht, ist eine
sinnvolle Einstellung (Planung per Assistent, Standorte bleiben draußen), und
in einer Rangfolge ließe sie sich nicht ausdrücken.
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class OrganizationMcpPolicy(Base):
    __tablename__ = "organization_mcp_policies"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    # Ob diese Organisation über die KI-Schnittstelle erreichbar ist.
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Die freigegebenen Scopes, durch Leerzeichen getrennt — dieselbe Form wie
    # in ``oauth_refresh_tokens.scopes`` und im Token selbst, damit beim
    # Vergleichen nichts umgerechnet werden muss.
    scopes: Mapped[str] = mapped_column(String(255), default="", server_default="")
    # Die freigegebenen Bereiche, ebenso durch Leerzeichen getrennt.
    bereiche: Mapped[str] = mapped_column(String(255), default="", server_default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    # Wer zuletzt daran gedreht hat. Nicht als Ersatz für das Audit-Log,
    # sondern damit die Oberfläche es ohne Suche im Log anzeigen kann.
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    organization: Mapped["Organization"] = relationship()
