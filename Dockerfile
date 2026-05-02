FROM python:3.12-slim

# Dependencias del sistema requeridas por WeasyPrint
# (Cairo, Pango y GLib para renderizado HTML→PDF)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    shared-mime-info \
    curl \
    iptables \
    && rm -rf /var/lib/apt/lists/*

# Instalar Tailscale
RUN curl -fsSL https://pkgs.tailscale.com/stable/debian/bookworm.noarmor.gpg \
        -o /usr/share/keyrings/tailscale-archive-keyring.gpg \
    && curl -fsSL https://pkgs.tailscale.com/stable/debian/bookworm.tailscale-keyring.list \
        -o /etc/apt/sources.list.d/tailscale.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends tailscale \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY sync_core.py .
COPY cron.py .
COPY webhook.py .
COPY receipt_mailer.py .
COPY register_webhook.py .
COPY start.sh .
RUN chmod +x start.sh

RUN mkdir -p /app/logs

ENV PYTHONUNBUFFERED=1
ENV PORT=8080

CMD ["./start.sh"]
