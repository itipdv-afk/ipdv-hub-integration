FROM python:3.12-slim

# Directorio de trabajo dentro del contenedor
WORKDIR /app

# Copiar dependencias primero (mejor caché de Docker)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código
COPY sync.py .

# El script escribe logs en /app/logs
RUN mkdir -p /app/logs

# Variable de entorno para que Python no bufferice stdout (ver logs en tiempo real)
ENV PYTHONUNBUFFERED=1

CMD ["python", "sync.py"]
