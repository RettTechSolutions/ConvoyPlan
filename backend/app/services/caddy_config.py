"""Generation — and self-healing — of the Caddy reverse-proxy configuration.

The setup wizard writes a Caddyfile to the shared ``/certs`` volume and Caddy's
entrypoint prefers that persisted file over its env-var-generated fallback.
Because the file is written exactly once (during initial setup) it freezes the
proxy configuration of that install forever: an instance that was set up before
the hardening headers existed keeps serving responses **without** HSTS, CSP,
``X-Frame-Options``, ``X-Content-Type-Options``, ``Referrer-Policy`` and
``Permissions-Policy`` — even after the images have been updated many times.

``ensure_caddyfile_current()`` closes that gap. On every backend start the
persisted Caddyfile is checked for the hardening headers; if any are missing it
is regenerated from the persisted setup settings (domain / TLS mode / ACME
mail) and hot-reloaded via Caddy's admin API, so the fix lands without a manual
re-run of the setup wizard.

ISO 27001 A.8.26 (application security requirements).
"""

from __future__ import annotations

import errno
import logging
import os
import tempfile
from contextlib import suppress
from pathlib import Path

from dataclasses import dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.settings import SystemSetting

logger = logging.getLogger(__name__)

CERTS_DIR = Path("/certs")
CADDYFILE_PATH = CERTS_DIR / "Caddyfile"

# Every header the generated config must carry. `ensure_caddyfile_current()`
# regenerates the persisted Caddyfile as soon as one of them is absent, so
# adding an entry here also rolls it out to existing installs on next start.
REQUIRED_SECURITY_HEADERS = (
    "Strict-Transport-Security",
    "X-Content-Type-Options",
    "X-Frame-Options",
    "Referrer-Policy",
    "Permissions-Policy",
    "Content-Security-Policy",
)


def csp_value(domain: str) -> str:
    """The Content-Security-Policy for the app, including the third-party map,
    geocoding and WebSocket origins the UI legitimately talks to."""
    return (
        "default-src 'self'; base-uri 'self'; object-src 'none'; "
        "frame-ancestors 'self'; "
        "img-src 'self' data: blob: https://tile.openstreetmap.org; "
        "style-src 'self' 'unsafe-inline'; script-src 'self'; "
        "worker-src 'self' blob:; font-src 'self' data:; "
        "connect-src 'self' https://tile.openstreetmap.org "
        "https://nominatim.openstreetmap.org https://photon.komoot.io "
        f"ws://{domain} wss://{domain}"
    )


def security_header_block(domain: str) -> str:
    """Caddy ``header`` block: hardening headers + a Content-Security-Policy.

    The CSP ships in *Report-Only* mode by default (it cannot break the UI —
    browsers only report violations). Set ``CSP_ENFORCE=true`` to switch to an
    enforcing policy once it has been verified for the deployment.
    """
    csp_header = (
        "Content-Security-Policy"
        if os.environ.get("CSP_ENFORCE", "false").lower() == "true"
        else "Content-Security-Policy-Report-Only"
    )
    return f"""header {{
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
        X-Content-Type-Options "nosniff"
        X-Frame-Options "SAMEORIGIN"
        Referrer-Policy "strict-origin-when-cross-origin"
        Permissions-Policy "geolocation=(self), microphone=(), camera=()"
        {csp_header} "{csp_value(domain)}"
        -Server
    }}"""


def generate_caddyfile(domain: str, tls_mode: str, acme_email: str) -> str:
    if tls_mode == "custom":
        tls_directive = "tls /certs/cert.pem /certs/key.pem"
    elif tls_mode == "internal":
        tls_directive = "tls internal"
    else:
        tls_directive = ""  # auto Let's Encrypt

    header_block = security_header_block(domain)

    return f"""{{
    admin 0.0.0.0:2019
    email {acme_email}
}}

{domain} {{
    {tls_directive}

    {header_block}

    # SSE live-log endpoint — flush every chunk immediately
    handle /api/admin/update-log {{
        reverse_proxy backend:8000 {{
            flush_interval -1
        }}
    }}
    handle /api/* {{
        reverse_proxy backend:8000
    }}
    # MCP endpoint. Streamable HTTP can answer with an SSE stream, so this
    # must not be buffered either. Always routed, even when MCP_ENABLED is
    # off — the backend answers 404 then, and switching MCP on later needs
    # no proxy change.
    handle /mcp {{
        reverse_proxy backend:8000 {{
            flush_interval -1
        }}
    }}
    # OAuth discovery and endpoints for the MCP server. RFC 9728 requires the
    # metadata at the site root, so it cannot live under /api/.
    handle /.well-known/oauth-* {{
        reverse_proxy backend:8000
    }}
    handle /authorize {{
        reverse_proxy backend:8000
    }}
    handle /token {{
        reverse_proxy backend:8000
    }}
    handle /register {{
        reverse_proxy backend:8000
    }}
    handle /revoke {{
        reverse_proxy backend:8000
    }}
    handle /ws/* {{
        reverse_proxy backend:8000 {{
            flush_interval -1
        }}
    }}
    handle {{
        reverse_proxy frontend:3000
    }}
}}
"""


# Die Pfade, die der MCP-Server an der Wurzel braucht. Ein Caddyfile aus der
# Zeit vor diesem Feature leitet sie ans Frontend — dort laufen sie ins Leere.
REQUIRED_MCP_PATHS = (
    "/mcp",
    "/.well-known/oauth-*",
    "/authorize",
    "/token",
    "/register",
    "/revoke",
)

# Dieselben Pfade in der Schreibweise des Caddyfiles. Abgeleitet statt ein
# zweites Mal getippt: zwei Listen, die auseinanderlaufen können, wären genau
# die Art Fehler, die hier niemand bemerkt.
REQUIRED_MCP_ROUTES = tuple(f"handle {pfad}" for pfad in REQUIRED_MCP_PATHS)


def has_mcp_routes(caddyfile: str) -> bool:
    """True, wenn die Konfiguration die MCP-Pfade ans Backend leitet."""
    return all(route in caddyfile for route in REQUIRED_MCP_ROUTES)


def has_security_headers(caddyfile: str) -> bool:
    """True when the config already sets every header in
    ``REQUIRED_SECURITY_HEADERS``. ``Content-Security-Policy`` matches the
    Report-Only variant too, since that is the default mode."""
    return all(name in caddyfile for name in REQUIRED_SECURITY_HEADERS)


async def reload_caddy(caddyfile: str) -> bool:
    """Push a new Caddyfile to Caddy's admin API at :2019.

    NOTE: Caddy admin is bound to 0.0.0.0:2019 so this backend container can
    reach it on the Docker bridge network. The port is not exposed to the host
    (no ports: entry in docker-compose.yml for the caddy admin port), so
    exposure is limited to the internal Docker network.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Step 1: adapt Caddyfile -> JSON
            adapt = await client.post(
                f"{settings.caddy_admin_url}/adapt",
                content=caddyfile.encode(),
                params={"adapter": "caddyfile"},
            )
            adapt.raise_for_status()
            # Step 2: load JSON config (Caddy /adapt returns {"result": ..., "warnings": [...]})
            adapted_config = adapt.json()["result"]
            load = await client.post(
                f"{settings.caddy_admin_url}/load",
                json=adapted_config,
            )
            load.raise_for_status()
            return True
    except Exception as exc:
        logger.warning("Caddy reload failed (will apply on next start): %s", exc)
        return False


@dataclass(frozen=True)
class ProxyBefund:
    """Was der Reverse Proxy gerade tatsächlich tut — und was sich reparieren lässt.

    ``routen_aktiv`` ist die einzige Angabe, die zählt: sie kommt aus der
    **laufenden** Konfiguration über Caddys Admin-API, nicht aus einer Datei
    auf der Platte. Genau das ist der Fall, der uns hier beschäftigt hat: das
    Backend war aktualisiert, die Datei stimmte womöglich, und der
    Caddy-Container lief trotzdem noch mit der alten Konfiguration.

    ``None`` heißt „nicht feststellbar" (Admin-API nicht erreichbar) und ist
    ausdrücklich nicht dasselbe wie ``False`` — im Portal darf daraus keine
    Fehlermeldung werden, sondern ein Hinweis.
    """

    routen_aktiv: bool | None
    persistierte_datei: bool
    datei_hat_routen: bool | None
    setup_werte_vorhanden: bool

    @property
    def reparierbar(self) -> bool:
        """Ob eine Reparatur aus dem Portal heraus etwas ausrichten kann.

        Ohne die Setup-Werte (Domain, TLS-Modus) lässt sich kein Caddyfile
        erzeugen — dann hilft nur der Setup-Assistent oder die Datei von Hand.

        Laufende Routen allein genügen nicht: trägt die hinterlegte Datei sie
        nicht, verliert der nächste Caddy-Neustart sie wieder. Genau dieser
        Zustand entsteht, wenn die Reparatur zwar nachladen, aber nicht
        schreiben konnte — der Knopf muss dann erreichbar bleiben."""
        if not self.setup_werte_vorhanden:
            return False
        if self.routen_aktiv is not True:
            return True
        return self.persistierte_datei and self.datei_hat_routen is False


async def _live_config() -> str | None:
    """Die laufende Caddy-Konfiguration als Rohtext, oder None."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.caddy_admin_url}/config/")
            resp.raise_for_status()
            return resp.text
    except Exception as exc:
        logger.debug("Caddy-Admin-API nicht erreichbar: %s", exc)
        return None


async def mcp_routes_live() -> bool | None:
    """Ob der laufende Proxy die MCP-Pfade ans Backend leitet.

    None, wenn die Admin-API nicht erreichbar ist — dann ist die Frage
    unbeantwortet und nicht etwa mit „nein" beantwortet.

    Gesucht wird im JSON der adaptierten Konfiguration nach den Pfaden in
    Anführungszeichen (``"/mcp"``). Das ist bewusst eine Textsuche statt
    einer Strukturauswertung: Caddys JSON-Aufbau ist ein Implementierungs-
    detail, die Pfade sind es nicht."""
    raw = await _live_config()
    if raw is None:
        return None
    return all(f'"{pfad}"' in raw for pfad in REQUIRED_MCP_PATHS)


async def diagnose_proxy(db: AsyncSession) -> ProxyBefund:
    """Den Zustand des Reverse Proxy für die Anzeige im Portal erheben."""
    datei_da = CADDYFILE_PATH.is_file()
    datei_routen: bool | None = None
    if datei_da:
        try:
            datei_routen = has_mcp_routes(CADDYFILE_PATH.read_text())
        except OSError:
            datei_routen = None
    return ProxyBefund(
        routen_aktiv=await mcp_routes_live(),
        persistierte_datei=datei_da,
        datei_hat_routen=datei_routen,
        setup_werte_vorhanden=await _persisted_setup_values(db) is not None,
    )


@dataclass(frozen=True)
class Reparatur:
    """Was die Proxy-Reparatur erreicht hat.

    ``erfolg`` und ``dauerhaft`` sind zwei Fragen, nicht eine: die Routen
    können im laufenden Proxy stehen, ohne dass sich die Konfiguration
    hinterlegen ließ. Das ist kein Fehlschlag — die Schnittstelle ist danach
    erreichbar —, aber auch kein fertiger Zustand, denn der nächste Neustart
    des Caddy-Containers wirft sie weg. Wer beides in ein Bool presst, muss
    sich für eine Lüge entscheiden."""

    erfolg: bool
    dauerhaft: bool
    meldung: str


def _caddyfile_schreiben(inhalt: str) -> None:
    """Das Caddyfile atomar ersetzen.

    Über eine Temporärdatei im Zielverzeichnis und ``os.replace``. Zwei Gründe:

    Erstens hinterlässt ein abgebrochener Schreibvorgang so kein halbes
    Caddyfile — mit dem käme Caddy beim nächsten Start nicht hoch, und zwar
    genau dann, wenn niemand hinsieht.

    Zweitens ersetzt ``os.replace`` eine Datei, die einem anderen Benutzer
    gehört, solange das *Verzeichnis* beschreibbar ist. Auf gewachsenen
    Installationen gehört ``/certs/Caddyfile`` oft noch einem früheren, als
    root laufenden Backend; ``write_text`` scheiterte dort mit EACCES, obwohl
    an den Rechten nichts auszusetzen war.

    Die Temporärdatei entsteht im Verzeichnis des Ziels, nicht in ``CERTS_DIR``.
    Im Betrieb ist das dasselbe, aber ``os.replace`` ist nur innerhalb eines
    Dateisystems atomar — und die Sicherheit oben gilt für das Verzeichnis, in
    dem die Zieldatei tatsächlich liegt.
    """
    ziel = Path(CADDYFILE_PATH)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=ziel.parent, prefix=".Caddyfile.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(inhalt)
        # mkstemp legt mit 0600 an; Caddy soll die Datei lesen können, auch
        # wenn es einmal nicht als root laufen sollte.
        os.chmod(tmp, 0o644)
        os.replace(tmp, ziel)
    except BaseException:
        with suppress(OSError):
            os.unlink(tmp)
        raise


def _rechte_hinweis(exc: OSError) -> str:
    """Warum das Schreiben scheiterte, in einem Satz für den Betreiber.

    Bei EACCES ist die Ursache bekannt und die Frage „läuft der Container mit
    Schreibrecht?" nur eine Rückfrage, die niemand ohne SSH beantworten kann —
    also lieber sagen, was die Instanz selbst dagegen tut."""
    if exc.errno == errno.EACCES:
        return (
            "Das Verzeichnis /certs gehört noch einem anderen Benutzer als dem "
            "Backend — ein Überbleibsel aus der Zeit, als das Backend als root "
            "lief. Der Caddy-Container zieht die Besitzrechte beim nächsten "
            "Update gerade; danach genügt ein erneuter Klick."
        )
    return f"Das Schreiben scheiterte mit: {exc.strerror}."


async def repair_mcp_routes(db: AsyncSession) -> Reparatur:
    """Die MCP-Routen in den Proxy bringen.

    Schreibt ein frisch erzeugtes Caddyfile nach ``/certs/Caddyfile`` und lädt
    es über die Admin-API nach. Beides ist gewollt: das Laden wirkt sofort, die
    Datei sorgt dafür, dass es einen Caddy-Neustart übersteht.

    Scheitert nur das Schreiben, wird trotzdem nachgeladen. Ein erreichbarer
    MCP-Endpunkt, der einen Neustart nicht überlebt, ist mehr wert als eine
    Fehlermeldung — und der Unterschied steht in der Rückmeldung.

    Anders als ``ensure_caddyfile_current`` steigt diese Funktion **nicht**
    aus, wenn noch keine persistierte Datei existiert. Genau dieser Fall — der
    Container läuft mit der vom Entrypoint erzeugten Konfiguration von vor dem
    MCP-Feature — ließ sich bisher nur per SSH beheben. Dass die Instanz
    danach eine persistierte Datei hat, ist eine dauerhafte Änderung an ihrer
    Betriebsweise; deshalb passiert das nur auf ausdrückliche Anforderung aus
    dem Portal und nicht beim Start."""
    werte = await _persisted_setup_values(db)
    if werte is None:
        return Reparatur(False, False, (
            "Die Setup-Werte (Domain, TLS-Modus) stehen nicht in der Datenbank — "
            "daraus lässt sich keine Proxy-Konfiguration erzeugen. Bitte den "
            "Setup-Assistenten erneut durchlaufen."
        ))

    domain, tls_mode, acme_email = werte
    caddyfile = generate_caddyfile(domain, tls_mode, acme_email)

    schreibfehler: OSError | None = None
    try:
        _caddyfile_schreiben(caddyfile)
    except OSError as exc:
        schreibfehler = exc
        logger.warning("Caddyfile konnte nicht geschrieben werden: %s", exc)

    if not await reload_caddy(caddyfile):
        if schreibfehler is not None:
            return Reparatur(False, False, (
                "Die Proxy-Konfiguration ließ sich weder hinterlegen noch "
                f"nachladen. {_rechte_hinweis(schreibfehler)} Caddys Admin-API "
                "war zudem nicht erreichbar."
            ))
        return Reparatur(False, False, (
            "Die Konfiguration wurde hinterlegt, aber Caddy hat sie nicht "
            "übernommen — die Admin-API war nicht erreichbar. Sie greift beim "
            "nächsten Start des Caddy-Containers."
        ))

    if await mcp_routes_live() is False:
        # Geschrieben, geladen, und trotzdem fehlen die Pfade: dann stimmt an
        # der erzeugten Konfiguration etwas nicht, und das soll nicht als
        # Erfolg durchgehen.
        return Reparatur(False, False, (
            "Die Konfiguration wurde übernommen, die MCP-Pfade fehlen aber "
            "weiterhin. Bitte die Logs des Backends und von Caddy ansehen."
        ))

    if schreibfehler is not None:
        logger.info(
            "MCP-Routen im laufenden Proxy hergestellt (Domain %s), aber nicht "
            "hinterlegt", domain,
        )
        return Reparatur(True, False, (
            "Die MCP-Pfade sind jetzt im laufenden Proxy aktiv — die "
            "Schnittstelle ist von außen erreichbar. Dauerhaft hinterlegen "
            f"ließ sich die Konfiguration nicht. {_rechte_hinweis(schreibfehler)} "
            "Bis dahin verliert ein Neustart des Caddy-Containers die Routen."
        ))

    logger.info("MCP-Routen im Proxy hergestellt (Domain %s)", domain)
    return Reparatur(True, True, "Der Reverse Proxy leitet die MCP-Pfade jetzt ans Backend.")


async def _persisted_setup_values(db: AsyncSession) -> tuple[str, str, str] | None:
    """The domain / TLS mode / ACME mail the setup wizard stored, or None when
    the instance has not completed setup (nothing to regenerate from)."""
    result = await db.execute(
        select(SystemSetting).where(
            SystemSetting.key.in_(("domain", "tls_mode", "acme_email"))
        )
    )
    values = {row.key: row.value for row in result.scalars()}
    domain = (values.get("domain") or "").strip()
    if not domain:
        return None
    return (
        domain,
        (values.get("tls_mode") or "auto").strip() or "auto",
        (values.get("acme_email") or "admin@example.com").strip() or "admin@example.com",
    )


async def ensure_caddyfile_current(db: AsyncSession) -> bool:
    """Upgrade a persisted Caddyfile that predates a routing or hardening change.

    Covers two retrofits: the security headers, and the MCP/OAuth routes at the
    site root. Both share the same mechanism — a persisted /certs/Caddyfile is
    written once at setup time and would otherwise never learn about anything
    added later.

    Returns True when the file was rewritten. Never raises: a proxy config that
    cannot be repaired must not stop the backend from booting — the failure is
    logged and the (outdated but working) config stays in place.
    """
    try:
        if not CADDYFILE_PATH.is_file():
            # No persisted config → Caddy runs in env-var mode, whose generated
            # Caddyfile (caddy/entrypoint.sh) already carries the headers.
            return False

        current = CADDYFILE_PATH.read_text()
        missing = []
        if not has_security_headers(current):
            missing.append("security headers")
        if not has_mcp_routes(current):
            missing.append("MCP/OAuth routes")
        if not missing:
            return False

        values = await _persisted_setup_values(db)
        if values is None:
            logger.warning(
                "Persisted Caddyfile is missing %s but no setup domain is stored — "
                "re-run the setup wizard to regenerate the proxy config.",
                " and ".join(missing),
            )
            return False

        domain, tls_mode, acme_email = values
        regenerated = generate_caddyfile(domain, tls_mode, acme_email)

        # Schreiben und Nachladen sind unabhängig voneinander. Gehört /certs
        # noch einem früheren, als root laufenden Backend, scheitert das
        # Schreiben — und vor dieser Trennung blieb dann auch das Nachladen
        # aus. Eine solche Instanz hat den Retrofit bei jedem einzelnen Start
        # verpasst, obwohl er nur über die Admin-API hätte laufen müssen.
        try:
            _caddyfile_schreiben(regenerated)
            hinterlegt = True
        except OSError as exc:
            hinterlegt = False
            logger.warning(
                "Persisted Caddyfile could not be rewritten (%s) — applying the "
                "config via the admin API only; it will not survive a Caddy "
                "restart until the ownership of /certs is corrected.", exc,
            )

        reloaded = await reload_caddy(regenerated)
        logger.warning(
            "Persisted Caddyfile was missing %s and was regenerated for domain %s "
            "(persisted: %s, live reload: %s).",
            " and ".join(missing),
            domain,
            "ok" if hinterlegt else "failed",
            "ok" if reloaded else "deferred to next Caddy start",
        )
        return hinterlegt
    except Exception:
        logger.warning("Caddyfile currency check failed", exc_info=True)
        return False
