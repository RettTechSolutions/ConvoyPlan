#!/bin/sh
set -e

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

cat > /tmp/Caddyfile << CADDYEOF
{
    email $ACME_EMAIL
}

$DOMAIN {
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

echo "[caddy] Starting with domain: $DOMAIN"
exec caddy run --config /tmp/Caddyfile --adapter caddyfile
