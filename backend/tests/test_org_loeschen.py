"""Wer eine Organisation löscht, löscht auch ihre Konvois.

Bis Migration 0050 zeigte ``convoys.organization_id`` mit ``ON DELETE SET NULL``
auf die Organisation. Beide Lösch-Endpunkte — der des Superadmins und der des
Inhabers — löschten deshalb nur die Organisation; ihre Konvois samt Wegpunkten,
Route und Tracking-Links blieben ohne Zuordnung in der Datenbank. Erreichbar
waren sie danach für niemanden mehr (jeder Zugriff prüft die Organisation),
gelöscht aber auch nicht. Die Demo-Bereinigung umging das, indem sie Konvois
vorher selbst löschte; die beiden regulären Wege taten das nicht.

Die Tests laufen gegen die echte Datenbank: um genau die Fremdschlüssel-Regel
geht es, und die gibt es in einer Attrappe nicht.
"""

import uuid

import pytest
from sqlalchemy import delete, func, select, text

from app.api.routes import admin as admin_routes
from app.api.routes import organizations as org_routes
from app.database import AsyncSessionLocal, engine
from app.models.convoy import Convoy
from app.models.organization import Organization, UserOrganization
from app.models.share_link import ConvoyShareLink
from app.models.user import User
from app.models.waypoint import Waypoint
from tests.fake_request import fake_request


@pytest.fixture(autouse=True)
async def reset_db_engine():
    await engine.dispose()
    yield
    await engine.dispose()


@pytest.fixture
async def org_mit_konvoi():
    """Eine Organisation mit Haupt- und Unterkonvoi, Wegpunkt und Tracking-Link."""
    marker = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(email=f"loeschen-{marker}@test.invalid", hashed_password="x", is_active=True)
        db.add(user)
        await db.flush()
        org = Organization(name=f"Org {marker}", slug=f"org-{marker}", owner_id=user.id)
        db.add(org)
        await db.flush()
        db.add(UserOrganization(user_id=user.id, organization_id=org.id, role="admin"))
        haupt = Convoy(name=f"Verband {marker}", owner_id=user.id, organization_id=org.id)
        db.add(haupt)
        await db.flush()
        unter = Convoy(
            name=f"Teil {marker}", owner_id=user.id, organization_id=org.id,
            parent_convoy_id=haupt.id,
        )
        db.add(unter)
        await db.flush()
        db.add(Waypoint(convoy_id=haupt.id, name="Bereitstellungsraum", order_index=0))
        db.add(ConvoyShareLink(
            convoy_id=haupt.id, slug=f"l{marker}", scope="track", created_by_id=user.id,
        ))
        await db.commit()
        ids = {"user": user.id, "org": org.id, "konvois": [haupt.id, unter.id]}
    yield ids
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Convoy).where(Convoy.id.in_(ids["konvois"])))
        await db.execute(delete(Organization).where(Organization.id == ids["org"]))
        await db.execute(delete(User).where(User.id == ids["user"]))
        await db.commit()


async def _reste(konvoi_ids) -> dict[str, int]:
    async with AsyncSessionLocal() as db:
        return {
            "konvois": await db.scalar(
                select(func.count()).select_from(Convoy).where(Convoy.id.in_(konvoi_ids))
            ),
            "wegpunkte": await db.scalar(
                select(func.count()).select_from(Waypoint).where(Waypoint.convoy_id.in_(konvoi_ids))
            ),
            "links": await db.scalar(
                select(func.count()).select_from(ConvoyShareLink)
                .where(ConvoyShareLink.convoy_id.in_(konvoi_ids))
            ),
        }


async def test_superadmin_loescht_org_samt_konvois(org_mit_konvoi):
    async with AsyncSessionLocal() as db:
        superadmin = await db.get(User, org_mit_konvoi["user"])
        await admin_routes.admin_delete_organization(
            org_mit_konvoi["org"], fake_request("DELETE"), db, superadmin,
        )
    assert await _reste(org_mit_konvoi["konvois"]) == {"konvois": 0, "wegpunkte": 0, "links": 0}


async def test_inhaber_loescht_org_samt_konvois(org_mit_konvoi):
    async with AsyncSessionLocal() as db:
        inhaber = await db.get(User, org_mit_konvoi["user"])
        await org_routes.delete_organization(org_mit_konvoi["org"], db, inhaber)
    assert await _reste(org_mit_konvoi["konvois"]) == {"konvois": 0, "wegpunkte": 0, "links": 0}


async def test_regel_liegt_in_der_datenbank(org_mit_konvoi):
    """Auch ein Löschen am ORM vorbei — etwa aus einem Skript — nimmt die
    Konvois mit. Die Regel steht am Fremdschlüssel, nicht im Endpunkt."""
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("DELETE FROM organizations WHERE id = :id"), {"id": org_mit_konvoi["org"]}
        )
        await db.commit()
    assert (await _reste(org_mit_konvoi["konvois"]))["konvois"] == 0
