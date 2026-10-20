"""Link-Beiträge: ein Instagram-, YouTube-, Facebook- oder TikTok-Link aus der
Gruppe statt eines Fotos.

Plan: docs/superpowers/plans/2026-10-13-fotos-auf-der-aktionsseite.md, § 11.

Einbetten scheidet aus (Skripte und Tracking von Meta auf einer Seite, die
nichts von außen lädt), abholen auch (fremde Inhalte, keine API). Übrig bleibt
der Link selbst, den der EventTracker erst beim Klick öffnet.

Nur eine feste Liste von Diensten: Der Link landet auf einer öffentlichen
Seite, und ein beliebiger wäre ein Weg, Zuschauer irgendwohin zu schicken —
auch nach Freigabe durch eine Presse, die die Adresse nur überflogen hat.
Abgelegt wird die bereinigte Adresse: https, ohne Anmeldedaten, Port,
Fragment und ohne Abfrage (``igsh``, ``utm_*`` und Co. verraten, wer geteilt
hat). YouTube behält ``v`` und ``t``, ohne die die Adresse nichts zeigt.
"""
import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit

from app.models.public_tracker import LINK_MAX

# Dienst → Domains. Eine Subdomain zählt mit (``m.``, ``www.``), eine
# ähnlich klingende Domain nicht (``instagram.com.example``, ``fakeinstagram.com``).
DIENSTE: dict[str, tuple[str, ...]] = {
    "instagram": ("instagram.com",),
    "youtube": ("youtube.com", "youtu.be"),
    "facebook": ("facebook.com", "fb.watch"),
    "tiktok": ("tiktok.com",),
}
NAMEN = {"instagram": "Instagram", "youtube": "YouTube", "facebook": "Facebook", "tiktok": "TikTok"}

_ADRESSE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_BEHALTEN = {"youtube": {"v", "t"}}


@dataclass(frozen=True)
class Link:
    url: str
    dienst: str


def dienst(host: str) -> str | None:
    host = host.lower().rstrip(".")
    for name, domains in DIENSTE.items():
        if any(host == d or host.endswith("." + d) for d in domains):
            return name
    return None


def bereinigen(roh: str) -> Link | None:
    """Die öffentliche Fassung einer Adresse — oder ``None``, wenn sie zu
    keinem bekannten Dienst gehört oder nicht sauber ist."""
    # Satzzeichen am Ende gehören zum Satz, nicht zur Adresse.
    roh = roh.rstrip(".,;:!?)]}»“\"'")
    try:
        teile = urlsplit(roh)
        port = teile.port
    except ValueError:
        return None
    if teile.scheme.lower() not in ("http", "https") or not teile.hostname:
        return None
    if teile.username or teile.password or port is not None:
        return None
    name = dienst(teile.hostname)
    if name is None:
        return None
    behalten = _BEHALTEN.get(name, set())
    abfrage = urlencode([(k, v) for k, v in parse_qsl(teile.query) if k in behalten])
    pfad = teile.path or "/"
    if not re.fullmatch(r"[A-Za-z0-9/_\-.~%@+]*", pfad):
        return None
    url = f"https://{teile.hostname.lower()}{pfad}" + (f"?{abfrage}" if abfrage else "")
    if len(url) > LINK_MAX:
        return None
    return Link(url=url, dienst=name)


def finden(text_: str | None) -> tuple[Link, str | None] | None:
    """Der erste bekannte Link in einer Nachricht und der Text ohne ihn.

    Andere Adressen bleiben im Text stehen; ob der so hinausgeht, entscheidet
    die Presse wie bei jeder Bildunterschrift."""
    if not text_:
        return None
    for m in _ADRESSE.finditer(text_):
        link = bereinigen(m.group(0))
        if link is None:
            continue
        rest = (text_[: m.start()] + text_[m.end():]).strip()
        rest = re.sub(r"[ \t]{2,}", " ", rest)
        return link, rest or None
    return None
