FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY sync_core.py .
COPY cron.py .
COPY webhook.py .

RUN mkdir -p /app/logs

ENV PYTHONUNBUFFERED=1

# Usar gunicorn en lugar de Flask dev server, escuchando en $PORT
CMD gunicorn --bind 0.0.0.0:$PORT --workers 1 --timeout 120 webhook:app