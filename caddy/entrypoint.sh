#!/bin/sh
set -e

DOMAIN="${DOMAIN:-localhost}"
ACME_EMAIL="${ACME_EMAIL:-admin@example.com}"

if [ -n "$CADDY_TLS_CERT" ] && [ -n "$CADDY_TLS_KEY" ]; then
    TLS_DIRECTIVE="tls $CADDY_TLS_CERT $CADDY_TLS_KEY"
elif [ "$DOMAIN" = "localhost" ]; then
    TLS_DIRECTIVE="tls internal"
else
    TLS_DIRECTIVE=""  # automatic Let's Encrypt via ACME
fi

cat > /tmp/Caddyfile << CADDYEOF
{
    email $ACME_EMAIL
}

$DOMAIN {
    $TLS_DIRECTIVE

    reverse_proxy /api/* backend:8000
    reverse_proxy /ws/* backend:8000
    reverse_proxy /* frontend:3000
}
CADDYEOF

echo "[caddy] Starting with domain: $DOMAIN"
exec caddy run --config /tmp/Caddyfile --adapter caddyfile
