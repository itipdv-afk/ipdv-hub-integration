FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY sync_core.py .
COPY cron.py .
COPY webhook.py .

RUN mkdir -p /app/logs

ENV PYTHONUNBUFFERED=1

# El servidor webhook se mantiene siempre activo.
# El cron (cron.py) se ejecuta por separado según railway.json.
CMD ["python", "webhook.py"]
