#!/bin/sh
set -e

echo "[start_cron.sh] Iniciando tailscaled..."
tailscaled --tun=userspace-networking --statedir=/tmp/tailscale --socks5-server=localhost:1055 &

sleep 2

if [ -n "$TAILSCALE_AUTH_KEY" ]; then
    echo "[start_cron.sh] Conectando a Tailscale..."
    tailscale up \
        --authkey="${TAILSCALE_AUTH_KEY}" \
        --hostname="ipdv-cron-railway" \
        --accept-routes \
        --accept-dns=false
    echo "[start_cron.sh] Tailscale conectado."
else
    echo "[start_cron.sh] ADVERTENCIA: TAILSCALE_AUTH_KEY no configurada."
fi

echo "[start_cron.sh] Iniciando cron..."
exec python cron.py