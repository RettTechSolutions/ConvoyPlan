"""Organisations-Export — alles, was eine Organisation in ConvoyPlan hat, in einer Datei.

Wofür: Endet ein Hosting- oder Wartungsvertrag, bekommt die Organisation ihre
Daten zurück (Art. 28 Abs. 3 lit. g DSGVO, § 11 des AV-Vertrags), und sie kann
sie jederzeit selbst ziehen, etwa für einen Umzug auf die eigene Installation.
Die Exporte je Konvoi (GPX, JSON, PDF) und je Nutzer reichen dafür nicht: Es
fehlen Fahrzeugbestand, Mitglieder, Leitstellen, Schlüssel und Protokoll.

Vollständig heißt hier: Jede Tabelle, die der Organisation gehört, geht mit
**allen** Spalten hinaus. Die Spalten werden aus dem Modell gelesen, nicht von
Hand aufgezählt — eine neue Spalte landet damit von selbst im Export, statt
stillschweigend zu fehlen. Ausgenommen ist nur, was in ``_GEHEIM`` steht:
Passwort- und Schlüssel-Hashes, das MFA-Geheimnis und der Slug der
Tracking-Links (der Slug *ist* der Zugang; eine liegengebliebene Exportdatei
soll keinen laufenden Konvoi öffnen).

Nicht im Export, weil es nicht Daten der Organisation sind: Rückmeldungen an den
Betreiber (``feedback_reports``), Kontaktdaten aus der Demo (``demo_leads``),
kurzlebige OAuth-Codes und -Tokens.

Format: ein ZIP mit ``organisation.json``, den hochgeladenen Logos unter
``logos/``, den Fotos der Aktionsseiten unter ``beitraege/<bild>.webp`` und
ihren Videos unter ``beitraege/videos/<video>.mp4``. ``format`` und ``version``
im JSON sagen einem späteren Import, was er vor sich hat.

Gebaut wird in eine temporäre Datei, nicht im Speicher: Mit Videos werden das
schnell Hunderte Megabyte.
"""

from __future__ import annotations

import io
import json
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Request
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask
from fastapi.encoders import jsonable_encoder
from geoalchemy2.elements import WKBElement
from geoalchemy2.shape import to_shape
from shapely.geometry import mapping
from sqlalchemy import inspect, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_key import ApiKey
from app.models.audit_log import AuditLog
from app.models.convoy import Convoy, ConvoyVehicle
from app.models.leitstelle import Leitstelle
from app.models.org_mcp_policy import OrganizationMcpPolicy
from app.models.organization import Organization, UserOrganization
from app.models.ortungsgeraet import Ortungsgeraet
from app.models.public_tracker import (
    PublicTracker,
    PublicTrackerConvoy,
    PublicTrackerPhoto,
    PublicTrackerPhotoData,
    PublicTrackerPost,
    PublicTrackerVideo,
    VehiclePositionTrail,
)
from app.models.route import Route
from app.models.share_link import ConvoyShareLink
from app.models.system_metric import UserActivityDay
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.vehicle_position import VehiclePosition
from app.models.waypoint import Waypoint
from app.services import aktionsseite_video, audit

EXPORT_FORMAT = "convoyplan-organisation"
EXPORT_VERSION = 1
LOGOS_DIR = Path("/uploads/logos")

# Spalten, die nie in einen Export gehören, je Tabelle.
_GEHEIM: dict[str, frozenset[str]] = {
    "users": frozenset({"hashed_password", "mfa_secret", "token_version"}),
    "api_keys": frozenset({"key_hash"}),
    "convoy_share_links": frozenset({"password_hash", "slug"}),
    # Slug und Abruf-Token zusammen öffnen die Aktionsseite — wie beim Share-Link.
    "public_trackers": frozenset({"fetch_token_hash", "slug"}),
    # Einmal-Code und Gerätetoken: wer beides hätte, könnte als das Gerät senden.
    "ortungsgeraete": frozenset({"code_hash", "token_hash"}),
    # Beiträge ohne Absender und ohne Telegram-Kennungen (Gruppe, Nachrichten,
    # Fahrer, Presse) — die gehören Dritten, nicht der Organisation (Plan § 9).
    "public_tracker_posts": frozenset({
        "sender_telegram_id", "sender_name", "reviewed_by_telegram_id",
        "chat_id", "message_id", "card_message_id", "media_group_id",
    }),
}

# Welche Tabellen der Export abdeckt und welche er bewusst auslässt. Ein Test
# (tests/test_org_export.py) prüft gegen das Schema, dass jede Tabelle mit Bezug
# zu einer Organisation oder einem Konvoi in genau einer der beiden Mengen steht
# — eine neue Tabelle kann den Export so nicht unbemerkt umgehen.
EXPORTIERT = frozenset({
    "organizations", "user_organizations", "users", "vehicles", "convoys",
    "convoy_vehicles", "waypoints", "routes", "vehicle_positions",
    "convoy_share_links", "leitstellen", "api_keys", "organization_mcp_policies",
    "user_activity_days", "audit_logs",
    "public_trackers", "public_tracker_convoys", "vehicle_position_trail",
    "ortungsgeraete", "public_tracker_posts", "public_tracker_photos",
    "public_tracker_videos",
})
NICHT_EXPORTIERT = frozenset({
    "feedback_reports",      # Rückmeldungen an den Betreiber, nicht Daten der Organisation
    "demo_leads",            # Kontaktdaten aus der Demo, Vertriebsdaten des Betreibers
    "organization_plans",    # Paket und Notiz des Betreibers — Vertragsdaten, nicht Daten der Organisation
    "organization_modules",  # Freischaltungen des Betreibers — wie der Plan, kein Inhalt der Organisation
    "oauth_codes",           # kurzlebige Autorisierungscodes (Minuten)
    "oauth_refresh_tokens",  # Zugangstokens — gehören in keine Exportdatei
    # Rund um die Beiträge der Aktionsseiten: Der Bot-Token ist ein Geheimnis,
    # Codes leben Minuten, Presse und Gruppen sind Telegram-Kennungen Dritter.
    # Die Bilder selbst gehen als Dateien hinaus (``beitraege/``), nicht als Zeilen.
    "public_tracker_telegram", "public_tracker_codes", "public_tracker_chats",
    "public_tracker_presse", "public_tracker_photo_data",
})

# Schlüssel im Branding-JSON, die auf eine Datei in LOGOS_DIR zeigen.
_LOGO_SCHLUESSEL = ("logo_main", "logo_horizontal")


def _wert(value):
    if isinstance(value, WKBElement):
        return mapping(to_shape(value))
    return value


def zeile(obj) -> dict:
    """Alle Spalten eines Modellobjekts, ohne die Geheimnisse seiner Tabelle."""
    mapper = inspect(obj).mapper
    ausgenommen = _GEHEIM.get(mapper.local_table.name, frozenset())
    return {
        attr.key: _wert(getattr(obj, attr.key))
        for attr in mapper.column_attrs
        if attr.key not in ausgenommen
    }


async def _alle(db: AsyncSession, stmt) -> list:
    return list((await db.execute(stmt)).scalars().all())


def _logo_dateien(org: Organization) -> list[str]:
    if not org.branding:
        return []
    try:
        branding = json.loads(org.branding)
    except ValueError:
        return []
    if not isinstance(branding, dict):
        return []
    namen = [branding.get(k) for k in _LOGO_SCHLUESSEL]
    # Nur nackte Dateinamen — ein Pfad im Branding-JSON darf nicht aus
    # LOGOS_DIR herausführen.
    return [n for n in namen if isinstance(n, str) and n and Path(n).name == n]


async def build_org_export(db: AsyncSession, org: Organization) -> dict:
    """Das JSON-Dokument des Exports (noch nicht serialisiert)."""
    memberships = await _alle(
        db, select(UserOrganization).where(UserOrganization.organization_id == org.id)
    )
    user_ids = {m.user_id for m in memberships} | {org.owner_id}
    users = await _alle(db, select(User).where(User.id.in_(user_ids)))

    convoys = await _alle(db, select(Convoy).where(Convoy.organization_id == org.id))
    convoy_ids = [c.id for c in convoys]
    convoy_vehicles = await _alle(
        db, select(ConvoyVehicle).where(ConvoyVehicle.convoy_id.in_(convoy_ids))
    )
    # Fahrzeuge der Organisation — und solche, die in ihren Konvois fahren,
    # auch wenn sie keiner Organisation zugeordnet sind. Sonst verwiesen die
    # Zuordnungen im Export ins Leere.
    vehicle_ids_in_convoys = {cv.vehicle_id for cv in convoy_vehicles}
    vehicles = await _alle(
        db,
        select(Vehicle).where(or_(Vehicle.org_id == org.id, Vehicle.id.in_(vehicle_ids_in_convoys))),
    )

    bundle = {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "exported_at": datetime.now(timezone.utc),
        "organization": zeile(org),
        "memberships": [zeile(m) for m in memberships],
        "users": [zeile(u) for u in users],
        "vehicles": [zeile(v) for v in vehicles],
        "convoys": [zeile(c) for c in convoys],
        "convoy_vehicles": [zeile(cv) for cv in convoy_vehicles],
        "waypoints": [
            zeile(w) for w in await _alle(
                db,
                select(Waypoint).where(Waypoint.convoy_id.in_(convoy_ids))
                .order_by(Waypoint.convoy_id, Waypoint.order_index),
            )
        ],
        "routes": [
            zeile(r) for r in await _alle(db, select(Route).where(Route.convoy_id.in_(convoy_ids)))
        ],
        "vehicle_positions": [
            zeile(p) for p in await _alle(
                db, select(VehiclePosition).where(VehiclePosition.convoy_id.in_(convoy_ids))
            )
        ],
        "aktionsseiten": [
            zeile(t) for t in await _alle(
                db, select(PublicTracker).where(PublicTracker.organization_id == org.id)
            )
        ],
        "beitraege": [
            zeile(p) for p in await _alle(
                db,
                select(PublicTrackerPost)
                .join(PublicTracker, PublicTracker.id == PublicTrackerPost.tracker_id)
                .where(PublicTracker.organization_id == org.id)
                .order_by(PublicTrackerPost.taken_at),
            )
        ],
        "beitrag_bilder": [
            zeile(b) for b in await _alle(
                db,
                select(PublicTrackerPhoto)
                .join(PublicTrackerPost, PublicTrackerPost.id == PublicTrackerPhoto.post_id)
                .join(PublicTracker, PublicTracker.id == PublicTrackerPost.tracker_id)
                .where(PublicTracker.organization_id == org.id)
                .order_by(PublicTrackerPhoto.post_id, PublicTrackerPhoto.position),
            )
        ],
        "beitrag_videos": [
            zeile(v) for v in await _alle(
                db,
                select(PublicTrackerVideo)
                .join(PublicTrackerPost, PublicTrackerPost.id == PublicTrackerVideo.post_id)
                .join(PublicTracker, PublicTracker.id == PublicTrackerPost.tracker_id)
                .where(PublicTracker.organization_id == org.id)
                .order_by(PublicTrackerVideo.post_id),
            )
        ],
        "aktionsseiten_konvois": [
            zeile(tc) for tc in await _alle(
                db,
                select(PublicTrackerConvoy).where(PublicTrackerConvoy.convoy_id.in_(convoy_ids)),
            )
        ],
        "tracker": [
            zeile(g) for g in await _alle(
                db, select(Ortungsgeraet).where(Ortungsgeraet.organization_id == org.id)
            )
        ],
        "positionsverlauf": [
            zeile(p) for p in await _alle(
                db,
                select(VehiclePositionTrail)
                .where(VehiclePositionTrail.convoy_id.in_(convoy_ids))
                .order_by(VehiclePositionTrail.convoy_id, VehiclePositionTrail.recorded_at),
            )
        ],
        "share_links": [
            zeile(s) for s in await _alle(
                db, select(ConvoyShareLink).where(ConvoyShareLink.convoy_id.in_(convoy_ids))
            )
        ],
        "leitstellen": [
            zeile(ls) for ls in await _alle(
                db,
                select(Leitstelle).where(
                    or_(Leitstelle.org_id == org.id, Leitstelle.proposed_by_org_id == org.id)
                ),
            )
        ],
        "api_keys": [
            zeile(k) for k in await _alle(db, select(ApiKey).where(ApiKey.organization_id == org.id))
        ],
        "mcp_policy": next(
            (
                zeile(p) for p in await _alle(
                    db,
                    select(OrganizationMcpPolicy)
                    .where(OrganizationMcpPolicy.organization_id == org.id),
                )
            ),
            None,
        ),
        "activity_days": [
            zeile(a) for a in await _alle(
                db,
                select(UserActivityDay).where(UserActivityDay.org_id == org.id)
                .order_by(UserActivityDay.day),
            )
        ],
        "audit_log": [
            zeile(a) for a in await _alle(
                db, select(AuditLog).where(AuditLog.org_id == org.id).order_by(AuditLog.created_at)
            )
        ],
        "logos": _logo_dateien(org),
    }
    return bundle


async def beitrag_bilder(db: AsyncSession, org: Organization) -> list[tuple[str, bytes]]:
    """Die Fotos der Aktionsseiten als ``(Dateiname, WebP)``, in voller Größe.

    Benannt nach ``public_id`` — so stehen sie auch in ``beitrag_bilder`` im
    JSON. Die Bytes sind schon neu kodiert und ohne Metadaten (``aktionsseite_bild``)."""
    zeilen = await db.execute(
        select(PublicTrackerPhoto.public_id, PublicTrackerPhotoData.gross)
        .join(PublicTrackerPhotoData, PublicTrackerPhotoData.photo_id == PublicTrackerPhoto.id)
        .join(PublicTrackerPost, PublicTrackerPost.id == PublicTrackerPhoto.post_id)
        .join(PublicTracker, PublicTracker.id == PublicTrackerPost.tracker_id)
        .where(PublicTracker.organization_id == org.id)
    )
    return [(f"{pid}.webp", gross) for pid, gross in zeilen.all()]


async def beitrag_videos(db: AsyncSession, org: Organization) -> list[tuple[str, Path]]:
    """Die Videos der Aktionsseiten als ``(Dateiname, Pfad)`` — gelesen wird
    erst beim Schreiben ins ZIP."""
    kennungen = (await db.execute(
        select(PublicTrackerVideo.public_id)
        .join(PublicTrackerPost, PublicTrackerPost.id == PublicTrackerVideo.post_id)
        .join(PublicTracker, PublicTracker.id == PublicTrackerPost.tracker_id)
        .where(PublicTracker.organization_id == org.id)
    )).scalars().all()
    return [(f"{vid}.mp4", aktionsseite_video.pfad(vid)) for vid in kennungen]


def export_zip(
    bundle: dict, logos_dir: Path = LOGOS_DIR, bilder: list[tuple[str, bytes]] = (),
    videos: list[tuple[str, Path]] = (),
) -> bytes:
    """Das ZIP im Speicher — für Tests und kleine Exporte; ``export_response``
    schreibt mit ``zip_schreiben`` in eine Datei."""
    puffer = io.BytesIO()
    zip_schreiben(puffer, bundle, logos_dir, bilder, videos)
    return puffer.getvalue()


def zip_schreiben(
    ziel, bundle: dict, logos_dir: Path = LOGOS_DIR, bilder: list[tuple[str, bytes]] = (),
    videos: list[tuple[str, Path]] = (),
) -> None:
    """ZIP aus ``organisation.json``, den Logo-Dateien, die es noch gibt, den
    Fotos der Aktionsseiten (``bilder``, siehe ``beitrag_bilder``) und ihren
    Videos (``videos``, siehe ``beitrag_videos``).

    Ein Logo oder Video, das in den Daten steht, aber auf der Platte fehlt,
    wird im JSON unter ``logos_missing`` bzw. ``videos_missing`` vermerkt,
    statt den ganzen Export scheitern zu lassen.
    """
    fehlend = []
    videos_fehlend = []
    with zipfile.ZipFile(ziel, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in bundle.get("logos", []):
            pfad = logos_dir / name
            if pfad.is_file():
                zf.write(pfad, f"logos/{name}")
            else:
                fehlend.append(name)
        for name, inhalt in bilder:
            # WebP ist schon komprimiert — noch einmal Deflate kostet nur Zeit.
            zf.writestr(f"beitraege/{name}", inhalt, compress_type=zipfile.ZIP_STORED)
        for name, pfad in videos:
            if pfad.is_file():
                zf.write(pfad, f"beitraege/videos/{name}", compress_type=zipfile.ZIP_STORED)
            else:
                videos_fehlend.append(name)
        doc = {**bundle, "logos_missing": fehlend, "videos_missing": videos_fehlend}
        zf.writestr(
            "organisation.json",
            json.dumps(jsonable_encoder(doc), ensure_ascii=False, indent=2),
        )


def export_filename(org: Organization, at: datetime) -> str:
    return f"convoyplan-{org.slug}-{at:%Y-%m-%d}.zip"


async def export_response(
    db: AsyncSession, org: Organization, request: Request, actor: User
) -> StreamingResponse:
    """Export bauen, im Audit-Log vermerken und als Download ausliefern.

    Gemeinsamer Weg für den Inhaber (``/api/organizations/{id}/export``) und
    den Superadmin (``/api/admin/organizations/{id}/export``)."""
    bundle = await build_org_export(db, org)
    datei = tempfile.TemporaryFile()
    zip_schreiben(datei, bundle, bilder=await beitrag_bilder(db, org), videos=await beitrag_videos(db, org))
    groesse = datei.tell()
    datei.seek(0)
    await audit.record(
        db, audit.ORG_EXPORTED, request=request, actor_id=actor.id, actor_email=actor.email,
        org_id=org.id, target_type="organization", target_id=str(org.id),
        detail={"bytes": groesse, "convoys": len(bundle["convoys"])},
    )
    dateiname = export_filename(org, datetime.now(timezone.utc))


    def stuecke():
        while stueck := datei.read(1024 * 1024):
            yield stueck

    return StreamingResponse(
        stuecke(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{dateiname}"', "Content-Length": str(groesse)},
        background=BackgroundTask(datei.close),
    )
