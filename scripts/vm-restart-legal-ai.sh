#!/usr/bin/env bash
# Restart legal-ai stack on VM (Postgres + API via docker compose).
#
#   export YC_VM_ID=fv4qdpndf1f3c70ugkd3
#   export IMAGE_TAG=latest
#   ./scripts/vm-restart-legal-ai.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lib/vm-common.sh
source "${ROOT}/scripts/lib/vm-common.sh"

IMAGE="${IMAGE:-cr.yandex/crpllsmk62iiorpelole/legal-ai:${IMAGE_TAG:-latest}}"
REMOTE_COMPOSE="${VM_REMOTE_DIR}/docker-compose.vm.yml"

vm_postgres_credentials "${ROOT}/.env"

echo "==> Ensure dirs on VM (uploads: mkdir only, never delete)"
UPLOADS_BEFORE="$(vm_uploads_file_count)"
echo "==> Uploads on disk before restart: ${UPLOADS_BEFORE} file(s)"
vm_ssh "mkdir -p '${VM_REMOTE_DIR}'"
vm_ensure_uploads_dir

echo "==> Upload docker-compose.vm.yml"
vm_upload_file "${ROOT}/docker-compose.vm.yml" "${REMOTE_COMPOSE}"

echo "==> Pull ${IMAGE}"
vm_ssh "sudo docker pull ${IMAGE}"

echo "==> Start stack (postgres + legal-ai)"
vm_ssh bash -s <<EOF
set -euo pipefail
cd '${VM_REMOTE_DIR}'
export POSTGRES_USER='${POSTGRES_USER}'
export POSTGRES_PASSWORD='${POSTGRES_PASSWORD}'
export LEGAL_AI_IMAGE='${IMAGE}'

# Stop legacy standalone container if present
sudo docker stop legal-ai 2>/dev/null || true
sudo docker rm legal-ai 2>/dev/null || true

sudo env POSTGRES_USER="\${POSTGRES_USER}" POSTGRES_PASSWORD="\${POSTGRES_PASSWORD}" \\
  LEGAL_AI_IMAGE="\${LEGAL_AI_IMAGE}" docker compose -f docker-compose.vm.yml up -d

sudo docker compose -f docker-compose.vm.yml ps
echo "==> Mounts (legal-ai):"
sudo docker inspect legal-ai --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{println}}{{end}}' 2>/dev/null || true

for i in \$(seq 1 12); do
  if curl -sf http://127.0.0.1:8000/api/health; then
    echo
    echo "health OK (:8000)"
    exit 0
  fi
  sleep 5
done
echo "WARN: health check timed out (app may still be warming up)" >&2
EOF

UPLOADS_AFTER="$(vm_uploads_file_count)"
vm_assert_uploads_preserved "${UPLOADS_BEFORE}" "${UPLOADS_AFTER}"
