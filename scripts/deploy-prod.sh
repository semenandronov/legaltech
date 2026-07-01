#!/usr/bin/env bash
# Production deploy to Yandex VM (legal-ai).
#
# Recommended: push to main → GitHub Actions (.github/workflows/deploy-prod.yml)
#   builds image, pushes to Yandex CR, rolls out on VM (uploads/ on disk untouched).
#
# Manual fallback — build linux/amd64 on Mac → push to CR → sync .env → restart:
#   ./scripts/deploy-prod.sh
#
# Fallback (slow first time, good if Mac push is unreliable): build on VM.
#   ./scripts/deploy-prod.sh --build-on-vm
#
# Runtime-only (no image rebuild; does NOT update VITE_/Google in UI):
#   ./scripts/deploy-prod.sh --env-only
#
# Environment:
#   YC_VM_ID, VM_PUBLIC_URL, REGISTRY_IMAGE, IMAGE_TAG
#   VM_DOCKER_PRUNE=1  — only for vm build path when disk is full
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"

# shellcheck source=lib/deploy-common.sh
source "${ROOT}/scripts/lib/deploy-common.sh"

BUILD_ON_VM=false
ENV_ONLY=false

for arg in "$@"; do
  case "$arg" in
    --build-on-vm) BUILD_ON_VM=true ;;
    --env-only) ENV_ONLY=true ;;
    -h|--help)
      sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "Unknown argument: ${arg}" >&2
      exit 1
      ;;
  esac
done

export YC_VM_ID="${YC_VM_ID:-fv4jkhc0aojn5r870h3h}"
deploy_resolve_vm_public_url
export VM_PUBLIC_URL

if [[ "${ENV_ONLY}" == "true" ]]; then
  exec "${ROOT}/scripts/vm-sync-env.sh"
fi

if [[ "${BUILD_ON_VM}" == "true" ]]; then
  exec "${ROOT}/scripts/vm-deploy-build-on-vm.sh"
fi

exec "${ROOT}/scripts/vm-deploy.sh" "$@"
