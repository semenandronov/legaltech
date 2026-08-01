#!/usr/bin/env bash
# Копирует локальный .env на VM и гарантирует настройки хранения файлов дел.
#
#   export YC_VM_ID=fv4qdpndf1f3c70ugkd3
#   ./scripts/vm-sync-env.sh
#   ./scripts/vm-sync-env.sh /path/to/.env
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lib/vm-common.sh
source "${ROOT}/scripts/lib/vm-common.sh"

VM_ID="${YC_VM_ID}"
REMOTE_DIR="${VM_REMOTE_DIR}"
REMOTE_ENV="${REMOTE_DIR}/.env"
LOCAL_ENV="${1:-${ROOT}/.env}"

if [[ ! -f "${LOCAL_ENV}" ]]; then
  echo "Local .env not found: ${LOCAL_ENV}" >&2
  exit 1
fi

TMP="$(mktemp)"
trap 'rm -f "${TMP}"' EXIT

vm_postgres_credentials "${LOCAL_ENV}"
VM_DB_URL="$(vm_internal_database_url "${LOCAL_ENV}")"

# База: локальный .env; на VM — Postgres в docker-сети (host postgres)
grep -v '^UPLOAD_DIR=' "${LOCAL_ENV}" \
  | grep -v '^FILE_STORE_BYTES_IN_DB=' \
  | grep -v '^CORS_ORIGINS=' \
  | grep -v '^ENVIRONMENT=' \
  | grep -v '^TABULAR_ONLY_MODE=' \
  | grep -v '^ENABLE_INTERNAL_DIAGNOSTICS=' \
  | grep -v '^GIGACHAT_VERIFY_SSL=' \
  | grep -v '^ACCESS_TOKEN_EXPIRE_MINUTES=' \
  | grep -v '^DATABASE_URL=' \
  > "${TMP}" || true
VM_PUBLIC_URL="${VM_PUBLIC_URL:-https://158.160.148.240}"
{
  cat "${TMP}"
  echo ""
  echo "# Postgres on same VM (docker-compose.vm.yml, service name: postgres)"
  echo "POSTGRES_USER=${POSTGRES_USER}"
  echo "POSTGRES_PASSWORD=${POSTGRES_PASSWORD}"
  echo "DATABASE_URL=${VM_DB_URL}"
  echo ""
  echo "# Case file storage (single container + VM volume)"
  echo "UPLOAD_DIR=/app/backend/uploads"
  echo "FILE_STORE_BYTES_IN_DB=false"
  echo "ENVIRONMENT=production"
  echo "TABULAR_ONLY_MODE=true"
  echo "ENABLE_INTERNAL_DIAGNOSTICS=false"
  echo "GIGACHAT_VERIFY_SSL=true"
  echo "ACCESS_TOKEN_EXPIRE_MINUTES=60"
  echo "# CORS for browser (SPA on same host :80 and :8000)"
  echo "CORS_ORIGINS=${VM_PUBLIC_URL},https://xsdwcefrvtgby.ru"
} > "${LOCAL_ENV}.vm.tmp"
mv "${LOCAL_ENV}.vm.tmp" "${TMP}"

vm_ssh "mkdir -p '${REMOTE_DIR}' '${REMOTE_DIR}/uploads' && chmod 755 '${REMOTE_DIR}/uploads'"

echo "==> Upload .env -> ${REMOTE_ENV}"
vm_ssh "cat > '${REMOTE_ENV}' && chmod 600 '${REMOTE_ENV}'" < "${TMP}"

echo "==> Done. Restart app: ./scripts/vm-restart-legal-ai.sh"
