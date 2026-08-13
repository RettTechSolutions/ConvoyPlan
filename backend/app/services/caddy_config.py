"""Generation — and self-healing — of the Caddy reverse-proxy configuration.

The setup wizard writes a Caddyfile to the shared ``/certs`` volume and Caddy's
entrypoint prefers that persisted file over its env-var-generated fallback.
Because the file is written exactly once (during initial setup) it freezes the
proxy configuration of that install forever: an instance that was set up before
the hardening headers existed keeps serving responses **without** HSTS, CSP,
``X-Frame-Options``, ``X-Content-Type-Options``, ``Referrer-Policy`` and
``Permissions-Policy`` — even after the images have been updated many times.

``ensure_security_headers()`` closes that gap. On every backend start the
persisted Caddyfile is checked for the hardening headers; if any are missing it
is regenerated from the persisted setup settings (domain / TLS mode / ACME
mail) and hot-reloaded via Caddy's admin API, so the fix lands without a manual
re-run of the setup wizard.

ISO 27001 A.8.26 (application security requirements).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.settings import SystemSetting

logger = logging.getLogger(__name__)

CERTS_DIR = Path("/certs")
CADDYFILE_PATH = CERTS_DIR / "Caddyfile"

# Every header the generated config must carry. `ensure_security_headers()`
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


async def ensure_security_headers(db: AsyncSession) -> bool:
    """Upgrade a persisted Caddyfile that predates the security headers.

    Returns True when the file was rewritten. Never raises: a proxy config that
    cannot be repaired must not stop the backend from booting — the failure is
    logged and the (unhardened but working) config stays in place.
    """
    try:
        if not CADDYFILE_PATH.is_file():
            # No persisted config → Caddy runs in env-var mode, whose generated
            # Caddyfile (caddy/entrypoint.sh) already carries the headers.
            return False

        current = CADDYFILE_PATH.read_text()
        if has_security_headers(current):
            return False

        values = await _persisted_setup_values(db)
        if values is None:
            logger.warning(
                "Persisted Caddyfile lacks security headers but no setup domain is "
                "stored — re-run the setup wizard to regenerate the proxy config."
            )
            return False

        domain, tls_mode, acme_email = values
        regenerated = generate_caddyfile(domain, tls_mode, acme_email)
        CADDYFILE_PATH.write_text(regenerated)
        reloaded = await reload_caddy(regenerated)
        logger.warning(
            "Persisted Caddyfile lacked the security headers and was regenerated "
            "for domain %s (live reload: %s).",
            domain,
            "ok" if reloaded else "deferred to next Caddy start",
        )
        return True
    except Exception:
        logger.warning("Caddyfile security-header check failed", exc_info=True)
        return False
