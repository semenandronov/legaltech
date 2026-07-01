#!/usr/bin/env bash
# Fallback production deploy: sources on VM → docker build → push CR → sync .env → restart.
# Use when Mac → CR push is too slow. Keeps Docker layer cache (no prune by default).
#
#   ./scripts/deploy-prod.sh --build-on-vm
#   VM_DOCKER_PRUNE=1 ./scripts/deploy-prod.sh --build-on-vm   # disk cleanup only
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"

# shellcheck source=lib/deploy-common.sh
source "${ROOT}/scripts/lib/deploy-common.sh"

VM_ID="${YC_VM_ID:-fv4jkhc0aojn5r870h3h}"
REGISTRY_IMAGE="${REGISTRY_IMAGE:-cr.yandex/crpllsmk62iiorpelole/legal-ai}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
IMAGE="${REGISTRY_IMAGE}:${IMAGE_TAG}"
REMOTE_BUILD_DIR="${REMOTE_BUILD_DIR:-/home/andronovsemen04/legal-ai-build}"

deploy_resolve_vm_public_url
export VM_PUBLIC_URL

deploy_prepare_vite_build_env "${ROOT}"
deploy_load_google_build_args "${ROOT}"

ARCHIVE="$(mktemp /tmp/legal-ai-src.XXXXXX.tgz)"
trap 'rm -f "${ARCHIVE}"' EXIT

echo "==> Pack sources (dockerignore-style excludes)"
tar -czf "${ARCHIVE}" \
  --exclude='.git' \
  --exclude='frontend/node_modules' \
  --exclude='frontend/dist' \
  --exclude='backend/uploads' \
  --exclude='backend/.venv' \
  --exclude='backend/legal-corpus-jobs' \
  --exclude='backend/__pycache__' \
  --exclude='backend/.pytest_cache' \
  -C "${ROOT}" \
  Dockerfile .dockerignore .env.vite-build backend frontend

ARCHIVE_MB="$(du -m "${ARCHIVE}" | cut -f1)"
echo "==> Archive ${ARCHIVE_MB}MB → VM:${REMOTE_BUILD_DIR}"

yc compute ssh --id "${VM_ID}" -- "mkdir -p '${REMOTE_BUILD_DIR}'"

echo "==> Upload sources (may take a few minutes)..."
cat "${ARCHIVE}" | yc compute ssh --id "${VM_ID}" -- "cat > '${REMOTE_BUILD_DIR}/src.tgz' && tar -xzf '${REMOTE_BUILD_DIR}/src.tgz' -C '${REMOTE_BUILD_DIR}' && rm -f '${REMOTE_BUILD_DIR}/src.tgz'"

TOKEN="$(yc iam create-token)"
echo "==> Docker login on VM"
yc compute ssh --id "${VM_ID}" -- bash -s <<EOF
set -euo pipefail
echo '${TOKEN}' | sudo docker login --username iam --password-stdin cr.yandex
if [[ "${VM_DOCKER_PRUNE:-}" == "1" ]]; then
  echo "==> Pruning build cache (VM_DOCKER_PRUNE=1)"
  sudo docker builder prune -af 2>/dev/null || true
fi
df -h /
EOF

echo "==> docker build on VM: ${IMAGE}"
yc compute ssh --id "${VM_ID}" -- bash -s <<EOF
set -euo pipefail
cd '${REMOTE_BUILD_DIR}'
test -f .env.vite-build && grep -q VITE_GOOGLE_CLIENT_ID .env.vite-build
sudo docker build \
  --build-arg VITE_GOOGLE_CLIENT_ID='${VITE_GOOGLE_CLIENT_ID}' \
  --build-arg VITE_GOOGLE_API_KEY='${VITE_GOOGLE_API_KEY}' \
  -t '${IMAGE}' .
sudo docker push '${IMAGE}'
sudo docker images '${REGISTRY_IMAGE}' --format '{{.ID}} {{.Size}}' | head -1
EOF

chmod +x "${ROOT}/scripts/vm-sync-env.sh" "${ROOT}/scripts/vm-restart-legal-ai.sh"
"${ROOT}/scripts/vm-sync-env.sh"
"${ROOT}/scripts/vm-restart-legal-ai.sh"

deploy_post_health_check "${VM_PUBLIC_URL}" || true

echo "==> Deploy (build on VM) finished: ${IMAGE}"
echo "    URL: ${VM_PUBLIC_URL}"
