"""Wann ein Tracker schweigen muss, obwohl sein Konvoi läuft.

Plansperre der Organisation (``org_plan.ist_gesperrt``), fehlende Lizenz der
Instanz oder nicht freigeschaltetes Modul *Tracker* (``org_module``). Zwei Leser
fragen dieselbe Regel: die Anweisung an das Gerät (``api/routes/geraete.py``)
und die Zählung für den Updater (``anwesenheit.aktive_tracker``) — ein Tracker,
der schweigen muss, hält auch kein Update auf. Wer hier eine Bedingung ergänzt,
ändert beide.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import org_module, org_plan


async def gesperrt(db: AsyncSession, org_id: uuid.UUID) -> bool:
    # Spät importiert: die Middleware zieht beim Import Einstellungen und Lizenzprüfung nach.
    from app.middleware.license_guard import is_licensed

    return (
        await org_plan.ist_gesperrt(db, org_id)
        or not await is_licensed()
        or not await org_module.freigegeben(db, org_id, org_module.TRACKER)
    )
