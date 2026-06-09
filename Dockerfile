FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY --chmod=755 docker-entrypoint.sh /docker-entrypoint.sh

# Run as an unprivileged user
RUN useradd --create-home appuser
USER appuser

EXPOSE 8000

# ENTRYPOINT (unlike CMD) cannot be replaced by a PaaS start-command override.
ENTRYPOINT ["/docker-entrypoint.sh"]
