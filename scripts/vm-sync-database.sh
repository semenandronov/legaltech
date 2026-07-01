#!/usr/bin/env bash
# Dump local Docker Postgres → upload → restore on Yandex VM.
#
# Prerequisites:
#   - Local: docker compose postgres running (legal-ai-vault-db)
#   - VM:    ./scripts/vm-postgres.sh setup
#
#   ./scripts/vm-sync-database.sh
#   ./scripts/vm-sync-database.sh --reuse-dump   # skip pg_dump, use existing file
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lib/vm-common.sh
source "${ROOT}/scripts/lib/vm-common.sh"

DUMP_DIR="${ROOT}/.vm-db-sync"
DUMP_FILE="${DUMP_DIR}/legal_ai.dump"
REMOTE_DUMP="${VM_REMOTE_DIR}/.db-sync/legal_ai.dump"
REUSE_DUMP=false

for arg in "$@"; do
  case "$arg" in
    --reuse-dump) REUSE_DUMP=true ;;
    -h|--help)
      sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "Unknown arg: ${arg}" >&2
      exit 1
      ;;
esac
done

vm_postgres_credentials "${ROOT}/.env"
mkdir -p "${DUMP_DIR}"

dump_local() {
  if ! docker ps --format '{{.Names}}' | grep -qx "${LOCAL_PG_CONTAINER}"; then
    echo "Local Postgres not running (${LOCAL_PG_CONTAINER}). Start: docker compose up -d" >&2
    exit 1
  fi
  echo "==> Dump local database (custom format)..."
  rm -f "${DUMP_FILE}"
  docker exec "${LOCAL_PG_CONTAINER}" pg_dump \
    -U "${POSTGRES_USER}" \
    -d legal_ai \
    --format=custom \
    --no-owner \
    --no-acl \
    > "${DUMP_FILE}"
  du -h "${DUMP_FILE}" | awk '{print "Local dump:", $1}'
}

upload_dump() {
  echo "==> Upload dump to VM (may take several minutes)..."
  vm_ssh "mkdir -p '${VM_REMOTE_DIR}/.db-sync'"
  vm_ssh "cat > '${REMOTE_DUMP}'" < "${DUMP_FILE}"
  vm_ssh "du -h '${REMOTE_DUMP}'"
}

restore_on_vm() {
  echo "==> Restore on VM (uploads on disk are NOT modified)..."
  local uploads_count
  uploads_count="$(vm_uploads_file_count)"
  echo "==> VM uploads unchanged during DB restore: ${uploads_count} file(s) on disk"
  vm_ssh bash -s <<EOF
set -euo pipefail
cd '${VM_REMOTE_DIR}'
export POSTGRES_USER='${POSTGRES_USER}'
export POSTGRES_PASSWORD='${POSTGRES_PASSWORD}'

if ! sudo docker ps --format '{{.Names}}' | grep -qx legal-ai-postgres; then
  echo "Postgres not running on VM. Run: ./scripts/vm-postgres.sh setup" >&2
  exit 1
fi

echo "Terminating connections..."
sudo docker exec legal-ai-postgres psql -U "\${POSTGRES_USER}" -d postgres -v ON_ERROR_STOP=1 -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'legal_ai' AND pid <> pg_backend_pid();" \
  >/dev/null 2>&1 || true

sudo docker exec legal-ai-postgres psql -U "\${POSTGRES_USER}" -d postgres -v ON_ERROR_STOP=1 -c \
  "DROP DATABASE IF EXISTS legal_ai;"
sudo docker exec legal-ai-postgres psql -U "\${POSTGRES_USER}" -d postgres -v ON_ERROR_STOP=1 -c \
  "CREATE DATABASE legal_ai;"

echo "Running pg_restore..."
sudo docker run --rm \
  --network legal-ai-internal \
  -v '${REMOTE_DUMP}:/dump/legal_ai.dump:ro' \
  ${VM_PG_IMAGE} \
  pg_restore \
    --dbname="postgresql://\${POSTGRES_USER}:\${POSTGRES_PASSWORD}@postgres:5432/legal_ai" \
    --no-owner \
    --no-acl \
    /dump/legal_ai.dump || true

sudo docker exec legal-ai-postgres psql -U "\${POSTGRES_USER}" -d legal_ai -v ON_ERROR_STOP=1 -c \
  "CREATE EXTENSION IF NOT EXISTS vector;"

echo "==> Row counts (sample):"
sudo docker exec legal-ai-postgres psql -U "\${POSTGRES_USER}" -d legal_ai -t -c \
  "SELECT 'cases' AS t, count(*) FROM cases UNION ALL SELECT 'files', count(*) FROM files;"
EOF
}

if [[ "${REUSE_DUMP}" != "true" ]] || [[ ! -s "${DUMP_FILE}" ]]; then
  dump_local
else
  du -h "${DUMP_FILE}" | awk '{print "Reusing dump:", $1}'
fi

upload_dump
restore_on_vm

echo "==> Database sync complete"
