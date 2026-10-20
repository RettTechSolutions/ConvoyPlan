"""Word-Vorlage für den Marschbefehl: Beispiel holen, eigene hochladen.

Regeln und Sandbox stehen in ``services/marschbefehl_vorlage.py``; gefüllt
wird sie im Export (``routing.export_docx``). Lesen darf jedes Mitglied,
austauschen nur der Org-Admin.
"""
import asyncio
import re
from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import OrgCtx, get_org_context
from app.api.guards import ROLE_ORDER
from app.database import get_db
from app.models.marschbefehl_vorlage import MarschbefehlVorlage
from app.services import audit
from app.services import marschbefehl_vorlage as vorlage_svc

router = APIRouter(prefix="/org/marschbefehl-vorlage", tags=["marschbefehl"])


class VorlageStatus(BaseModel):
    eigene: bool
    dateiname: str | None = None
    groesse: int | None = None
    hochgeladen_at: datetime | None = None


def _require_admin(role: str) -> None:
    if ROLE_ORDER.get(role, -1) < ROLE_ORDER["admin"]:
        raise HTTPException(status_code=403, detail="Org-Adminrechte erforderlich")


def _docx(inhalt: bytes, dateiname: str) -> Response:
    # Nur ASCII im einfachen Teil, der Rest über filename* — wie _attachment
    # beim Konvoi-Export.
    einfach = re.sub(r"[^A-Za-z0-9._-]+", "_", dateiname) or "Vorlage.docx"
    return Response(
        content=inhalt,
        media_type=vorlage_svc.DOCX_MIME,
        headers={
            "Content-Disposition": f"attachment; filename=\"{einfach}\"; filename*=UTF-8''{quote(dateiname, safe='')}",
        },
    )


async def laden(db: AsyncSession, org_id) -> MarschbefehlVorlage | None:
    return await db.get(MarschbefehlVorlage, org_id)


def _status(v: MarschbefehlVorlage | None) -> VorlageStatus:
    if v is None:
        return VorlageStatus(eigene=False)
    return VorlageStatus(eigene=True, dateiname=v.dateiname, groesse=v.groesse, hochgeladen_at=v.hochgeladen_at)


@router.get("", response_model=VorlageStatus)
async def status(ctx: OrgCtx = Depends(get_org_context), db: AsyncSession = Depends(get_db)):
    _, org, _ = ctx
    return _status(await laden(db, org.id))


@router.get("/felder")
async def felder(ctx: OrgCtx = Depends(get_org_context)):
    return vorlage_svc.feldkatalog()


@router.get("/beispiel")
async def beispiel(ctx: OrgCtx = Depends(get_org_context)):
    inhalt = await asyncio.get_running_loop().run_in_executor(None, vorlage_svc.beispielvorlage)
    return _docx(inhalt, "Marschbefehl-Vorlage.docx")


@router.get("/datei")
async def datei(ctx: OrgCtx = Depends(get_org_context), db: AsyncSession = Depends(get_db)):
    """Die hochgeladene Vorlage, unverändert — zum Weiterbearbeiten."""
    _, org, role = ctx
    _require_admin(role)
    v = await laden(db, org.id)
    if v is None:
        raise HTTPException(status_code=404, detail="Keine eigene Vorlage hochgeladen")
    return _docx(v.daten, v.dateiname)


@router.post("", response_model=VorlageStatus)
async def hochladen(
    request: Request,
    file: UploadFile = File(...),
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    user, org, role = ctx
    _require_admin(role)
    # Eins mehr lesen als erlaubt, damit eine zu große Datei als solche
    # erkannt wird, ohne sie ganz in den Speicher zu holen.
    inhalt = await file.read(vorlage_svc.MAX_BYTES + 1)
    try:
        await asyncio.get_running_loop().run_in_executor(None, vorlage_svc.pruefe, inhalt)
    except vorlage_svc.VorlageFehler as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    dateiname = (file.filename or "Marschbefehl-Vorlage.docx").rsplit("/", 1)[-1].rsplit("\\", 1)[-1][:200]
    if not dateiname.lower().endswith(".docx"):
        dateiname += ".docx"
    v = await laden(db, org.id)
    if v is None:
        v = MarschbefehlVorlage(organization_id=org.id)
        db.add(v)
    v.dateiname = dateiname
    v.groesse = len(inhalt)
    v.daten = inhalt
    v.hochgeladen_von_id = user.id
    v.hochgeladen_at = datetime.now().astimezone()
    await db.commit()
    await db.refresh(v)
    antwort = _status(v)
    await audit.record(
        db, audit.MARSCHBEFEHL_VORLAGE_SET, request=request, actor_id=user.id, actor_email=user.email,
        org_id=org.id, target_type="organization", target_id=str(org.id),
        detail={"dateiname": dateiname, "bytes": len(inhalt)},
    )
    return antwort


@router.delete("", response_model=VorlageStatus)
async def entfernen(
    request: Request, ctx: OrgCtx = Depends(get_org_context), db: AsyncSession = Depends(get_db)
):
    """Zurück zur Beispielvorlage."""
    user, org, role = ctx
    _require_admin(role)
    v = await laden(db, org.id)
    if v is not None:
        await db.delete(v)
        await db.commit()
        await audit.record(
            db, audit.MARSCHBEFEHL_VORLAGE_REMOVED, request=request, actor_id=user.id,
            actor_email=user.email, org_id=org.id, target_type="organization", target_id=str(org.id),
        )
    return _status(None)


async def vorlage_fuer(db: AsyncSession, org_id) -> bytes:
    """Die Vorlage, mit der eine Organisation exportiert — die eigene oder das Beispiel."""
    if org_id is not None:
        v = (await db.execute(
            select(MarschbefehlVorlage.daten).where(MarschbefehlVorlage.organization_id == org_id)
        )).scalar_one_or_none()
        if v is not None:
            return v
    return await asyncio.get_running_loop().run_in_executor(None, vorlage_svc.beispielvorlage)
