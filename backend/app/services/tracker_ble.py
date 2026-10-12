"""Geräteschlüssel, Weiterleitung über BLE und Bake: die Kryptographie, ohne Netz und Datenbank.

Ein Tracker erreicht die Instanz über WLAN, Mobilfunk oder — als Rückfallebene — über
BLE und ein Telefon mit der Begleit-App (E14 im Plan des Tracker-Repos). Über BLE geht
das Gerätetoken **nie**: Das Telefon ist eine Leitung, die nichts fälschen soll. Das
Gerät signiert deshalb seine Rahmen selbst, die App liefert sie mit ihrem Fahrer-Link
ab, und die Instanz signiert ihre Antwort. Eine App kann so eine Antwort verschlucken,
aber kein ``senden`` außerhalb eines laufenden Konvois erfinden und kein ``schweigen``.

Grundlage ist der **Geräteschlüssel**, 32 zufällige Byte. Er entsteht bei ``einloesen``
und geht nur über eine direkte Verbindung zum Gerät (``einloesen``, ``hallo``), nie über
BLE. Aus ihm leiten Gerät und Instanz drei Teilschlüssel ab:

    k_<zweck> = HMAC-SHA256(schluessel, "convoyplan-tracker/<zweck>")   zweck ∈ buendel, anweisung, bake
    kennung   = hex(SHA-256(schluessel))[0:16]

Dieselbe Bake trägt eine Kennung, die alle 15 Minuten wechselt, damit die App erkennt,
in welchem Fahrzeug sie sitzt, ohne dass ein Passant ein Fahrzeug über Tage verfolgen
kann.

Abgelegt wird der Schlüssel verschlüsselt (``services/crypto.py``, wie MFA-Geheimnisse
und OAuth-Client-Secrets). Ist er nicht mehr lesbar (Schlüssel der Instanz gewechselt),
gilt er als fehlend: Das Gerät meldet beim nächsten direkten ``hallo`` eine Kennung, die
nicht passt, und bekommt einen neuen.

Das Protokoll steht im Tracker-Repo (``docs/PROTOKOLL.md``, „Geräteschlüssel",
„Weiterleitung über BLE", „Bake", „Prüfwerte"); die Prüfwerte von dort prüft
``tests/test_tracker_bake.py`` wörtlich. Simulator und Firmware rechnen dasselbe — wer
hier etwas ändert, zieht beide mit, und die Begleit-App (``packages/track-api``).
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.services import crypto

SCHLUESSEL_BYTES = 32
#: Länge eines Bake-Fensters; die Kennung wechselt mit ihm.
FENSTER_S = 900
#: Rahmen dürfen nur ``hallo`` und ``positionen`` tragen; Firmware und Einlösen gehen nie über BLE.
ARTEN = ("hallo", "positionen")
#: ``seq`` ist eine ganze Zahl unter 2⁵³ — so bleibt sie in JavaScript exakt.
SEQ_MAX = 2**53
#: Eine GATT-Nachricht hat höchstens 16 KB; was größer ist, kann von keinem Gerät stammen.
NUTZLAST_MAX = 16 * 1024


# ── Schlüssel ──────────────────────────────────────────────────────────────


def schluessel_erzeugen() -> bytes:
    return secrets.token_bytes(SCHLUESSEL_BYTES)


def kennung(schluessel: bytes) -> str:
    """16 Hex-Zeichen, mit denen das Gerät sagt, welchen Schlüssel es hat."""
    return hashlib.sha256(schluessel).hexdigest()[:16]


def teilschluessel(schluessel: bytes, zweck: str) -> bytes:
    return hmac.new(schluessel, f"convoyplan-tracker/{zweck}".encode(), hashlib.sha256).digest()


def als_base64(schluessel: bytes) -> str:
    return base64.b64encode(schluessel).decode()


def ablegen(schluessel: bytes) -> str:
    """Für die Spalte ``ortungsgeraete.schluessel``."""
    return crypto.encrypt_secret(als_base64(schluessel))


def schluessel_lesen(abgelegt: str | None) -> bytes | None:
    """Der Schlüssel aus der Spalte, oder ``None``, wenn keiner da oder er nicht lesbar ist."""
    if not abgelegt:
        return None
    klar = crypto.decrypt_secret(abgelegt)
    try:
        roh = base64.b64decode(klar, validate=True)
    except (binascii.Error, ValueError):
        return None
    return roh if len(roh) == SCHLUESSEL_BYTES else None


def kennung_gemeldet(daten: dict[str, Any]) -> str | None:
    """Die Kennung aus ``hallo``. ``None`` heißt: das Feld fehlt (alte Firmware), und dann
    bekommt das Gerät nie einen Schlüssel. ``""`` heißt: das Gerät hat keinen."""
    wert = daten.get("schluessel_kennung")
    return wert if isinstance(wert, str) else None


def angebot_noetig(gemeldet: str | None, schluessel: bytes | None) -> bool:
    """Ob ``hallo`` den Schlüssel mitschickt: nur bei gemeldeter, abweichender Kennung."""
    if gemeldet is None:
        return False
    return schluessel is None or not hmac.compare_digest(gemeldet, kennung(schluessel))


# ── Bake ───────────────────────────────────────────────────────────────────


def fenster(zeit: datetime) -> int:
    return int(zeit.timestamp()) // FENSTER_S


def bake_kennung(schluessel: bytes, fenster_: int) -> str:
    """``HMAC-SHA256(k_bake, fenster als 8 Byte Big Endian)[0:8]`` als Hex."""
    mac = hmac.new(teilschluessel(schluessel, "bake"), fenster_.to_bytes(8, "big"), hashlib.sha256)
    return mac.digest()[:8].hex()


def bake_kennungen(schluessel: bytes, zeit: datetime) -> list[str]:
    """Voriges, laufendes und nächstes Fenster — die Uhren von Gerät und Instanz gehen nicht gleich."""
    f = fenster(zeit)
    return [bake_kennung(schluessel, f + d) for d in (-1, 0, 1)]


def instanz_kurz(instanz: str) -> str:
    """``SHA-256(instanz)[0:2]`` als Hex — die Bytes 9–10 der Bake."""
    return hashlib.sha256(instanz.encode()).digest()[:2].hex()


# ── Rahmen ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Rahmen:
    geraet: str
    seq: int
    art: str
    instanz: str
    nutzlast: str
    mac: str


def rahmen_lesen(roh: Any) -> Rahmen | None:
    """Die Felder eines Rahmens, oder ``None``, wenn er so nicht von einem Gerät stammen kann.

    Was hier durchfällt, endet in derselben 404 wie eine falsche Signatur — es gibt
    nichts, das man dem Absender sagen müsste."""
    if not isinstance(roh, dict):
        return None
    geraet, seq, art = roh.get("geraet"), roh.get("seq"), roh.get("art")
    instanz, nutzlast, mac = roh.get("instanz"), roh.get("nutzlast"), roh.get("mac")
    if not all(isinstance(w, str) for w in (geraet, art, instanz, nutzlast, mac)):
        return None
    if isinstance(seq, bool) or not isinstance(seq, int) or not 0 <= seq < SEQ_MAX:
        return None
    if art not in ARTEN or len(nutzlast) > NUTZLAST_MAX or len(geraet) > 64 or len(instanz) > 256:
        return None
    return Rahmen(geraet=geraet, seq=seq, art=art, instanz=instanz, nutzlast=nutzlast, mac=mac)


def _b64_mac(schluessel: bytes, zweck: str, teile: list[str]) -> str:
    nachricht = "\n".join(teile).encode()
    return base64.b64encode(hmac.new(teilschluessel(schluessel, zweck), nachricht, hashlib.sha256).digest()).decode()


def rahmen_mac(schluessel: bytes, r: Rahmen) -> str:
    """``HMAC-SHA256(k_buendel, geraet \\n seq \\n art \\n instanz \\n nutzlast)``, Base64."""
    return _b64_mac(schluessel, "buendel", [r.geraet, str(r.seq), r.art, r.instanz, r.nutzlast])


def rahmen_echt(schluessel: bytes, r: Rahmen) -> bool:
    """Vergleich in konstanter Zeit, über die Bytes und nicht über die Schreibweise."""
    try:
        gemeldet = base64.b64decode(r.mac, validate=True)
    except (binascii.Error, ValueError):
        return False
    erwartet = base64.b64decode(rahmen_mac(schluessel, r))
    return hmac.compare_digest(gemeldet, erwartet)


def nutzlast_lesen(r: Rahmen) -> dict[str, Any] | None:
    """Der Körper, den das Gerät direkt geschickt hätte; ``None``, wenn er keiner ist.

    Ein unbrauchbarer Körper in einem echten Rahmen ist kein Fehler der Weiterleitung,
    sondern ein ``status: 400`` in der signierten Antwort — wie beim direkten Aufruf."""
    try:
        daten = json.loads(base64.b64decode(r.nutzlast, validate=True).decode("utf-8"))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    return daten if isinstance(daten, dict) else None


# ── Antwort ────────────────────────────────────────────────────────────────


def antwort_kodieren(status: int, koerper: dict[str, Any]) -> str:
    """``{"status", "koerper"}`` kompakt als UTF-8, Base64. Signiert wird dieser Text."""
    text = json.dumps({"status": status, "koerper": koerper}, separators=(",", ":"), ensure_ascii=False)
    return base64.b64encode(text.encode("utf-8")).decode()


def antwort_mac(schluessel: bytes, geraet: str, seq: int, antwort: str) -> str:
    """``HMAC-SHA256(k_anweisung, geraet \\n seq \\n antwort)``, Base64."""
    return _b64_mac(schluessel, "anweisung", [geraet, str(seq), antwort])


def antwort(schluessel: bytes, r: Rahmen, status: int, koerper: dict[str, Any]) -> dict[str, Any]:
    """Was die App dem Gerät zurückgibt: ``{seq, antwort, mac}``."""
    kodiert = antwort_kodieren(status, koerper)
    return {"seq": r.seq, "antwort": kodiert, "mac": antwort_mac(schluessel, r.geraet, r.seq, kodiert)}
