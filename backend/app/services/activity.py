"""Portalnutzung in Echtzeit — wer ist gerade da, wie viel Last erzeugt er.

Bewusst ohne Datenbankschreibvorgang pro Request: die Middleware pflegt nur ein
kleines Dictionary im Prozess, der Metrik-Collector liest es im Sampling-
Intervall aus und schreibt einmal je Intervall eine Zeile. Bei einem Portal mit
Dutzenden Nutzern kostet das nichts, und die Datenbank sieht statt tausender
Update-Statements pro Stunde eine Handvoll.

Die Registry ist absichtlich flüchtig: Nach einem Neustart ist die
Momentaufnahme leer. Die *dauerhafte* Historie („wie viele Nutzer waren im
Portal") lebt in ``user_activity_days`` und wird vom Collector aus dieser
Registry heraus fortgeschrieben (siehe ``app.services.system_metrics``).
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

# Ein Nutzer gilt als „aktiv", wenn er innerhalb dieses Fensters einen Request
# gemacht hat. 5 Minuten decken normales Arbeiten im Portal ab, ohne dass eine
# geschlossene Registerkarte noch minutenlang mitzählt.
ACTIVE_WINDOW_SECONDS = 300


@dataclass
class UserActivity:
    user_id: uuid.UUID
    org_id: uuid.UUID | None
    first_seen: datetime
    last_seen: datetime
    requests: int = 0


@dataclass
class Counters:
    """Request-Zähler seit dem letzten ``drain()``."""

    requests: int = 0
    errors: int = 0
    duration_ms_total: float = 0.0

    @property
    def avg_response_ms(self) -> float | None:
        if not self.requests:
            return None
        return round(self.duration_ms_total / self.requests, 2)


# Die Registry wird aus dem Event-Loop-Thread beschrieben, kann aber (Uvicorn mit
# Worker-Threads für sync-Endpunkte) auch aus anderen Threads erreicht werden —
# deshalb ein Lock statt bloßem Vertrauen auf den GIL.
_lock = threading.Lock()
_users: dict[uuid.UUID, UserActivity] = {}
_counters = Counters()
# Nutzer, die seit dem letzten Flush aktiv waren — Grundlage für die
# Tagesstatistik. Wird beim Flush geleert, `_users` dagegen nur beim Verfallen.
_pending: dict[uuid.UUID, UserActivity] = {}


def touch(user_id: uuid.UUID, org_id: uuid.UUID | None = None) -> None:
    """Aktivität eines Benutzers vermerken (ein Request)."""
    now = datetime.now(timezone.utc)
    with _lock:
        entry = _users.get(user_id)
        if entry is None:
            _users[user_id] = UserActivity(user_id, org_id, now, now, 1)
        else:
            entry.last_seen = now
            entry.requests += 1
            if org_id is not None:
                entry.org_id = org_id

        pending = _pending.get(user_id)
        if pending is None:
            _pending[user_id] = UserActivity(user_id, org_id, now, now, 1)
        else:
            pending.last_seen = now
            pending.requests += 1
            if org_id is not None:
                pending.org_id = org_id


def record_request(*, status_code: int, duration_ms: float) -> None:
    """Einen abgeschlossenen HTTP-Request zählen."""
    with _lock:
        _counters.requests += 1
        # Nur Serverfehler zählen als Fehler — 401/404 sind im Normalbetrieb
        # erwartbar (abgelaufener Token, gelöschte Ressource) und würden die
        # Fehlerquote sonst dauerhaft unbrauchbar machen.
        if status_code >= 500:
            _counters.errors += 1
        _counters.duration_ms_total += duration_ms


def active_users(window_seconds: int = ACTIVE_WINDOW_SECONDS) -> list[UserActivity]:
    """Momentan aktive Benutzer (Aktivität innerhalb des Fensters)."""
    now = datetime.now(timezone.utc)
    with _lock:
        return [
            entry
            for entry in _users.values()
            if (now - entry.last_seen).total_seconds() <= window_seconds
        ]


def snapshot(window_seconds: int = ACTIVE_WINDOW_SECONDS) -> dict:
    """Momentaufnahme für die Live-Anzeige (ohne die Zähler zurückzusetzen)."""
    entries = active_users(window_seconds)
    with _lock:
        counters = Counters(_counters.requests, _counters.errors, _counters.duration_ms_total)
    return {
        "active_users": len(entries),
        "active_orgs": len({e.org_id for e in entries if e.org_id is not None}),
        "window_seconds": window_seconds,
        "requests_since_flush": counters.requests,
        "errors_since_flush": counters.errors,
        "avg_response_ms": counters.avg_response_ms,
    }


def drain() -> tuple[Counters, list[UserActivity]]:
    """Zähler und aufgelaufene Nutzeraktivität abholen und zurücksetzen.

    Ruft der Collector einmal je Intervall auf. Verfallene Einträge (älter als
    das Aktivfenster) werden dabei aus der Registry entfernt, damit sie in einem
    lang laufenden Prozess nicht unbegrenzt wächst.
    """
    global _counters
    now = datetime.now(timezone.utc)
    with _lock:
        counters, _counters = _counters, Counters()
        pending = list(_pending.values())
        _pending.clear()
        stale = [
            uid
            for uid, entry in _users.items()
            if (now - entry.last_seen).total_seconds() > ACTIVE_WINDOW_SECONDS
        ]
        for uid in stale:
            del _users[uid]
    return counters, pending


def reset() -> None:
    """Kompletter Reset — nur für Tests."""
    global _counters
    with _lock:
        _users.clear()
        _pending.clear()
        _counters = Counters()
