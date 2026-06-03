"""Entrypoint for the retention cron container: `python -m app.jobs.retention`.

Runs one purge pass and exits. The container loops with a sleep interval.
"""

import asyncio
import logging

from app.config import settings
from app.database import get_db_session
from app.services import retention

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("retention")


async def _main() -> None:
    if not settings.retention_enabled:
        logger.info("Retention disabled (RETENTION_ENABLED=false) — skipping.")
        return
    async with get_db_session() as db:
        await retention.run_all(db)


if __name__ == "__main__":
    asyncio.run(_main())
