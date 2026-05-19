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

cat > /tmp/Caddyfile << CADDYEOF
{
    admin 0.0.0.0:2019
    email $ACME_EMAIL
}

$SITE_ADDRESS {
    $TLS_DIRECTIVE

    handle /api/* {
        reverse_proxy backend:8000
    }
    handle /ws/* {
        reverse_proxy backend:8000
    }
    handle {
        reverse_proxy frontend:3000
    }
}
CADDYEOF

echo "[caddy] Starting with domain: $DOMAIN (env-var mode)"
exec caddy run --config /tmp/Caddyfile --adapter caddyfile
