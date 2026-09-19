"""Fehler melden, Wünsche einreichen — und beides im Adminportal aufbereiten.

Zwei Router in einer Datei, weil es *ein* Vorgang ist: was hier entgegengenommen
wird, wird zehn Zeilen weiter unten wieder ausgegeben. Der Alternativweg wäre
gewesen, die Adminseite in `admin.py` zu legen; die Datei hat 2500 Zeilen und
jede Änderung an den Meldungen läge dann an zwei Orten.

**Wer melden darf:** jedes angemeldete Mitglied einer Organisation, Demo-Konten
eingeschlossen. Gerade die laufen als erste in das, was noch nicht rund ist, und
ein Melde-Dialog, der ausgerechnet dort nicht aufgeht, verschenkt die Hälfte der
Rückmeldungen. Ein Superadmin ohne Organisationssitzung darf ebenfalls melden —
er sitzt im selben Portal.

**Wer liest:** ausschließlich Superadmins. Eine Meldung trägt Seiten-URL,
Browser-Kennung und womöglich ein Bildschirmfoto mit Einsatzdaten darauf; das
ist nichts, was eine andere Organisation sehen soll, und auch nichts, was der
Melder später noch einmal aufrufen können muss.

Die Grenze sitzt an der Missbrauchsseite, nicht an der Bequemlichkeit: zehn
Meldungen je Stunde und IP. Wer wirklich zehn Fehler in einer Stunde findet, hat
ein größeres Problem als das Limit — und dafür gibt es das Telefon.
"""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_person, get_org_context, oauth2_optional, require_superadmin
from app.database import get_db
from app.models.feedback import (
    FeedbackReport,
    KIND_BUG,
    KIND_FEATURE,
    STATUS_NEU,
    STATUSES,
    STATUSES_ABGESCHLOSSEN,
)
from app.models.organization import Organization
from app.models.user import User
from app.schemas.feedback import (
    FeedbackCreate,
    FeedbackReportOut,
    FeedbackStats,
    FeedbackSubmitted,
    FeedbackUpdate,
)
from app.services import audit
from app.services import feedback as feedback_svc
from app.services.rate_limit import rate_limit

router = APIRouter(prefix="/feedback", tags=["feedback"])
admin_router = APIRouter(prefix="/admin/feedback", tags=["feedback", "admin"])


# ── Melden ────────────────────────────────────────────────────────────────────


class Melder:
    """Wer meldet — mit Organisation, wenn es eine gibt."""

    def __init__(self, user: User, org: Organization | None, role: str | None):
        self.user = user
        self.org = org
        self.role = role


async def melder(
    request: Request,
    token: str | None = Depends(oauth2_optional),
    db: AsyncSession = Depends(get_db),
) -> Melder:
    """Die Organisationssitzung, und wenn es keine gibt, die Person.

    Zwei Wege, weil der Melde-Dialog an zwei Stellen hängt: in der Anwendung
    unter `/o/<slug>/…`, wo eine Organisation gewählt ist, und im Adminportal,
    wo keine gewählt ist. Ein `get_org_context` allein wiese den Betreiber ab,
    ein `get_current_person` allein verlöre bei allen anderen die Organisation
    — und damit die Angabe, in welcher Umgebung der Fehler auftrat.

    Kein API-Key: eine Meldung ist die Aussage eines Menschen.
    """
    try:
        user, org, role = await get_org_context(request, token, None, db)
        return Melder(user, org, role)
    except HTTPException as exc:
        # 401/403 heißt hier nur „keine Organisationssitzung" — die Person kann
        # trotzdem angemeldet sein. Alles andere (409 bei mehreren Konten im
        # Browser, 404) ist eine Antwort und keine Zwischenstufe.
        if exc.status_code not in (401, 403):
            raise
    user = await get_current_person(request, token, db)
    return Melder(user, None, None)


@router.post(
    "",
    response_model=FeedbackSubmitted,
    status_code=201,
    dependencies=[Depends(rate_limit("feedback", max_attempts=10, window_seconds=3600, count_attempts=True))],
)
async def submit_feedback(
    data: FeedbackCreate,
    request: Request,
    ctx: Melder = Depends(melder),
    db: AsyncSession = Depends(get_db),
) -> FeedbackSubmitted:
    """Eine Meldung entgegennehmen.

    Das Bild wird **vor** dem Schreiben der Zeile geprüft und **danach**
    abgelegt: ein ungültiges Bild soll keine halbe Meldung hinterlassen, und
    der Dateiname trägt die Kennung der Zeile, die es dafür erst geben muss.
    Scheitert das Ablegen, bleibt die Meldung ohne Bild bestehen — der Text ist
    das, worauf es ankommt.
    """
    bild = feedback_svc.decode_screenshot(data.screenshot) if data.screenshot else None

    bericht = FeedbackReport(
        id=uuid.uuid4(),
        kind=data.kind,
        title=data.title,
        description=data.description,
        severity=data.severity,
        # Der Betreiber fängt bei der Einschätzung des Melders an und zieht sie
        # beim Sichten gerade. Auf „normal" zu starten hieße, eine als kritisch
        # gemeldete Störung erst einmal einzuebnen.
        priority=data.severity,
        status=STATUS_NEU,
        org_id=ctx.org.id if ctx.org else None,
        org_slug=ctx.org.slug if ctx.org else None,
        org_name=ctx.org.name if ctx.org else None,
        user_id=ctx.user.id,
        reporter_email=ctx.user.email,
        reporter_name=ctx.user.full_name or None,
        reporter_role=ctx.role,
        is_demo=bool(getattr(ctx.user, "is_demo", False)),
        page_url=data.page_url,
        user_agent=data.user_agent,
        app_version=data.app_version,
        viewport=data.viewport,
    )
    if bild is not None:
        rohdaten, endung = bild
        bericht.screenshot_name = await feedback_svc.store_screenshot(bericht.id, rohdaten, endung)
        bericht.screenshot_bytes = len(rohdaten)

    db.add(bericht)
    await db.commit()
    await db.refresh(bericht)

    await audit.record(
        db,
        audit.FEEDBACK_SUBMITTED,
        request=request,
        actor_id=ctx.user.id,
        actor_email=ctx.user.email,
        org_id=ctx.org.id if ctx.org else None,
        target_type="feedback_report",
        target_id=str(bericht.id),
        detail={"kind": bericht.kind, "severity": bericht.severity},
    )
    return FeedbackSubmitted(id=bericht.id, kind=bericht.kind, created_at=bericht.created_at)


# ── Lesen und bearbeiten (Superadmin) ────────────────────────────────────────


def _out(bericht: FeedbackReport, *, handled_by_email: str | None = None) -> FeedbackReportOut:
    return FeedbackReportOut(
        id=bericht.id,
        kind=bericht.kind,
        title=bericht.title,
        description=bericht.description,
        severity=bericht.severity,
        priority=bericht.priority,
        status=bericht.status,
        org_id=bericht.org_id,
        org_slug=bericht.org_slug,
        org_name=bericht.org_name,
        org_vorhanden=bericht.org_id is not None,
        user_id=bericht.user_id,
        reporter_email=bericht.reporter_email,
        reporter_name=bericht.reporter_name,
        reporter_role=bericht.reporter_role,
        is_demo=bericht.is_demo,
        page_url=bericht.page_url,
        user_agent=bericht.user_agent,
        app_version=bericht.app_version,
        viewport=bericht.viewport,
        has_screenshot=bool(bericht.screenshot_name),
        screenshot_bytes=bericht.screenshot_bytes,
        admin_note=bericht.admin_note,
        handled_by_email=handled_by_email,
        handled_at=bericht.handled_at,
        created_at=bericht.created_at,
        updated_at=bericht.updated_at,
    )


async def _bearbeiter_adressen(db: AsyncSession, berichte: list[FeedbackReport]) -> dict:
    """Die Adressen der Bearbeiter in *einer* Abfrage.

    Sonst wäre die Liste ein N+1: 200 Meldungen, 200 Abfragen nach demselben
    halben Dutzend Superadmins.
    """
    ids = {b.handled_by_id for b in berichte if b.handled_by_id}
    if not ids:
        return {}
    result = await db.execute(select(User.id, User.email).where(User.id.in_(ids)))
    return {row[0]: row[1] for row in result.all()}


@admin_router.get("", response_model=list[FeedbackReportOut])
async def list_feedback(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
    kind: str | None = Query(default=None),
    status: str | None = Query(default=None),
    offen: bool = Query(default=False, description="Nur, was noch auf dem Tisch liegt"),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> list[FeedbackReportOut]:
    abfrage = select(FeedbackReport)
    if kind in (KIND_BUG, KIND_FEATURE):
        abfrage = abfrage.where(FeedbackReport.kind == kind)
    if status in STATUSES:
        abfrage = abfrage.where(FeedbackReport.status == status)
    if offen:
        abfrage = abfrage.where(FeedbackReport.status.notin_(STATUSES_ABGESCHLOSSEN))
    abfrage = abfrage.order_by(FeedbackReport.created_at.desc()).limit(limit).offset(offset)

    berichte = list((await db.execute(abfrage)).scalars().all())
    adressen = await _bearbeiter_adressen(db, berichte)
    return [_out(b, handled_by_email=adressen.get(b.handled_by_id)) for b in berichte]


@admin_router.get("/stats", response_model=FeedbackStats)
async def feedback_stats(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
) -> FeedbackStats:
    """Die Kennzahlen über der Liste — in einer Abfrage statt in sieben.

    Gezählt wird nach Art und Status gruppiert; alles Weitere fällt in Python
    aus derselben Tabelle. Sieben `SELECT count(*)` wären lesbarer gewesen und
    sieben Rundreisen für eine Kachelzeile.
    """
    zeilen = (
        await db.execute(
            select(
                FeedbackReport.kind,
                FeedbackReport.status,
                FeedbackReport.priority,
                func.count().label("anzahl"),
            ).group_by(FeedbackReport.kind, FeedbackReport.status, FeedbackReport.priority)
        )
    ).all()

    gesamt = offen = bugs_offen = features_offen = kritisch_offen = 0
    je_status: dict[str, int] = {s: 0 for s in STATUSES}
    for kind, status, priority, anzahl in zeilen:
        gesamt += anzahl
        je_status[status] = je_status.get(status, 0) + anzahl
        if status in STATUSES_ABGESCHLOSSEN:
            continue
        offen += anzahl
        if kind == KIND_BUG:
            bugs_offen += anzahl
        elif kind == KIND_FEATURE:
            features_offen += anzahl
        if priority == "kritisch":
            kritisch_offen += anzahl

    seit = datetime.now(timezone.utc) - timedelta(days=7)
    neu_7_tage = (
        await db.execute(
            select(func.count()).select_from(FeedbackReport).where(FeedbackReport.created_at >= seit)
        )
    ).scalar_one()

    return FeedbackStats(
        gesamt=gesamt,
        offen=offen,
        bugs_offen=bugs_offen,
        features_offen=features_offen,
        kritisch_offen=kritisch_offen,
        neu_7_tage=neu_7_tage,
        je_status=je_status,
    )


async def _hole(db: AsyncSession, report_id: uuid.UUID) -> FeedbackReport:
    bericht = await db.get(FeedbackReport, report_id)
    if bericht is None:
        raise HTTPException(status_code=404, detail="Meldung nicht gefunden")
    return bericht


@admin_router.get("/{report_id}", response_model=FeedbackReportOut)
async def get_feedback(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
) -> FeedbackReportOut:
    bericht = await _hole(db, report_id)
    adressen = await _bearbeiter_adressen(db, [bericht])
    return _out(bericht, handled_by_email=adressen.get(bericht.handled_by_id))


@admin_router.get("/{report_id}/screenshot")
async def get_feedback_screenshot(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    """Das Bildschirmfoto ausliefern.

    Über den Endpunkt und nicht über ein statisch gemountetes Verzeichnis: auf
    einem Screenshot aus dem Einsatz stehen Einsatzdaten, und ein ratbarer Pfad
    unter `/uploads/` wäre für die ganze Instanz lesbar.
    """
    bericht = await _hole(db, report_id)
    if not bericht.screenshot_name:
        raise HTTPException(status_code=404, detail="Zu dieser Meldung gibt es kein Bildschirmfoto")
    pfad = feedback_svc.screenshot_path(bericht.screenshot_name)
    if not pfad.is_file():
        # Die Zeile weiß von einem Bild, das Volume nicht — etwa nach einer
        # Wiederherstellung der Datenbank ohne das Volume. Kein 500: die
        # Meldung selbst ist in Ordnung.
        raise HTTPException(status_code=404, detail="Das Bildschirmfoto liegt nicht mehr vor")
    return FileResponse(
        pfad,
        media_type=feedback_svc.medientyp(bericht.screenshot_name),
        headers={"Cache-Control": "private, max-age=300"},
    )


@admin_router.patch("/{report_id}", response_model=FeedbackReportOut)
async def update_feedback(
    report_id: uuid.UUID,
    data: FeedbackUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_superadmin),
) -> FeedbackReportOut:
    bericht = await _hole(db, report_id)
    vorher = {"status": bericht.status, "priority": bericht.priority}

    felder = data.model_dump(exclude_unset=True)
    for feld in ("status", "priority", "admin_note"):
        if feld in felder and felder[feld] is not None:
            setattr(bericht, feld, felder[feld])

    # Wer zuletzt angefasst hat, steht in der Zeile — nicht nur im Audit-Log.
    # Im Portal ist das die Antwort auf „kümmert sich da schon jemand drum?",
    # und die soll man nicht im Log suchen müssen.
    bericht.handled_by_id = admin.id
    bericht.handled_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(bericht)

    await audit.record(
        db,
        audit.FEEDBACK_UPDATED,
        request=request,
        actor_id=admin.id,
        actor_email=admin.email,
        target_type="feedback_report",
        target_id=str(bericht.id),
        detail={"vorher": vorher, "nachher": {"status": bericht.status, "priority": bericht.priority}},
    )
    return _out(bericht, handled_by_email=admin.email)


@admin_router.delete("/{report_id}", status_code=204)
async def delete_feedback(
    report_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_superadmin),
) -> None:
    bericht = await _hole(db, report_id)
    name = bericht.screenshot_name
    titel, art = bericht.title, bericht.kind
    await db.delete(bericht)
    await db.commit()
    # Erst nach dem Commit: ein gelöschtes Bild zu einer Zeile, die es noch
    # gibt, wäre der schlechtere von beiden Fehlern.
    feedback_svc.delete_screenshot(name)

    await audit.record(
        db,
        audit.FEEDBACK_DELETED,
        request=request,
        actor_id=admin.id,
        actor_email=admin.email,
        target_type="feedback_report",
        target_id=str(report_id),
        detail={"kind": art, "title": titel},
    )
