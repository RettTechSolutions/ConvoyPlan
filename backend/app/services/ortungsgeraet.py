"""Ortungsgeräte: die Regeln der Geräte-API, ohne Netz und ohne Datenbank.

Ein Tracker (Repo ConvoyPlan-Tracker) hängt am **Fahrzeug**, Positionen gehören
aber einem **Konvoi** (``vehicle_positions`` hat den Schlüssel ``convoy_id,
vehicle_id``). Deshalb entscheidet die Instanz, nicht das Gerät, ob gesendet
wird: ``senden`` nur, solange das gekoppelte Fahrzeug in mindestens einem
Konvoi mit Status ``active`` oder ``running`` eingeplant ist (E7 im Plan des
Tracker-Repos). Alles andere ist ``schweigen`` — Datenschutz, Akku und
Datenvolumen zugleich. Das Gerät erfährt es aus jeder Antwort und hält sich
daran; ein Fix, der trotzdem ankommt, wird verworfen.

Zwei Dinge unterscheiden den Tracker von Fahrer-Link und App:

- **Gerätezeit statt Serverzeit.** Ein Tracker puffert im Funkloch und reicht
  nach. Mit Serverzeit landete die Fahrt durch den Tunnel als Knäuel am Ende
  der Linie. Jeder Fix trägt deshalb seine GNSS-Zeit; was mehr als zwei
  Minuten in der Zukunft liegt (falsche Uhr) oder älter als ein Tag ist, fällt
  weg — je Fix, nicht je Bündel.
- **Die aktuelle Position gewinnt nur, wenn sie jünger ist.** Ein nachgereichtes
  Bündel darf das Fahrzeug auf der Karte nicht zurücksetzen.

Was hier steht, prüft ``tests/test_tracker_geraete.py`` ohne Datenbank; die
Verdrahtung in ``api/routes/geraete.py`` danach durch die App. Das Protokoll
selbst steht im Tracker-Repo (``docs/PROTOKOLL.md``); die Referenz-Instanz
dort tut dasselbe wie dieser Code und muss mitziehen, wenn sich hier etwas
ändert.
"""
from __future__ import annotations

import hashlib
import hmac
import math
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

#: Konvoi-Status, in denen ein Tracker sendet (E7).
LAUFEND = frozenset({"active", "running"})
#: Firmware-Kanäle, wie bei der Instanz.
KANAELE = ("stable", "beta", "nightly")

ZUKUNFT_MAX = timedelta(seconds=120)
VERGANGENHEIT_MAX = timedelta(hours=24)
BUENDEL_MAX = 500
#: Ein Einmal-Code gilt einen Tag — lang genug, um das Gerät in Ruhe
#: anzustecken, kurz genug, dass ein liegen gebliebener Zettel nichts wert ist.
CODE_GUELTIG = timedelta(hours=24)

#: Unter diesem Ladestand und ohne Bordnetz warnt die Oberfläche („Akku schwach").
#: Hier und nur hier: Org-Admin und Konvoi-Ansicht lesen ``akku_niedrig``.
AKKU_NIEDRIG_PROZENT = 20

#: Takt, den die Instanz dem Gerät vorgibt (Protokoll, „Anweisung"). ``buendel_s``
#: ist der Standard; jede Organisation kann ihn ändern (``tracker_buendel_s``).
TAKT = {"intervall_s": 10, "buendel_s": 15, "nachfrage_s": 300, "lebenszeichen_s": 43200}

#: Was der Org-Admin für ``buendel_s`` wählen kann. Nicht unter dem Fix-Takt
#: (``intervall_s``): öfter senden als messen bringt nichts. Nicht über 120 s:
#: Der Tracker behält seinen Vorrang vor dem Telefon nur, solange er in den
#: letzten fünf Minuten gesendet hat (``positionsquelle.VORRANG_S``), und ein
#: Funkloch soll nicht gleich das Telefon zurückholen.
BUENDEL_WAHL = (10, 15, 30, 60, 120)

# Datenvolumen je Versand in Fahrt, geschätzt aus dem, was die Firmware schickt
# (Tracker-Repo, ``kern_json_positionen`` und ``kern_http_anfrage``); gemessen
# wird es dort in Phase 0 (M3). Was sich häuft, ist der Versand, nicht der Fix:
# Ein Fix sind gut 100 Bytes, Kopf, Antwort und Rahmen um 1,4 KB.
VOLUMEN_FIX_B = 115
#: Anfrage mit Kopf, Token und Gerätezustand, Antwort mit Anweisung, TLS-Rahmen
#: und TCP/IP-Pakete samt Quittungen — bei offener Verbindung (Keep-Alive).
VOLUMEN_VERSAND_B = 1400
#: Dazu, wenn die Verbindung zwischen zwei Versänden zugegangen ist: TCP- und
#: TLS-Handschlag mit Zertifikatskette.
VOLUMEN_HANDSCHLAG_B = 5000

#: Wie viele erwartete Bündel ausbleiben, bis die Verbindung als unterbrochen gilt.
#: Eins allein ist oft nur ein langsamer Verbindungsaufbau.
BUENDEL_AUSGEBLIEBEN = 2
#: Spielraum für Verbindungsaufbau und TLS im Mobilfunk, auf die ausgebliebenen Bündel.
VERBINDUNG_TOLERANZ = timedelta(seconds=15)
#: Im Halt nimmt das Gerät nur alle 60 s einen Fix auf. So lange plus ein Bündel und
#: Spielraum darf bei stehender Verbindung ein plausibler Fix fehlen (``gps_frist``).
HALT_FIX_S = 60

#: Unplausible Fixes (Protokoll, „positionen"): Was ein Empfänger mit gestörtem GNSS
#: liefert, Null Island, Mehrwege im Häuserblock, Spoofing, landet nicht auf der Karte.
GENAUIGKEIT_MAX_M = 100.0
TEMPO_MAX_KMH = 250.0

# Ohne 0/O, 1/I: der Code wird abgetippt.
_CODE_ZEICHEN = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CODE_FORM = re.compile(r"^[A-Z2-9]{4}-?[A-Z2-9]{4}$")
UPDATE_ERGEBNISSE = ("bestaetigt", "zurueckgerollt", "fehler")


# ── Geheimnisse ────────────────────────────────────────────────────────────


def hash(wert: str) -> str:  # noqa: A001 — bewusst wie bei der Aktionsseite
    return hashlib.sha256(wert.encode()).hexdigest()


def code_erzeugen() -> str:
    """``K7Q2-M9XD``: 8 Zeichen aus 32, rund 40 Bit. Reicht mit Ablauf und
    Rate-Limit am Einlösen; ein Code wird einmal abgetippt, nicht geraten."""
    roh = "".join(secrets.choice(_CODE_ZEICHEN) for _ in range(8))
    return f"{roh[:4]}-{roh[4:]}"


def code_normalisieren(eingabe: str) -> str | None:
    """Groß/klein und Bindestrich sind dem Tipper egal; der Hash nicht."""
    text = eingabe.strip().upper().replace(" ", "")
    if not _CODE_FORM.match(text):
        return None
    text = text.replace("-", "")
    return f"{text[:4]}-{text[4:]}"


def token_erzeugen() -> str:
    return "cvt_" + secrets.token_urlsafe(32)


def code_gueltig(
    code_hash: str | None, code_expires_at: datetime | None, eingabe: str, jetzt: datetime
) -> bool:
    if code_hash is None or code_expires_at is None or jetzt >= code_expires_at:
        return False
    code = code_normalisieren(eingabe)
    return code is not None and hmac.compare_digest(hash(code), code_hash)


# ── Fixes ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Fix:
    t: datetime
    lat: float
    lon: float
    speed_kmh: float | None
    heading: float | None
    accuracy_m: float | None


def _zahl(wert: Any) -> float | None:
    if isinstance(wert, bool) or not isinstance(wert, (int, float)):
        return None
    return float(wert)


def fix_lesen(roh: Any, jetzt: datetime) -> Fix | None:
    """Ein Fix aus dem Bündel, oder ``None``, wenn er nicht zu gebrauchen ist."""
    if not isinstance(roh, dict):
        return None
    try:
        t = datetime.fromisoformat(str(roh["t"]).replace("Z", "+00:00"))
        lat, lon = float(roh["lat"]), float(roh["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    if t.tzinfo is None:
        return None
    t = t.astimezone(timezone.utc)
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    if t > jetzt + ZUKUNFT_MAX or t < jetzt - VERGANGENHEIT_MAX:
        return None
    if lat == 0 and lon == 0:
        return None  # Null Island: der Empfänger hat keine Position, schickt aber eine
    speed = _zahl(roh.get("speed_kmh"))
    heading = _zahl(roh.get("heading"))
    accuracy = _zahl(roh.get("accuracy_m"))
    if (accuracy is not None and accuracy > GENAUIGKEIT_MAX_M) or (speed is not None and speed > TEMPO_MAX_KMH):
        return None
    return Fix(
        t=t,
        lat=lat,
        lon=lon,
        speed_kmh=speed if speed is not None and speed >= 0 else None,
        heading=heading if heading is not None and 0 <= heading < 360 else None,
        accuracy_m=accuracy if accuracy is not None and accuracy >= 0 else None,
    )


def fixes_lesen(roh: Any, jetzt: datetime) -> tuple[list[Fix], int]:
    """Alle brauchbaren Fixes nach Zeit sortiert, dazu die Zahl der verworfenen.

    Wirft ``ValueError``, wenn das Bündel als Ganzes nicht taugt (keine Liste,
    zu groß) — das ist der einzige Fall für eine 400. Ein einzelner kaputter
    Fix kostet nur sich selbst."""
    if not isinstance(roh, list) or len(roh) > BUENDEL_MAX:
        raise ValueError(f"fixes: Liste mit höchstens {BUENDEL_MAX} Einträgen")
    gueltig = [f for f in (fix_lesen(r, jetzt) for r in roh) if f is not None]
    gueltig.sort(key=lambda f: f.t)
    gueltig = _ohne_spruenge(gueltig)
    return gueltig, len(roh) - len(gueltig)


def _abstand_m(a: Fix, b: Fix) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dp, dl = p2 - p1, math.radians(b.lon - a.lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(h)))


def _ohne_spruenge(fixes: list[Fix]) -> list[Fix]:
    """Fixes, die vom vorigen schneller als ``TEMPO_MAX_KMH`` entfernt wären, fallen weg.

    Verglichen wird mit dem letzten behaltenen, damit ein einzelner Ausreißer nicht
    auch den nächsten, wieder richtigen Fix mitreißt. Mindestens eine Sekunde
    Abstand, sonst wäre jeder Doppelfix mit Rauschen unendlich schnell."""
    behalten: list[Fix] = []
    for f in fixes:
        if behalten:
            vorher = behalten[-1]
            sekunden = max(1.0, (f.t - vorher.t).total_seconds())
            if _abstand_m(vorher, f) / sekunden * 3.6 > TEMPO_MAX_KMH:
                continue
        behalten.append(f)
    return behalten


def ueberschreibt(vorhanden_at: datetime | None, neu: Fix) -> bool:
    """Ob der Fix die aktuelle Position ersetzt: nur, wenn er jünger ist."""
    return vorhanden_at is None or neu.t > vorhanden_at


# ── Anweisung ──────────────────────────────────────────────────────────────


def modus(gekoppelt: bool, laufende_konvois: int, gesperrt: bool = False) -> str:
    """``senden`` oder ``schweigen``. *gesperrt* ist die Plansperre der
    Organisation — ein dritter Schreibweg zieht sie mit (``services/org_plan``)."""
    if gesperrt or not gekoppelt or laufende_konvois == 0:
        return "schweigen"
    return "senden"


def buendel_s(gewaehlt: int | None) -> int:
    """Der Bündeltakt einer Organisation; ohne gültige Wahl der Standard."""
    return gewaehlt if gewaehlt in BUENDEL_WAHL else TAKT["buendel_s"]


def volumen_kb_pro_stunde(buendel: int, offen: bool = True) -> int:
    """Geschätztes Datenvolumen eines Trackers je Fahrstunde in KB.

    *offen*: Die Verbindung bleibt zwischen zwei Versänden stehen. Sonst kostet
    jeder Versand einen neuen Handschlag, und der ist größer als alles andere.
    Im Halt (Fix alle 60 s) und in Ruhe ist es viel weniger."""
    versaende = 3600 / buendel
    fixes = buendel / TAKT["intervall_s"]
    je_versand = VOLUMEN_VERSAND_B + fixes * VOLUMEN_FIX_B + (0 if offen else VOLUMEN_HANDSCHLAG_B)
    return round(versaende * je_versand / 1000)


def anweisung(
    modus_: str,
    jetzt: datetime,
    firmware: dict[str, Any] | None = None,
    buendel: int | None = None,
) -> dict[str, Any]:
    return {
        "modus": modus_,
        **TAKT,
        "buendel_s": buendel_s(buendel),
        "serverzeit": jetzt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "firmware": firmware,
    }


def gps_frist(buendel: int) -> timedelta:
    """Bis „GPS gestört" gilt: Fix-Takt im Halt, ein Bündel im Takt der Organisation, Spielraum."""
    return timedelta(seconds=HALT_FIX_S + buendel) + VERBINDUNG_TOLERANZ


def unterbrochen_ab(modus_: str, ruhe: Any, jetzt: datetime, buendel: int) -> datetime | None:
    """Ab wann die Verbindung als unterbrochen gilt, nach einem angenommenen Bündel.

    Solange die Fahrt läuft, sendet das Gerät alle *buendel* Sekunden (der Takt
    der Organisation aus der Anweisung, ``buendel_s``) — auch leer, wenn
    GNSS fehlt. Bleiben zwei erwartete Bündel aus, ist die Verbindung weg. Erwartet
    wird nichts, wenn die Antwort ``schweigen`` war oder das Gerät mit ``ruhe: true``
    sagt, dass es jetzt schläft (fünf Minuten Halt, Zündung aus): ein parkendes
    Fahrzeug ist kein Funkloch. Ein Gerät, das mitten in der Fahrt ausgeht, meldet
    sich nicht ab — genau das soll auffallen.
    """
    if modus_ != "senden" or ruhe is True:
        return None
    return jetzt + BUENDEL_AUSGEBLIEBEN * timedelta(seconds=buendel) + VERBINDUNG_TOLERANZ


def gps_gestoert_ab(
    alt: datetime | None, unterbrochen_ab_: datetime | None, plausible: int, jetzt: datetime, buendel: int
) -> datetime | None:
    """Ab wann „GPS gestört" gilt, nach einem angenommenen Bündel.

    Nur solange die Instanz Bündel erwartet (*unterbrochen_ab_* gesetzt): Dann ist
    das Netz da, und ein Bündel ohne plausiblen Fix heißt, GNSS liefert nichts
    Brauchbares — kein Empfang, Antenne ab, Störsender, Unsinn. Ein plausibler Fix
    schiebt die Frist, ein leeres Bündel nicht; es beginnt sie nur, wenn noch keine
    läuft (erstes Bündel der Fahrt)."""
    if unterbrochen_ab_ is None:
        return None
    if plausible > 0 or alt is None:
        return jetzt + gps_frist(buendel)
    return alt


def akku_niedrig(akku_prozent: int | None, extern: bool | None) -> bool:
    """Ob der Akku warnen soll: unter der Schwelle **und** nicht am Bordnetz.

    Am Bordnetz lädt das Gerät; ein leerer Akku dort ist ein Ladezustand,
    keine Gefahr. Ohne Angabe zum Bordnetz zählt nur der Ladestand."""
    return akku_prozent is not None and akku_prozent < AKKU_NIEDRIG_PROZENT and extern is not True


def akku_seit(
    alt_extern: bool | None, alt_seit: datetime | None, neu_extern: bool | None, jetzt: datetime
) -> datetime | None:
    """Seit wann ein Gerät auf Akku läuft, nach seiner neuesten Meldung.

    Die Instanz sieht den Wechsel nur, wenn das Gerät ihn meldet — also ist der
    Wert „seit spätestens". Eine Meldung ohne `extern` ändert nichts, sonst
    verlöre ein Bündel ohne Zustand den Zeitpunkt. Ohne Vorwert (neues Gerät,
    alte Zeile) gilt die erste Meldung `false` als Beginn.
    """
    if neu_extern is None:
        return alt_seit
    if neu_extern:
        return None
    if alt_extern is False and alt_seit is not None:
        return alt_seit
    return jetzt


def zustand_lesen(daten: dict[str, Any]) -> dict[str, Any]:
    """Was das Gerät über sich meldet, bereinigt — für die Spalten am Gerät."""
    felder: dict[str, Any] = {}
    firmware = daten.get("firmware")
    if isinstance(firmware, str) and firmware.strip():
        felder["firmware"] = firmware.strip()[:40]
    akku = _zahl(daten.get("akku_prozent"))
    if akku is not None and 0 <= akku <= 100:
        felder["akku_prozent"] = int(akku)
    if isinstance(daten.get("extern"), bool):
        felder["extern"] = daten["extern"]
    signal = _zahl(daten.get("signal_dbm"))
    if signal is not None and -200 <= signal <= 0:
        felder["signal_dbm"] = int(signal)
    return felder
