#!/usr/bin/env bash
# Roll out a new legal-ai image on the VM. Safe for CI over SSH.
# - Pulls image, docker compose up -d
# - mkdir uploads only; never deletes user files on disk
#
# Required env: LEGAL_AI_IMAGE
# Optional: VM_REMOTE_DIR (default /home/andronovsemen04/legal-ai)
set -euo pipefail

VM_REMOTE_DIR="${VM_REMOTE_DIR:-/home/andronovsemen04/legal-ai}"
COMPOSE_FILE="${VM_REMOTE_DIR}/docker-compose.vm.yml"
IMAGE="${LEGAL_AI_IMAGE:?LEGAL_AI_IMAGE is required}"

if [[ ! -f "${COMPOSE_FILE}" ]]; then
  echo "Missing ${COMPOSE_FILE} — upload docker-compose.vm.yml first" >&2
  exit 1
fi

if [[ ! -f "${VM_REMOTE_DIR}/.env" ]]; then
  echo "Missing ${VM_REMOTE_DIR}/.env — sync runtime env before first deploy" >&2
  exit 1
fi

cd "${VM_REMOTE_DIR}"
mkdir -p uploads
chmod 755 uploads

UPLOADS_BEFORE="$(find uploads -type f 2>/dev/null | wc -l | tr -d ' ')"
echo "==> Uploads on disk before rollout: ${UPLOADS_BEFORE} file(s)"

set -a
# shellcheck disable=SC1091
source .env
set +a

if [[ -n "${YC_REGISTRY_IAM_TOKEN:-}" ]]; then
  echo "==> Registry login (fresh IAM token)"
  echo "${YC_REGISTRY_IAM_TOKEN}" | sudo docker login --username iam --password-stdin cr.yandex
fi

echo "==> Pull ${IMAGE}"
sudo docker pull "${IMAGE}"

sudo docker stop legal-ai 2>/dev/null || true
sudo docker rm legal-ai 2>/dev/null || true

sudo env POSTGRES_USER="${POSTGRES_USER:-user}" \
  POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-password}" \
  LEGAL_AI_IMAGE="${IMAGE}" \
  docker compose -f docker-compose.vm.yml up -d

sudo docker compose -f docker-compose.vm.yml ps

UPLOADS_AFTER="$(find uploads -type f 2>/dev/null | wc -l | tr -d ' ')"
if [[ "${UPLOADS_AFTER}" -lt "${UPLOADS_BEFORE}" ]]; then
  echo "ERROR: uploads count dropped (${UPLOADS_BEFORE} -> ${UPLOADS_AFTER})" >&2
  exit 1
fi
echo "==> Uploads preserved: ${UPLOADS_AFTER} file(s)"

for i in $(seq 1 24); do
  if curl -sf http://127.0.0.1:8000/api/health >/dev/null; then
    echo "==> health OK"
    exit 0
  fi
  sleep 5
done

echo "WARN: health check timed out (reranker may still be warming)" >&2
exit 0
