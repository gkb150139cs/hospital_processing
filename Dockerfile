FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Run as an unprivileged user
RUN useradd --create-home appuser
USER appuser

EXPOSE 8000

# Render (and most PaaS) inject PORT; default to 8000 for local/docker-compose.
# Boot markers diagnose where startup dies on Render (exit 128 with no logs).
CMD ["sh", "-c", "echo \"[boot] container started, uid=$(id -u), PORT=${PORT:-unset}\" && python -c 'import app.main' && echo '[boot] app imports OK' && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
