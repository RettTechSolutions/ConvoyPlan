"""Nahfunk: die Begleit-App meldet über den Tracker im Fahrzeug (E15 im Tracker-Plan).

Erreicht das Telefon der Besatzung die Instanz nicht, gibt die App Status, Stärke und
Betriebsstoff per Bluetooth an den festen Tracker ihres Fahrzeugs. Der reicht sie mit
``POST /api/geraete/meldungen`` über sein eigenes Modem weiter. Vertrag: ConvoyPlan-Tracker,
``docs/PROTOKOLL.md``, „Nahfunk zur Begleit-App" und ``meldungen``.

Wer über den Tracker melden darf, entscheidet die Instanz mit einem **Schlüssel**. Den
bekommen zwei Seiten: der Tracker mit seiner Anweisung (``nahfunk``) und die App über den
Fahrer-Link, und zwar nur die Verbindung, die das Fahrzeug belegt (``track_ws``). Beide
beweisen sich damit gegenseitig, bevor eine Meldung fließt.

Der Schlüssel wird **nicht gespeichert, sondern abgeleitet**: HMAC über das Geheimnis der
Instanz, das Gerät, das Fahrzeug, die laufenden Konvois und wer das Fahrzeug belegt. Ändert
sich eins davon — neuer Konvoi, andere Besatzung, anderes Fahrzeug —, gilt ein neuer, ohne
dass irgendwo etwas weggeräumt werden muss. Und Tracker und App bekommen zwangsläufig
denselben, weil beide aus denselben Zutaten gerechnet werden. Ein Neustart verliert nichts:
die Belegung meldet sich mit dem Keepalive binnen einer Minute zurück, dann stimmt auch der
Schlüssel wieder.

Hier stehen nur die Regeln, ohne Datenbank und ohne Netz (``tests/test_nahfunk.py``).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

#: Meldungen je Aufruf von ``meldungen`` (so viele puffert der Tracker).
MELDUNGEN_MAX = 16
#: Älter übergeben: abgelehnt. Ein technischer Halt eine halbe Stunde zu spät ist eine
#: falsche Lage und ein falscher Alarm.
VERALTET = timedelta(minutes=30)
#: Was der Tracker weiterreicht. Positionen nicht: die schickt er selbst.
ARTEN = ("status", "staerke", "betriebsstoff")
_CLIENT_ID_MAX = 64

_ETIKETT_SCHLUESSEL = b"convoyplan-nahfunk-1 schluessel"
_ETIKETT_KENNUNG = b"convoyplan-nahfunk-1 kennung"


def _geheimnis(instanz_geheimnis: str) -> bytes:
    # Eigener Teilschlüssel: Ein Nahfunk-Schlüssel verrät nichts über das, womit die
    # Instanz ihre Sitzungen signiert.
    return hashlib.sha256(b"nahfunk|" + instanz_geheimnis.encode()).digest()


def zugang(
    instanz_geheimnis: str,
    geraet_id: Any,
    fahrzeug_id: Any,
    konvois: Iterable[Any],
    halter: Iterable[str],
) -> dict[str, Any]:
    """Der Zugang für Tracker und App: ``{kennung, schluessel, gueltig_bis}``.

    ``halter``: die Gerätekennungen, die das Fahrzeug in den laufenden Konvois belegen.
    Leer, solange keine Besatzung verbunden ist — dann passt der Schlüssel zu niemandem,
    und das ist richtig so. ``gueltig_bis`` ist ``None``: Der Zugang gilt, bis sich eine
    der Zutaten ändert, nicht bis zu einer Uhrzeit.
    """
    basis = "|".join(
        [
            str(geraet_id),
            str(fahrzeug_id),
            ",".join(sorted(str(k) for k in konvois)),
            ",".join(sorted(set(halter))),
        ]
    ).encode()
    g = _geheimnis(instanz_geheimnis)
    schluessel = hmac.new(g, _ETIKETT_SCHLUESSEL + b"|" + basis, hashlib.sha256).digest()
    kennung = hmac.new(g, _ETIKETT_KENNUNG + b"|" + basis, hashlib.sha256).digest()[:4].hex()
    return {
        "kennung": kennung,
        "schluessel": base64.b64encode(schluessel).decode(),
        "gueltig_bis": None,
    }


def ws_nachricht(vehicle_id: Any, zugang_: dict[str, Any] | None) -> dict[str, Any]:
    """Der Frame ``nahfunk`` für die App. Ohne Zugang zieht ``kennung: null`` ihn zurück."""
    if zugang_ is None:
        return {"type": "nahfunk", "vehicle_id": str(vehicle_id), "kennung": None}
    return {"type": "nahfunk", "vehicle_id": str(vehicle_id), **zugang_}


@dataclass(frozen=True)
class Meldung:
    client_id: str
    art: str | None
    #: Der Frame der Besatzung, wie am WebSocket — die ``vehicle_id`` setzt die Instanz.
    frame: dict[str, Any] | None
    erhalten: datetime | None


def meldungen_lesen(roh: Any) -> list[Meldung]:
    """Liest den Körper von ``meldungen``. ``ValueError`` (→ 400) nur, wenn ``meldungen``
    keine Liste ist oder zu lang. Einträge ohne lesbare ``client_id`` fallen weg — auf sie
    gibt es kein Ergebnis, weil der Tracker es keiner Meldung zuordnen könnte."""
    if not isinstance(roh, list) or len(roh) > MELDUNGEN_MAX:
        raise ValueError(f"meldungen: Liste mit höchstens {MELDUNGEN_MAX} Einträgen")
    aus: list[Meldung] = []
    for eintrag in roh:
        if not isinstance(eintrag, dict):
            continue
        cid = eintrag.get("client_id")
        if not isinstance(cid, str) or not 0 < len(cid) <= _CLIENT_ID_MAX:
            continue
        frame = eintrag.get("frame")
        art = frame.get("type") if isinstance(frame, dict) else None
        aus.append(
            Meldung(
                client_id=cid,
                art=art if art in ARTEN else None,
                frame=dict(frame) if isinstance(frame, dict) else None,
                erhalten=_zeit(eintrag.get("erhalten")),
            )
        )
    return aus


def _zeit(roh: Any) -> datetime | None:
    if not isinstance(roh, str):
        return None
    try:
        t = datetime.fromisoformat(roh.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t.astimezone(timezone.utc) if t.tzinfo is not None else None


def veraltet(m: Meldung, jetzt: datetime) -> bool:
    return m.erhalten is not None and jetzt - m.erhalten > VERALTET


def abgelehnt(client_id: str, grund: str) -> dict[str, Any]:
    return {"client_id": client_id, "ergebnis": "abgelehnt", "grund": grund}


def ergebnis_aus_quittung(client_id: str, quittung: dict[str, Any]) -> dict[str, Any]:
    """Die Quittung des WebSockets (``_ack``) als Ergebnis für den Tracker."""
    if quittung.get("result") == "ok":
        return {"client_id": client_id, "ergebnis": "ok", "applied": quittung.get("applied") or {}}
    return abgelehnt(client_id, str(quittung.get("reason") or "server-error"))


def zusammenfassen(client_id: str, ergebnisse: list[dict[str, Any]]) -> dict[str, Any]:
    """Ein Fahrzeug in mehreren laufenden Konvois (E8): Die Meldung gilt in jedem. Eine
    Zusage genügt — abgelehnt ist sie nur, wenn kein Konvoi sie genommen hat."""
    for e in ergebnisse:
        if e["ergebnis"] == "ok":
            return e
    return ergebnisse[0] if ergebnisse else abgelehnt(client_id, "kein-konvoi")
