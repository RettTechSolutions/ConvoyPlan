"""Betriebsart der Instanz: selbst gehostet oder Hosting-Server.

Derselbe Code läuft an beiden Stellen. Die Betriebsart schaltet keine
Funktionen frei und keine ab, sie entscheidet über **Standards**: was eine
Instanz von sich aus ankündigt, wohin Meldungen gehen und später, was das
Adminportal zeigt. Eine zweite Codebasis für Selbsthoster hieße doppelte Tests
und Migrationen, die auseinanderlaufen; ein Schalter heißt eine Zeile.

Unbekannte Werte gelten als ``selfhost``. Das ist die zurückhaltendere Seite:
eine Selbsthoster-Instanz, die sich als Hosting-Server ausgäbe, nähme
Meldungen fremder Instanzen an und kündigte sich bei Suchmaschinen an.
"""

import logging

from app.config import settings

logger = logging.getLogger(__name__)

SELFHOST = "selfhost"
HOSTING = "hosting"
BETRIEBSARTEN = (SELFHOST, HOSTING)


def aktuell() -> str:
    wert = (settings.instance_mode or "").strip().lower()
    if wert in BETRIEBSARTEN:
        return wert
    if wert:
        logger.warning("INSTANCE_MODE=%r ist unbekannt — gilt als %s", settings.instance_mode, SELFHOST)
    return SELFHOST


def ist_hosting() -> bool:
    return aktuell() == HOSTING
