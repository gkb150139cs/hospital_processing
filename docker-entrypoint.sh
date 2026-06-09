#!/bin/sh
# Entrypoint cannot be bypassed by a dashboard "Docker Command" override
# (the override merely becomes $* here), so the service always starts.
echo "[boot] entrypoint running, uid=$(id -u), PORT=${PORT:-unset}, args: ${*:-<none>}"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
