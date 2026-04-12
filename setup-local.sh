#!/usr/bin/env bash
# Локальная установка: Python 3.10+, Node, опционально Docker Postgres + init_db.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# macOS: pg_config от Homebrew libpq (если pip всё же собирает psycopg2 из исходников)
if [[ "$(uname -s)" == "Darwin" ]]; then
  for p in "/opt/homebrew/opt/libpq/bin" "/usr/local/opt/libpq/bin"; do
    if [[ -x "$p/pg_config" ]]; then
      export PATH="$p:$PATH"
      echo "PATH: добавлен $p (pg_config для libpq)"
      break
    fi
  done
fi

pick_python() {
  for c in python3.12 python3.11 python3.10 python3; do
    if command -v "$c" >/dev/null 2>&1; then
      ver="$("$c" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
      major="${ver%%.*}"
      minor="${ver#*.}"
      if [ "$major" -eq 3 ] && [ "$minor" -ge 10 ]; then
        echo "$c"
        return 0
      fi
    fi
  done
  return 1
}

PY="$(pick_python || true)"
if [ -z "${PY:-}" ]; then
  echo "Нужен Python 3.10+. Установите python.org или: brew install python@3.12"
  exit 1
fi

echo "Python: $PY ($($PY --version))"

rm -rf venv
"$PY" -m venv venv
# shellcheck disable=SC1091
source venv/bin/activate
pip install --upgrade pip
pip install -r backend/requirements.txt

cd frontend
npm install --legacy-peer-deps
cd "$ROOT"

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  echo "Docker: поднимаю postgres (pgvector)..."
  docker compose up -d
  echo "Ожидание готовности БД..."
  for i in $(seq 1 30); do
    if docker compose exec -T postgres pg_isready -U user -d legal_ai >/dev/null 2>&1; then
      echo "Postgres готов."
      break
    fi
    sleep 1
  done
  # shellcheck disable=SC1091
  source venv/bin/activate
  (cd backend && python init_db.py)
else
  echo "Docker недоступен — пропускаю docker compose и init_db. Поднимите Postgres с pgvector вручную."
fi

echo ""
echo "Готово. Секреты — в .env в корне репозитория."
echo "Backend:  source venv/bin/activate && cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
echo "Frontend: cd frontend && npm run dev"
