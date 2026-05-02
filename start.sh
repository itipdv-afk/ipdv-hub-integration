#!/bin/sh
set -e

echo "[start.sh] Iniciando tailscaled..."
tailscaled --tun=userspace-networking --statedir=/tmp/tailscale --socks5-server=localhost:1055 &

sleep 2

if [ -n "$TAILSCALE_AUTH_KEY" ]; then
    echo "[start.sh] Conectando a Tailscale..."
    tailscale up \
        --authkey="${TAILSCALE_AUTH_KEY}" \
        --hostname="ipdv-hub-railway" \
        --accept-routes \
        --accept-dns=false
    echo "[start.sh] Tailscale conectado."
    tailscale status
else
    echo "[start.sh] ADVERTENCIA: TAILSCALE_AUTH_KEY no configurada."
fi

echo "[start.sh] Iniciando gunicorn en puerto ${PORT:-8080}..."
exec gunicorn \
    --bind "0.0.0.0:${PORT:-8080}" \
    --workers 1 \
    --timeout 120 \
    webhook:app