"""Passkeys: Challenges, Relying Party und die Regeln drumherum.

Das Kryptografische erledigt ``py_webauthn``. Was hier steht, sind die
Entscheidungen, die die Bibliothek offen lässt — und die man ohne Netz und
ohne Browser prüfen kann (``tests/test_passkey_anmeldung.py``):

**Relying Party ist ``APP_BASE_URL``.** Ihr Hostname ist die RP-ID, sie selbst
der einzige erlaubte Ursprung. Dieselbe Adresse, die schon CORS und den
OAuth-Aussteller festlegt; eine zweite Einstellung, die von ihr abweichen
kann, wäre nur eine zweite Gelegenheit für einen Passkey, der nirgends passt.
Ein Passkey gehört damit zur Domain: zieht die Instanz um, gelten die alten
nicht mehr — das ist WebAuthn, nicht diese Umsetzung.

**Eine Challenge gilt einmal.** Sie liegt im Speicher und wird beim Einlösen
entfernt, ob die Prüfung danach gelingt oder nicht. Ein Token, das die
Challenge signiert mit sich trägt, wäre zustandslos, ließe sich aber bis zum
Ablauf beliebig oft einlösen. Im Speicher und nicht in der Datenbank wie die
Fehlversuche in ``rate_limit`` und die Verbindungen in ``tracking_manager``;
nach einem Neustart fängt eine halb begonnene Anmeldung von vorn an.

**Benutzerverifikation ist Pflicht.** Ein Passkey ersetzt Passwort *und*
Zweitfaktor: Besitz (das Gerät) plus PIN oder Biometrie. Ohne die Verifikation
bliebe nur der Besitz, und ein liegengelassenes, entsperrtes Telefon wäre eine
Anmeldung. Deshalb verlangt die Anmeldung per Passkey kein TOTP.
"""
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.config import settings

RP_NAME = "ConvoyPlan"

CHALLENGE_TTL_SECONDS = 300
"""So lange darf zwischen Optionen und Antwort liegen — der Browserdialog
selbst bricht nach ``TIMEOUT_MS`` ab, der Rest ist Puffer für langsame Netze."""

TIMEOUT_MS = 120_000

MAX_OFFENE = 10_000
"""Obergrenze für gleichzeitig offene Challenges.

Die Optionen für die Anmeldung sind öffentlich, jeder Aufruf legt eine an.
Ohne Grenze wäre das ein Weg, den Speicher des Backends zu füllen; mit ihr
fällt im schlimmsten Fall die älteste Anmeldung heraus und beginnt neu."""

MAX_PASSKEYS_JE_BENUTZER = 20

LOGIN = "login"
REGISTRIERUNG = "registrierung"


def rp_id() -> str:
    """Hostname aus ``APP_BASE_URL`` — ohne Port, ohne Schema."""
    return (urlsplit(settings.app_base_url.strip()).hostname or "").lower()


def origin() -> str:
    """Der Ursprung, aus dem eine Antwort stammen muss (Schema, Host, Port)."""
    teile = urlsplit(settings.app_base_url.strip())
    return f"{teile.scheme}://{teile.netloc}".lower()


# ── Challenges ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _Offen:
    challenge: bytes
    zweck: str
    user_id: str | None
    laeuft_ab: float


_offen: dict[str, _Offen] = {}


def _aufraeumen(jetzt: float) -> None:
    for schluessel in [k for k, v in _offen.items() if v.laeuft_ab <= jetzt]:
        del _offen[schluessel]
    # dict hält die Einfügereihenfolge: vorn steht die älteste.
    while len(_offen) >= MAX_OFFENE:
        del _offen[next(iter(_offen))]


def ausstellen(zweck: str, user_id: str | None = None, *, jetzt: float | None = None) -> tuple[str, bytes]:
    """Neue Challenge für ``zweck`` — gibt (Kennung, Challenge) zurück.

    Die Kennung geht mit den Optionen an den Browser und kommt mit der Antwort
    zurück; die Challenge steckt in den Optionen und, vom Gerät signiert, in
    der Antwort. Eine Registrierung ist an den Benutzer gebunden, der sie
    begonnen hat."""
    jetzt = time.monotonic() if jetzt is None else jetzt
    _aufraeumen(jetzt)
    kennung = secrets.token_urlsafe(24)
    challenge = secrets.token_bytes(32)
    _offen[kennung] = _Offen(challenge, zweck, user_id, jetzt + CHALLENGE_TTL_SECONDS)
    return kennung, challenge


def einloesen(kennung: str, zweck: str, user_id: str | None = None, *, jetzt: float | None = None) -> bytes | None:
    """Die Challenge zu ``kennung`` — genau einmal, und nur für denselben
    Zweck und Benutzer. ``None``, wenn es sie nicht (mehr) gibt.

    Entfernt wird sie in jedem Fall, auch wenn Zweck oder Benutzer nicht
    passen: wer eine fremde Kennung kennt, soll sie nicht gegen die richtige
    Stelle ein zweites Mal probieren können."""
    jetzt = time.monotonic() if jetzt is None else jetzt
    eintrag = _offen.pop(kennung, None)
    if eintrag is None or eintrag.laeuft_ab <= jetzt:
        return None
    if eintrag.zweck != zweck or eintrag.user_id != user_id:
        return None
    return eintrag.challenge


def reset() -> None:
    """Alle offenen Challenges verwerfen (Tests)."""
    _offen.clear()


# ── Zähler ───────────────────────────────────────────────────────────────────


def zaehler_ok(gespeichert: int, neu: int) -> bool:
    """Ob der Signaturzähler einer Anmeldung zum gespeicherten passt.

    Zählt das Gerät nicht (beide 0 — der Normalfall bei synchronisierten
    Passkeys), gibt es nichts zu vergleichen. Zählt es, muss der neue Wert
    größer sein; ein gleicher oder kleinerer heißt, dass ein zweites Exemplar
    desselben Schlüssels in Gebrauch ist (WebAuthn §6.1.1)."""
    if gespeichert == 0 and neu == 0:
        return True
    return neu > gespeichert


def standardname(transports: list[str], backed_up: bool) -> str:
    """Name, falls beim Anlegen keiner angegeben wurde.

    Mehr als eine grobe Einordnung gibt die Antwort ohne Attestierung nicht
    her — welches Telefon es war, sagt sie nicht."""
    if backed_up:
        return "Synchronisierter Passkey"
    if "usb" in transports or "nfc" in transports:
        return "Sicherheitsschlüssel"
    return "Passkey"
