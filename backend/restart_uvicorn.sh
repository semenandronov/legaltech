#!/usr/bin/env bash
# Перезапуск API: освобождает :8000 и поднимает uvicorn (venv в корне репозитория, если есть).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"
for p in $(lsof -ti :8000 2>/dev/null); do kill -9 "$p" 2>/dev/null || true; done
sleep 1
if [[ -x "$ROOT/venv/bin/python" ]]; then
  exec "$ROOT/venv/bin/python" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
fi
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  exec "$ROOT/.venv/bin/python" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
fi
exec python3 -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
