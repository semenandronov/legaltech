#!/usr/bin/env bash
# Production deploy: Mac buildx (linux/amd64) → Yandex CR → VM sync .env → restart.
# Uses registry layer cache for repeat deploys. Bakes VITE_* (incl. Google Drive) at build time.
#
#   ./scripts/vm-deploy.sh
#   ./scripts/vm-deploy.sh --no-build   # sync .env + restart only
#   ./scripts/deploy-prod.sh            # same default path
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"

# shellcheck source=lib/deploy-common.sh
source "${ROOT}/scripts/lib/deploy-common.sh"

VM_ID="${YC_VM_ID:-fv4qdpndf1f3c70ugkd3}"
REGISTRY_IMAGE="${REGISTRY_IMAGE:-cr.yandex/crpllsmk62iiorpelole/legal-ai}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
IMAGE="${REGISTRY_IMAGE}:${IMAGE_TAG}"
CACHE_REF="${REGISTRY_IMAGE}:buildcache"
NO_BUILD=false
SKIP_VERIFY=false

for arg in "$@"; do
  case "$arg" in
    --no-build) NO_BUILD=true ;;
    --skip-verify) SKIP_VERIFY=true ;;
    -h|--help)
      sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    --build-on-vm|--env-only)
      echo "Use ./scripts/deploy-prod.sh ${arg} instead" >&2
      exit 1
      ;;
    *)
      echo "Unknown arg: ${arg}" >&2
      exit 1
      ;;
  esac
done

export YC_VM_ID="${VM_ID}"
export IMAGE_TAG="${IMAGE_TAG}"
export IMAGE="${IMAGE}"
deploy_resolve_vm_public_url
export VM_PUBLIC_URL

if [[ "${NO_BUILD}" != "true" ]]; then
  deploy_prepare_vite_build_env "${ROOT}"
  deploy_load_google_build_args "${ROOT}"
  deploy_docker_login_registry

  echo "==> Docker build (linux/amd64) ${IMAGE}"
  echo "    Google client id length: ${#VITE_GOOGLE_CLIENT_ID}"
  export DOCKER_BUILDKIT=1

  # Prefer Docker Desktop builder (stable with registry cache). Avoid docker-container
  # builder when project path contains non-ASCII chars (buildx gRPC session error).
  BUILDER=""
  for candidate in desktop-linux default; do
    if docker buildx inspect "${candidate}" >/dev/null 2>&1; then
      BUILDER="${candidate}"
      break
    fi
  done

  if [[ -n "${BUILDER}" ]]; then
    echo "    buildx builder: ${BUILDER}, registry cache: ${CACHE_REF}"
    docker buildx build \
      --builder "${BUILDER}" \
      --platform linux/amd64 \
      --cache-from "type=registry,ref=${CACHE_REF}" \
      --cache-to "type=registry,ref=${CACHE_REF},mode=max" \
      --build-arg "VITE_GOOGLE_CLIENT_ID=${VITE_GOOGLE_CLIENT_ID}" \
      --build-arg "VITE_GOOGLE_API_KEY=${VITE_GOOGLE_API_KEY}" \
      -t "${IMAGE}" \
      --push \
      . || BUILDER=""
  fi

  if [[ -z "${BUILDER}" ]]; then
    echo "==> buildx unavailable or failed; using docker build + push"
    docker build \
      --platform linux/amd64 \
      --build-arg "VITE_GOOGLE_CLIENT_ID=${VITE_GOOGLE_CLIENT_ID}" \
      --build-arg "VITE_GOOGLE_API_KEY=${VITE_GOOGLE_API_KEY}" \
      -t "${IMAGE}" \
      .
    docker push "${IMAGE}"
  fi

  if [[ "${SKIP_VERIFY}" != "true" ]]; then
    deploy_verify_image_has_google_keys "${IMAGE}" || true
  fi
fi

chmod +x "${ROOT}/scripts/vm-sync-env.sh" "${ROOT}/scripts/vm-restart-legal-ai.sh"
"${ROOT}/scripts/vm-sync-env.sh"
"${ROOT}/scripts/vm-restart-legal-ai.sh"

deploy_post_health_check "${VM_PUBLIC_URL}" || true

echo "==> Deploy finished: ${IMAGE}"
echo "    URL: ${VM_PUBLIC_URL}"
echo "    Google Drive: upload on case overview / document upload modal"
