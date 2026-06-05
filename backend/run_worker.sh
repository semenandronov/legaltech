#!/bin/sh
# Worker entrypoint (тот же образ, что и API)
cd "$(dirname "$0")" || exit 1
exec uvicorn app.worker_app:app --host 0.0.0.0 --port "${PORT:-8000}"
