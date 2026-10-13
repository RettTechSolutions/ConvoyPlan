"""Module je Organisation: Freigabe durch den Betreiber, Anzeige für die Org.

Zwei Router in einer Datei, wie bei den Plänen. Die Regeln stehen in
``services/org_module.py``.

Freischalten darf nur der Superadmin — ein Modul ist eine Zusage des
Betreibers, kein Schalter der Organisation. Lesen darf jedes Mitglied: der
Org-Admin braucht es für die Reiter, und wer plant, soll sehen können, warum
ein Tracker nicht sendet.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import OrgCtx, get_org_context, require_superadmin
from app.database import get_db
from app.models.organization import Organization
from app.models.user import User
from app.services import audit, betriebsart, org_module, positionsverlauf

admin_router = APIRouter(prefix="/admin/modules", tags=["module"])
org_router = APIRouter(prefix="/org/modules", tags=["module"])


class ModulEintrag(BaseModel):
    modul: str
    label: str
    beschreibung: str


class ModulKatalog(BaseModel):
    module: list[ModulEintrag]
    # Was ohne Entscheidung gilt — damit das Portal erklären kann, warum eine
    # neue Organisation nichts oder alles hat.
    standard: bool
    betriebsart: str


class AdminModulZeile(BaseModel):
    organization_id: uuid.UUID
    organization_name: str
    organization_slug: str
    is_demo: bool
    module: dict[str, bool]


def _zeile(org: Organization, module: dict[str, bool]) -> AdminModulZeile:
    return AdminModulZeile(
        organization_id=org.id,
        organization_name=org.name,
        organization_slug=org.slug,
        is_demo=org.is_demo,
        module=module,
    )


# ── Betreiber ─────────────────────────────────────────────────────────────


@admin_router.get("/catalog", response_model=ModulKatalog)
async def katalog(_: User = Depends(require_superadmin)) -> ModulKatalog:
    return ModulKatalog(
        module=[
            ModulEintrag(modul=m.schluessel, label=m.label, beschreibung=m.beschreibung)
            for m in org_module.MODULE.values()
        ],
        standard=org_module.standard(),
        betriebsart=betriebsart.aktuell(),
    )


@admin_router.get("/organizations", response_model=list[AdminModulZeile])
async def liste(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
) -> list[AdminModulZeile]:
    orgs = (await db.execute(select(Organization).order_by(Organization.name))).scalars().all()
    module = await org_module.fuer_orgs(db, [o.id for o in orgs])
    return [_zeile(o, module[o.id]) for o in orgs]


@admin_router.put("/organizations/{org_id}", response_model=AdminModulZeile)
async def setzen(
    org_id: uuid.UUID,
    werte: dict[str, bool],
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_superadmin),
) -> AdminModulZeile:
    """Module freischalten oder sperren. Nur die genannten ändern sich."""
    org = await db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation nicht gefunden")
    unbekannt = sorted(set(werte) - set(org_module.MODULE))
    if unbekannt:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Unbekanntes Modul: {', '.join(unbekannt)}. Möglich: {', '.join(org_module.MODULE)}",
        )
    await org_module.setzen(db, org_id, werte, actor_id=current.id)
    await db.commit()
    # Die Aktionsseite hält Antwort und aktive Konvois kurz vor; ein Entzug
    # soll sofort wirken, nicht nach Ablauf des Zwischenspeichers.
    from app.api.routes import aktionsseite as aktionsseite_routes

    aktionsseite_routes._cache.clear()
    positionsverlauf.vergessen()

    await audit.record(
        db, audit.ORG_MODULES_SET, request=request, actor_id=current.id,
        actor_email=current.email, org_id=org_id, target_type="organization",
        target_id=org_id, detail=werte,
    )
    return _zeile(org, await org_module.fuer_org(db, org_id))


# ── Organisation ──────────────────────────────────────────────────────────


@org_router.get("", response_model=dict[str, bool])
async def eigene_module(
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    _user, org, _role = ctx
    return await org_module.fuer_org(db, org.id)
