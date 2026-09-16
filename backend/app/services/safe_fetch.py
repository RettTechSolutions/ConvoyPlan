"""Abrufen einer URL, die jemand anderes bestimmt hat.

Gebraucht für Client ID Metadata Documents (``app/services/oauth_provider.py``):
dort ist die ``client_id`` eine HTTPS-URL, die der Anfragende wählt, und der
Server ruft sie ab. Damit ist das ein lupenreines SSRF-Primitiv, wenn man es
naiv baut — ein Angreifer ließe den Server jede Adresse ansprechen, die vom
Container aus erreichbar ist: Nachbardienste im Compose-Netz, der
Metadatendienst der Cloud, das Docker-API.

Die Schranken hier sind deshalb fail-closed und einzeln begründet.

**Was NICHT abgedeckt ist:** DNS-Rebinding. Zwischen der Auflösung des Namens
und dem Verbindungsaufbau kann sich die Antwort ändern; ein Angreifer mit
Kontrolle über seine eigene Zone kann das gezielt herbeiführen. Dagegen hülfe
nur, die geprüfte IP an die Verbindung zu binden — das geht mit httpx nicht
ohne eigene Transportschicht und wäre hier mehr Apparat als Nutzen, solange
die Funktion überhaupt abschaltbar ist (``MCP_ALLOW_CIMD``, standardmäßig
aus). Das ist eine bewusste Grenze, keine Lücke aus Versehen: wer sie nicht
tragen will, lässt CIMD aus und bleibt bei der Registrierung.
"""
import ipaddress
import logging
import socket

import httpx

logger = logging.getLogger(__name__)

# Knapp bemessen. Ein Metadatendokument ist ein paar hundert Bytes; alles
# darüber ist entweder falsch adressiert oder ein Versuch, den Speicher zu
# füllen.
MAX_BYTES = 64 * 1024
# Getrennte Zeitgrenzen: ein Angreifer, der die Verbindung annimmt und dann
# schweigt, würde sonst einen Worker binden.
TIMEOUT = httpx.Timeout(connect=3.0, read=5.0, write=3.0, pool=3.0)


class UnsafeUrlError(ValueError):
    """Die URL darf nicht abgerufen werden. Die Meldung nennt den Grund."""


# Shared Address Space nach RFC 6598 (Carrier-Grade NAT). Python zählt den
# Bereich **nicht** zu ``is_private`` — geprüft, nicht vermutet:
# ``ipaddress.ip_address("100.64.0.1").is_private`` ist ``False``. In Netzen,
# die CGNAT einsetzen, wären darüber erreichbare Hosts sonst offen.
_SHARED_ADDRESS_SPACE = ipaddress.ip_network("100.64.0.0/10")


def _ip_ist_oeffentlich(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Ob eine Adresse außerhalb des eigenen Netzes und der Sonderbereiche liegt.

    ``is_private`` deckt in CPython bereits Loopback, Link-local (also auch
    ``169.254.169.254``, den Metadatendienst vieler Cloud-Anbieter) und
    ``0.0.0.0`` mit ab. Die weiteren Prüfungen sind trotzdem einzeln
    ausgeschrieben: was hier gemeint ist, soll nicht davon abhängen, wie eine
    Python-Version ``is_private`` gerade auslegt. Zwei Fälle deckt sie
    tatsächlich nicht ab — sie stehen deshalb ausdrücklich da."""
    if isinstance(ip, ipaddress.IPv4Address) and ip in _SHARED_ADDRESS_SPACE:
        return False
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        # IPv4-gemappte IPv6-Adressen (::ffff:10.0.0.1): hier deckt is_private
        # sie zwar ab, aber verlassen wollen wir uns darauf nicht — die
        # Auslegung hat sich zwischen Python-Versionen schon geändert.
        or (isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None)
    )


def pruefe_url(url: str) -> str:
    """Eine URL auf Abrufbarkeit prüfen; gibt den Hostnamen zurück.

    Wirft ``UnsafeUrlError`` mit Begründung, wenn etwas nicht passt."""
    try:
        parsed = httpx.URL(url)
    except Exception:
        raise UnsafeUrlError("Die Adresse ist keine gültige URL.")

    if parsed.scheme != "https":
        # Kein HTTP: das Dokument bestimmt, wem der Server künftig vertraut.
        raise UnsafeUrlError("Nur HTTPS ist zulässig.")
    if parsed.fragment:
        raise UnsafeUrlError("Die Adresse darf kein Fragment enthalten.")
    if parsed.userinfo:
        raise UnsafeUrlError("Die Adresse darf keine Zugangsdaten enthalten.")

    host = parsed.host
    if not host:
        raise UnsafeUrlError("Die Adresse nennt keinen Host.")

    # Eine direkt angegebene IP wird sofort geprüft — sonst käme man über
    # https://10.0.0.5/… an jedem Namensfilter vorbei.
    try:
        direkt = ipaddress.ip_address(host)
    except ValueError:
        direkt = None
    if direkt is not None:
        if not _ip_ist_oeffentlich(direkt):
            raise UnsafeUrlError(f"Die Adresse {host} liegt in einem nicht zulässigen Netz.")
        return host

    # Namen auflösen und **jede** Antwort prüfen. Nur die erste zu prüfen
    # genügt nicht: ein Name kann auf mehrere Adressen zeigen, und welche der
    # Client-Stack am Ende nimmt, entscheidet nicht diese Funktion.
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise UnsafeUrlError(f"Der Name {host} lässt sich nicht auflösen.")
    if not infos:
        raise UnsafeUrlError(f"Der Name {host} löst auf keine Adresse auf.")

    for info in infos:
        adresse = ipaddress.ip_address(info[4][0])
        if not _ip_ist_oeffentlich(adresse):
            raise UnsafeUrlError(
                f"Der Name {host} zeigt auf {adresse} — das liegt in einem "
                "nicht zulässigen Netz."
            )
    return host


async def fetch_json(url: str) -> dict:
    """Ein JSON-Dokument von einer fremdbestimmten URL holen.

    Keine Weiterleitungen: eine zulässige Adresse, die auf eine unzulässige
    weiterleitet, wäre die offensichtlichste Umgehung der Prüfung oben."""
    pruefe_url(url)
    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT, follow_redirects=False, max_redirects=0
        ) as client:
            antwort = await client.get(url, headers={"Accept": "application/json"})
    except httpx.HTTPError as exc:
        raise UnsafeUrlError(f"Die Adresse ist nicht erreichbar: {exc}")

    if antwort.is_redirect:
        raise UnsafeUrlError("Weiterleitungen werden nicht gefolgt.")
    if antwort.status_code != 200:
        raise UnsafeUrlError(f"Die Adresse antwortet mit HTTP {antwort.status_code}.")

    typ = antwort.headers.get("content-type", "").split(";")[0].strip().lower()
    if typ not in ("application/json", "application/ld+json"):
        raise UnsafeUrlError(f"Unerwarteter Inhaltstyp: {typ or '(keiner)'}.")

    rohdaten = antwort.content
    if len(rohdaten) > MAX_BYTES:
        raise UnsafeUrlError(f"Das Dokument ist größer als {MAX_BYTES} Bytes.")

    try:
        daten = antwort.json()
    except ValueError:
        raise UnsafeUrlError("Das Dokument ist kein gültiges JSON.")
    if not isinstance(daten, dict):
        raise UnsafeUrlError("Das Dokument ist kein JSON-Objekt.")
    return daten
