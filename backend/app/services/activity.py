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

# Nutzergruppen. Sie werden getrennt geführt, weil sie verschiedene Fragen
# beantworten: „wie viele Kunden arbeiten im Portal" (member) ist die Kennzahl,
# um die es geht — Demo-Besucher (demo) sind Interessenten, deren Konto nach
# Stunden wieder verschwindet, und der Superadmin (admin) ist der Betreiber
# selbst. Beide würden die Nutzerzahl sonst nach oben verfälschen.
KIND_MEMBER = "member"
KIND_DEMO = "demo"
KIND_ADMIN = "admin"
KINDS = (KIND_MEMBER, KIND_DEMO, KIND_ADMIN)


@dataclass
class UserActivity:
    user_id: uuid.UUID
    org_id: uuid.UUID | None
    first_seen: datetime
    last_seen: datetime
    requests: int = 0
    kind: str = KIND_MEMBER


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
# Schlüssel ist (Benutzer, Gruppe), nicht die Benutzer-ID allein: derselbe
# Superadmin kann im Admin-Portal *und* in einer Organisation arbeiten, und
# beides soll getrennt gezählt werden.
_Key = tuple[uuid.UUID, str]
_users: dict[_Key, UserActivity] = {}
_counters = Counters()
# Nutzer, die seit dem letzten Flush aktiv waren — Grundlage für die
# Tagesstatistik. Wird beim Flush geleert, `_users` dagegen nur beim Verfallen.
_pending: dict[_Key, UserActivity] = {}


def touch(
    user_id: uuid.UUID, org_id: uuid.UUID | None = None, kind: str = KIND_MEMBER
) -> None:
    """Aktivität eines Benutzers vermerken (ein Request)."""
    now = datetime.now(timezone.utc)
    if kind not in KINDS:
        kind = KIND_MEMBER
    key = (user_id, kind)
    with _lock:
        for registry in (_users, _pending):
            entry = registry.get(key)
            if entry is None:
                registry[key] = UserActivity(user_id, org_id, now, now, 1, kind)
            else:
                entry.last_seen = now
                entry.requests += 1
                if org_id is not None:
                    entry.org_id = org_id


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


def active_users(
    window_seconds: int = ACTIVE_WINDOW_SECONDS, kind: str | None = None
) -> list[UserActivity]:
    """Momentan aktive Benutzer (Aktivität innerhalb des Fensters).

    Ohne ``kind`` kommen alle Gruppen zurück; mit ``kind`` nur die gewünschte.
    """
    now = datetime.now(timezone.utc)
    with _lock:
        return [
            entry
            for entry in _users.values()
            if (now - entry.last_seen).total_seconds() <= window_seconds
            and (kind is None or entry.kind == kind)
        ]


def count_by_kind(entries: list[UserActivity]) -> dict[str, int]:
    """Aktive Benutzer je Gruppe — fehlende Gruppen als 0, damit die Kennzahlen
    stabile Felder haben."""
    counts = {k: 0 for k in KINDS}
    for entry in entries:
        counts[entry.kind] = counts.get(entry.kind, 0) + 1
    return counts


def snapshot(window_seconds: int = ACTIVE_WINDOW_SECONDS) -> dict:
    """Momentaufnahme für die Live-Anzeige (ohne die Zähler zurückzusetzen)."""
    entries = active_users(window_seconds)
    counts = count_by_kind(entries)
    with _lock:
        counters = Counters(_counters.requests, _counters.errors, _counters.duration_ms_total)
    return {
        # `active_users` meint die echten Portalnutzer — Demo und Admin stehen
        # daneben, damit die Zahl nicht durch Probesitzungen aufgebläht wird.
        "active_users": counts[KIND_MEMBER],
        "active_demo_users": counts[KIND_DEMO],
        "active_admin_users": counts[KIND_ADMIN],
        "active_orgs": len(
            {e.org_id for e in entries if e.org_id is not None and e.kind == KIND_MEMBER}
        ),
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
            key
            for key, entry in _users.items()
            if (now - entry.last_seen).total_seconds() > ACTIVE_WINDOW_SECONDS
        ]
        for key in stale:
            del _users[key]
    return counters, pending


def reset() -> None:
    """Kompletter Reset — nur für Tests."""
    global _counters
    with _lock:
        _users.clear()
        _pending.clear()
        _counters = Counters()
