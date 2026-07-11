#!/usr/bin/env bash
# Локальный Postgres для эксперимента (замер latency vs Neon).
# Использование:
#   ./scripts/local_db_experiment.sh start    — бэкап Neon URL, docker, дамп, restore
#   ./scripts/local_db_experiment.sh revert   — вернуть DATABASE_URL и убрать маркер
#   ./scripts/local_db_experiment.sh stop     — revert + docker compose down
#   ./scripts/local_db_experiment.sh status   — состояние эксперимента
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT/docker-compose.yml"
ENV_FILE="$ROOT/.env"
BACKEND_ENV="$ROOT/backend/.env"
NEON_BACKUP="$ROOT/.env.neon-backup"
MARKER="$ROOT/.local-db-experiment-active"
DUMP_DIR="$ROOT/.local-db-experiment"
DUMP_FILE="$DUMP_DIR/neon.dump"
LOCAL_URL='postgresql://user:password@localhost:5432/legal_ai'
CONTAINER='legal-ai-vault-db'
PG_IMAGE='postgres:17'

read_database_url() {
  local file="$1"
  if [[ ! -f "$file" ]]; then
    echo "missing env file: $file" >&2
    return 1
  fi
  python3 - "$file" <<'PY'
import re, sys
from pathlib import Path
text = Path(sys.argv[1]).read_text(encoding="utf-8")
m = re.search(r'^DATABASE_URL\s*=\s*["\']?([^"\'#\n]+)', text, re.M)
if not m:
    raise SystemExit("DATABASE_URL not found")
print(m.group(1).strip())
PY
}

write_database_url() {
  local file="$1"
  local url="$2"
  python3 - "$file" "$url" <<'PY'
import re, sys
from pathlib import Path
path = Path(sys.argv[1])
url = sys.argv[2]
text = path.read_text(encoding="utf-8")
if re.search(r'^DATABASE_URL\s*=', text, re.M):
    text = re.sub(
        r'^DATABASE_URL\s*=.*$',
        f'DATABASE_URL="{url}"',
        text,
        count=1,
        flags=re.M,
    )
else:
    text = f'DATABASE_URL="{url}"\n' + text
path.write_text(text, encoding="utf-8")
PY
}

backup_neon_url() {
  if [[ -f "$NEON_BACKUP" ]]; then
    echo "Neon backup already exists: $NEON_BACKUP"
    return 0
  fi
  local neon_url
  neon_url="$(read_database_url "$ENV_FILE")"
  if [[ "$neon_url" == *localhost* ]]; then
    echo "Root .env already points to localhost; cannot backup Neon URL." >&2
    exit 1
  fi
  printf 'DATABASE_URL="%s"\n' "$neon_url" > "$NEON_BACKUP"
  chmod 600 "$NEON_BACKUP"
  echo "Saved Neon DATABASE_URL -> $NEON_BACKUP"
}

switch_to_local_url() {
  write_database_url "$ENV_FILE" "$LOCAL_URL"
  if [[ -f "$BACKEND_ENV" ]]; then
    write_database_url "$BACKEND_ENV" "$LOCAL_URL"
  fi
  date -u +"%Y-%m-%dT%H:%M:%SZ" > "$MARKER"
  echo "DATABASE_URL -> localhost (marker: $MARKER)"
}

restore_neon_url() {
  if [[ ! -f "$NEON_BACKUP" ]]; then
    echo "No Neon backup at $NEON_BACKUP" >&2
    exit 1
  fi
  local neon_url
  neon_url="$(read_database_url "$NEON_BACKUP")"
  write_database_url "$ENV_FILE" "$neon_url"
  if [[ -f "$BACKEND_ENV" ]]; then
    write_database_url "$BACKEND_ENV" "$neon_url"
  fi
  rm -f "$MARKER"
  echo "DATABASE_URL restored from $NEON_BACKUP"
}

wait_for_postgres() {
  echo "Waiting for Postgres..."
  for _ in $(seq 1 40); do
    if docker exec "$CONTAINER" pg_isready -U user -d legal_ai >/dev/null 2>&1; then
      echo "Postgres is ready."
      return 0
    fi
    sleep 1
  done
  echo "Postgres did not become ready in time." >&2
  exit 1
}

dump_from_neon() {
  mkdir -p "$DUMP_DIR"
  rm -f "$DUMP_FILE"
  local neon_url
  neon_url="$(read_database_url "$NEON_BACKUP")"
  echo "Dumping from Neon (this may take a while)..."
  docker run --rm \
    -v "$DUMP_DIR:/dump" \
    "$PG_IMAGE" \
    pg_dump "$neon_url" \
      --format=custom \
      --no-owner \
      --no-acl \
      --file=/dump/neon.dump
  if [[ ! -s "$DUMP_FILE" ]]; then
    echo "Dump failed or empty: $DUMP_FILE" >&2
    exit 1
  fi
  du -h "$DUMP_FILE" | awk '{print "Dump saved:", $1, $2}'
}

restore_to_local() {
  if [[ ! -f "$DUMP_FILE" ]]; then
    echo "Dump not found: $DUMP_FILE" >&2
    exit 1
  fi
  echo "Recreating local database legal_ai..."
  docker exec "$CONTAINER" psql -U user -d postgres -v ON_ERROR_STOP=1 -c \
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'legal_ai' AND pid <> pg_backend_pid();" \
    >/dev/null 2>&1 || true
  docker exec "$CONTAINER" psql -U user -d postgres -v ON_ERROR_STOP=1 -c \
    "DROP DATABASE IF EXISTS legal_ai;"
  docker exec "$CONTAINER" psql -U user -d postgres -v ON_ERROR_STOP=1 -c \
    "CREATE DATABASE legal_ai;"
  echo "Restoring dump into local Postgres..."
  docker run --rm \
    --network "container:$CONTAINER" \
    -v "$DUMP_DIR:/dump" \
    "$PG_IMAGE" \
    pg_restore \
      --dbname="$LOCAL_URL" \
      --no-owner \
      --no-acl \
      --verbose \
      /dump/neon.dump || true
  docker exec "$CONTAINER" psql -U user -d legal_ai -v ON_ERROR_STOP=1 -c \
    "CREATE EXTENSION IF NOT EXISTS vector;"
  echo "Local restore finished (pg_restore may report harmless object-exists warnings)."
}

cmd_start() {
  backup_neon_url
  echo "Starting docker compose..."
  docker compose -f "$COMPOSE_FILE" up -d
  wait_for_postgres
  if [[ ! -s "$DUMP_FILE" ]]; then
    dump_from_neon
  else
    du -h "$DUMP_FILE" | awk '{print "Reusing existing dump:", $1, $2}'
  fi
  restore_to_local
  switch_to_local_url
  echo ""
  echo "Local DB experiment is ACTIVE."
  echo "Restart backend to use localhost. Revert: ./scripts/local_db_experiment.sh revert"
}

cmd_revert() {
  restore_neon_url
  echo "Reverted to Neon DATABASE_URL. Restart backend."
}

cmd_stop() {
  cmd_revert
  docker compose -f "$COMPOSE_FILE" down
  echo "Docker Postgres stopped."
}

cmd_status() {
  if [[ -f "$MARKER" ]]; then
    echo "Experiment ACTIVE since $(cat "$MARKER")"
  else
    echo "Experiment not active."
  fi
  if docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    echo "Container $CONTAINER: running"
  else
    echo "Container $CONTAINER: not running"
  fi
  if [[ -f "$NEON_BACKUP" ]]; then
    echo "Neon backup: present ($NEON_BACKUP)"
  else
    echo "Neon backup: missing"
  fi
  if [[ -f "$DUMP_FILE" ]]; then
    du -h "$DUMP_FILE" | awk '{print "Dump:", $1, $2}'
  fi
  if [[ -f "$ENV_FILE" ]]; then
    local current
    current="$(read_database_url "$ENV_FILE")"
    if [[ "$current" == *localhost* ]]; then
      echo "DATABASE_URL: localhost"
    else
      echo "DATABASE_URL: remote (Neon or other)"
    fi
  fi
}

case "${1:-}" in
  start) cmd_start ;;
  revert) cmd_revert ;;
  stop) cmd_stop ;;
  status) cmd_status ;;
  *)
    echo "Usage: $0 {start|revert|stop|status}" >&2
    exit 1
    ;;
esac
