#!/bin/sh
# ==============================================================================
# start.sh — Levanta Tailscale y luego el servidor webhook
# ==============================================================================
# Variables de entorno requeridas (configurar en Railway):
#   TAILSCALE_AUTH_KEY  — Auth key generada en tailscale.com/settings/keys
#                         Usar tipo "Reusable" y "Ephemeral" para contenedores
# ==============================================================================

set -e

# ── 1. Arrancar el daemon de Tailscale ────────────────────────────────────────
echo "[start.sh] Iniciando tailscaled..."
tailscaled --tun=userspace-networking --statedir=/tmp/tailscale &
TAILSCALED_PID=$!

# Esperar a que el daemon esté listo
sleep 2

# ── 2. Conectar a la red Tailscale ───────────────────────────────────────────
if [ -n "$TAILSCALE_AUTH_KEY" ]; then
    echo "[start.sh] Conectando a Tailscale..."
    tailscale up \
        --authkey="${TAILSCALE_AUTH_KEY}" \
        --hostname="ipdv-hub-railway" \
        --accept-routes \
        --shields-up
    echo "[start.sh] Tailscale conectado."
else
    echo "[start.sh] ADVERTENCIA: TAILSCALE_AUTH_KEY no configurada — salteando Tailscale."
fi

# ── 3. Arrancar gunicorn ──────────────────────────────────────────────────────
echo "[start.sh] Iniciando gunicorn en puerto ${PORT:-8080}..."
exec gunicorn \
    --bind "0.0.0.0:${PORT:-8080}" \
    --workers 1 \
    --timeout 120 \
    webhook:app
