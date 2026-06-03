#!/bin/sh
set -e

# If setup wizard wrote a Caddyfile to the shared volume, use it directly.
if [ -f "/certs/Caddyfile" ]; then
    echo "[caddy] Using persisted Caddyfile from /certs/Caddyfile"
    exec caddy run --config /certs/Caddyfile --adapter caddyfile
fi

# Otherwise fall back to env-var-based generation (initial start before setup).
DOMAIN="${DOMAIN:-localhost}"
ACME_EMAIL="${ACME_EMAIL:-admin@example.com}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
BACKEND_PORT="${BACKEND_PORT:-8000}"

if [ -n "$CADDY_TLS_CERT" ] && [ -n "$CADDY_TLS_KEY" ]; then
    TLS_DIRECTIVE="tls $CADDY_TLS_CERT $CADDY_TLS_KEY"
elif [ "$DOMAIN" = "localhost" ]; then
    TLS_DIRECTIVE="tls internal"
else
    TLS_DIRECTIVE=""
fi

# Validate DOMAIN to prevent Caddyfile injection
case "$DOMAIN" in
    *[!a-zA-Z0-9._-]*)
        echo "[caddy] ERROR: DOMAIN contains invalid characters: $DOMAIN" >&2
        exit 1
        ;;
esac

# For bare IP addresses Caddy would attempt ACME (which fails for private IPs).
# Force plain HTTP by prefixing with http:// when DOMAIN is an IPv4 address.
case "$DOMAIN" in
    [0-9]*.[0-9]*.[0-9]*.[0-9]*)
        SITE_ADDRESS="http://$DOMAIN"
        TLS_DIRECTIVE=""
        ;;
    *)
        SITE_ADDRESS="$DOMAIN"
        ;;
esac

# Content-Security-Policy. Report-Only by default (safe); CSP_ENFORCE=true enforces.
CSP_VALUE="default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'self'; img-src 'self' data: blob: https://tile.openstreetmap.org; style-src 'self' 'unsafe-inline'; script-src 'self'; worker-src 'self' blob:; font-src 'self' data:; connect-src 'self' https://tile.openstreetmap.org https://nominatim.openstreetmap.org ws://$DOMAIN wss://$DOMAIN"
if [ "${CSP_ENFORCE:-false}" = "true" ]; then
    CSP_HEADER="Content-Security-Policy"
else
    CSP_HEADER="Content-Security-Policy-Report-Only"
fi

cat > /tmp/Caddyfile << CADDYEOF
{
    admin 0.0.0.0:2019
    email $ACME_EMAIL
}

$SITE_ADDRESS {
    $TLS_DIRECTIVE

    # ── Security headers (ISO 27001 A.8.26) ──────────────────────────────
    # The Content-Security-Policy ships in Report-Only mode by default so it
    # cannot break the map UI; set CSP_ENFORCE=true to enforce it once verified.
    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
        X-Content-Type-Options "nosniff"
        X-Frame-Options "SAMEORIGIN"
        Referrer-Policy "strict-origin-when-cross-origin"
        Permissions-Policy "geolocation=(self), microphone=(), camera=()"
        $CSP_HEADER "$CSP_VALUE"
        -Server
    }

    # SSE endpoint — must flush every chunk immediately, no buffering
    handle /api/admin/update-log {
        reverse_proxy backend:$BACKEND_PORT {
            flush_interval -1
        }
    }
    handle /api/* {
        reverse_proxy backend:$BACKEND_PORT
    }
    handle /ws/* {
        reverse_proxy backend:$BACKEND_PORT {
            flush_interval -1
        }
    }
    handle {
        reverse_proxy frontend:$FRONTEND_PORT
    }
}
CADDYEOF

echo "[caddy] Starting with domain: $DOMAIN (env-var mode)"
exec caddy run --config /tmp/Caddyfile --adapter caddyfile
