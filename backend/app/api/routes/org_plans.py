"""Pläne je Organisation: Verwaltung durch den Betreiber, Anzeige für die Org.

Zwei Router in einer Datei, wie bei den Meldungen: was der Betreiber setzt und
was die Organisation davon sieht, gehört zusammen gelesen. Die Regeln stehen
in ``services/org_plan.py``.

Setzen darf nur der Superadmin — ein Paket ist ein Vertrag mit dem Betreiber,
kein Schalter der Organisation. Die Organisation sieht ihren Plan, die
Nutzung und die Hinweise, aber keine Notiz des Betreibers.
"""
import uuid
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import OrgCtx, get_org_context, require_superadmin
from app.database import get_db
from app.models.org_plan import OrganizationPlan
from app.models.organization import Organization
from app.models.user import User
from app.services import audit, org_plan

admin_router = APIRouter(prefix="/admin/plans", tags=["plans"])
org_router = APIRouter(prefix="/org/plan", tags=["plans"])


class KatalogEintrag(BaseModel):
    plan: str
    label: str
    max_vehicles: int | None
    max_planners: int | None
    max_trackers: int | None
    laufzeit_tage: int | None


class PlanZustand(BaseModel):
    plan: str | None
    label: str | None
    max_vehicles: int | None
    max_planners: int | None
    max_trackers: int | None
    valid_until: date | None
    vehicles: int
    planners: int
    trackers: int
    vehicles_over: bool
    planners_over: bool
    trackers_over: bool
    expired: bool
    locked: bool
    days_left: int | None
    locked_from: date | None


class AdminPlanZeile(PlanZustand):
    organization_id: uuid.UUID
    organization_name: str
    organization_slug: str
    note: str | None
    updated_at: datetime | None


class PlanSetzen(BaseModel):
    plan: str
    # Fehlt ein Wert, gilt der Katalog. Ausdrücklich null heißt unbegrenzt —
    # deshalb ``model_fields_set`` statt ``is None`` (siehe unten).
    max_vehicles: int | None = Field(default=None, ge=0)
    max_planners: int | None = Field(default=None, ge=0)
    max_trackers: int | None = Field(default=None, ge=0)
    valid_until: date | None = None
    note: str | None = Field(default=None, max_length=2000)


def _zustand(zeile: OrganizationPlan | None, nutzung: org_plan.Nutzung) -> dict:
    z = org_plan.zustand(zeile, nutzung, org_plan.heute())
    katalog = org_plan.KATALOG.get(zeile.plan) if zeile else None
    return {
        "plan": zeile.plan if zeile else None,
        "label": (katalog.label if katalog else zeile.plan) if zeile else None,
        "max_vehicles": zeile.max_vehicles if zeile else None,
        "max_planners": zeile.max_planners if zeile else None,
        "max_trackers": zeile.max_trackers if zeile else None,
        "valid_until": zeile.valid_until if zeile else None,
        "vehicles": nutzung.fahrzeuge,
        "planners": nutzung.planer,
        "trackers": nutzung.tracker,
        "vehicles_over": z.fahrzeuge_ueber,
        "planners_over": z.planer_ueber,
        "trackers_over": z.tracker_ueber,
        "expired": z.abgelaufen,
        "locked": z.gesperrt,
        "days_left": z.tage_bis_ablauf,
        "locked_from": z.sperre_ab,
    }


# ── Betreiber ─────────────────────────────────────────────────────────────


@admin_router.get("/catalog", response_model=list[KatalogEintrag])
async def katalog(_: User = Depends(require_superadmin)) -> list[KatalogEintrag]:
    return [
        KatalogEintrag(
            plan=p.schluessel,
            label=p.label,
            max_vehicles=p.max_fahrzeuge,
            max_planners=p.max_planer,
            max_trackers=p.max_tracker,
            laufzeit_tage=p.laufzeit_tage,
        )
        for p in org_plan.KATALOG.values()
    ]


@admin_router.get("/organizations", response_model=list[AdminPlanZeile])
async def liste(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
) -> list[AdminPlanZeile]:
    """Alle Organisationen mit Plan und Nutzung — auch die ohne Plan.

    LEFT JOIN aus demselben Grund wie die MCP-Übersicht: keine Zeile ist der
    Normalfall, und eine Liste nur der Organisationen mit Plan ließe genau
    die weg, die noch keinen haben. Demo-Organisationen bleiben draußen.
    Überschreitungen und Ablauf zuerst — danach wird hier gesucht."""
    zeilen = (
        await db.execute(
            select(Organization, OrganizationPlan)
            .join(
                OrganizationPlan,
                OrganizationPlan.organization_id == Organization.id,
                isouter=True,
            )
            .where(Organization.is_demo.is_(False))
            .order_by(Organization.name)
        )
    ).all()
    nutzung = await org_plan.nutzung_alle(db)
    out = [
        AdminPlanZeile(
            organization_id=org.id,
            organization_name=org.name,
            organization_slug=org.slug,
            note=plan.note if plan else None,
            updated_at=plan.updated_at if plan else None,
            **_zustand(plan, nutzung.get(org.id, org_plan.Nutzung(0, 0))),
        )
        for org, plan in zeilen
    ]
    out.sort(
        key=lambda z: not (z.vehicles_over or z.planners_over or z.trackers_over or z.expired)
    )
    return out


@admin_router.put("/organizations/{org_id}", response_model=AdminPlanZeile)
async def setzen(
    org_id: uuid.UUID,
    data: PlanSetzen,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_superadmin),
) -> AdminPlanZeile:
    org = await db.get(Organization, org_id)
    if org is None or org.is_demo:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation nicht gefunden")
    katalog = org_plan.KATALOG.get(data.plan)
    if katalog is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Unbekannter Plan „{data.plan}“. Möglich: {', '.join(org_plan.KATALOG)}",
        )

    gesetzt = data.model_fields_set
    valid_until = data.valid_until
    if "valid_until" not in gesetzt and katalog.laufzeit_tage:
        # Letzter gebuchter Tag: heute zählt als erster.
        valid_until = org_plan.heute() + timedelta(days=katalog.laufzeit_tage - 1)

    zeile = await org_plan.fuer_org(db, org_id)
    if zeile is None:
        zeile = OrganizationPlan(organization_id=org_id)
        db.add(zeile)
    zeile.plan = katalog.schluessel
    zeile.max_vehicles = (
        data.max_vehicles if "max_vehicles" in gesetzt else katalog.max_fahrzeuge
    )
    zeile.max_planners = (
        data.max_planners if "max_planners" in gesetzt else katalog.max_planer
    )
    zeile.max_trackers = (
        data.max_trackers if "max_trackers" in gesetzt else katalog.max_tracker
    )
    zeile.valid_until = valid_until
    zeile.note = data.note
    zeile.updated_by_id = current.id
    await db.commit()
    await db.refresh(zeile)

    await audit.record(
        db, audit.ORG_PLAN_SET, request=request, actor_id=current.id,
        actor_email=current.email, org_id=org_id, target_type="organization",
        target_id=org_id,
        detail={
            "plan": zeile.plan,
            "max_vehicles": zeile.max_vehicles,
            "max_planners": zeile.max_planners,
            "max_trackers": zeile.max_trackers,
            "valid_until": zeile.valid_until.isoformat() if zeile.valid_until else None,
        },
    )
    return AdminPlanZeile(
        organization_id=org.id,
        organization_name=org.name,
        organization_slug=org.slug,
        note=zeile.note,
        updated_at=zeile.updated_at,
        **_zustand(zeile, await org_plan.nutzung(db, org_id)),
    )


@admin_router.delete("/organizations/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
async def entfernen(
    org_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_superadmin),
) -> None:
    """Plan entfernen: die Organisation läuft ohne Grenzen weiter."""
    zeile = await org_plan.fuer_org(db, org_id)
    if zeile is None:
        return
    plan = zeile.plan
    await db.delete(zeile)
    await db.commit()
    await audit.record(
        db, audit.ORG_PLAN_REMOVED, request=request, actor_id=current.id,
        actor_email=current.email, org_id=org_id, target_type="organization",
        target_id=org_id, detail={"plan": plan},
    )


# ── Organisation ──────────────────────────────────────────────────────────


@org_router.get("", response_model=PlanZustand)
async def eigener_plan(
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
) -> PlanZustand:
    """Plan, Nutzung und Hinweise der eigenen Organisation.

    Für jedes Mitglied lesbar: ein Planer, der das 26. Fahrzeug anlegt, soll
    den Hinweis sehen können, nicht nur der Admin. Ohne Plan kommen lauter
    leere Felder zurück — das Frontend zeigt dann nichts an."""
    _user, org, _role = ctx
    zeile = await org_plan.fuer_org(db, org.id)
    return PlanZustand(**_zustand(zeile, await org_plan.nutzung(db, org.id)))
