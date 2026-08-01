#!/usr/bin/env bash
# Upload production runtime .env to VM (stdin or PRODUCTION_ENV_FILE).
# Rewrites DATABASE_URL for docker-compose postgres service. Never touches uploads/.
#
#   PRODUCTION_ENV_FILE=.env ./scripts/ci/sync-production-env-remote.sh   # local + yc ssh
#   cat production.env | VM_HOST=... VM_SSH_PRIVATE_KEY_FILE=... ./scripts/ci/sync-production-env-remote.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck source=../lib/vm-common.sh
source "${ROOT}/scripts/lib/vm-common.sh"

VM_REMOTE_DIR="${VM_REMOTE_DIR:-/home/andronovsemen04/legal-ai}"
REMOTE_ENV="${VM_REMOTE_DIR}/.env"
TMP="$(mktemp)"
trap 'rm -f "${TMP}"' EXIT

if [[ -n "${PRODUCTION_ENV_FILE:-}" ]]; then
  cp "${PRODUCTION_ENV_FILE}" "${TMP}"
elif [[ ! -t 0 ]]; then
  cat >"${TMP}"
else
  echo "Set PRODUCTION_ENV_FILE or pipe .env on stdin" >&2
  exit 1
fi

vm_postgres_credentials "${TMP}"
VM_DB_URL="$(vm_internal_database_url "${TMP}")"
VM_PUBLIC_URL="${VM_PUBLIC_URL:-https://158.160.148.240}"

{
  grep -v '^UPLOAD_DIR=' "${TMP}" \
    | grep -v '^FILE_STORE_BYTES_IN_DB=' \
    | grep -v '^CORS_ORIGINS=' \
    | grep -v '^ENVIRONMENT=' \
    | grep -v '^TABULAR_ONLY_MODE=' \
    | grep -v '^ENABLE_INTERNAL_DIAGNOSTICS=' \
    | grep -v '^GIGACHAT_VERIFY_SSL=' \
    | grep -v '^ACCESS_TOKEN_EXPIRE_MINUTES=' \
    | grep -v '^DATABASE_URL=' || true
  echo ""
  echo "# Postgres on same VM (docker-compose.vm.yml)"
  echo "POSTGRES_USER=${POSTGRES_USER}"
  echo "POSTGRES_PASSWORD=${POSTGRES_PASSWORD}"
  echo "DATABASE_URL=${VM_DB_URL}"
  echo ""
  echo "UPLOAD_DIR=/app/backend/uploads"
  echo "FILE_STORE_BYTES_IN_DB=false"
  echo "ENVIRONMENT=production"
  echo "TABULAR_ONLY_MODE=true"
  echo "ENABLE_INTERNAL_DIAGNOSTICS=false"
  echo "GIGACHAT_VERIFY_SSL=true"
  echo "ACCESS_TOKEN_EXPIRE_MINUTES=60"
  echo "CORS_ORIGINS=${VM_PUBLIC_URL},https://xsdwcefrvtgby.ru"
} >"${TMP}.vm"
mv "${TMP}.vm" "${TMP}"

vm_ssh "mkdir -p '${VM_REMOTE_DIR}/uploads' && chmod 755 '${VM_REMOTE_DIR}/uploads'"
vm_ssh "cat > '${REMOTE_ENV}' && chmod 600 '${REMOTE_ENV}'" <"${TMP}"
echo "==> Runtime .env synced to ${REMOTE_ENV}"
