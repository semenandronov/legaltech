# Shared production deploy helpers (source from deploy scripts, do not execute directly).
# shellcheck shell=bash

deploy_common_root() {
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  cd "$(cd "${script_dir}/../.." && pwd)"
  pwd
}

deploy_resolve_vm_public_url() {
  if [[ -n "${VM_PUBLIC_URL:-}" ]]; then
    return 0
  fi
  if [[ -z "${YC_VM_ID:-}" ]]; then
    VM_PUBLIC_URL="${VM_PUBLIC_URL:-https://158.160.148.240}"
    export VM_PUBLIC_URL
    return 0
  fi
  local ip
  ip="$(yc compute instance get "${YC_VM_ID}" --format json | python3 -c \
    "import sys,json; d=json.load(sys.stdin); print(d['network_interfaces'][0]['primary_v4_address']['one_to_one_nat']['address'])")"
  VM_PUBLIC_URL="https://${ip}"
  export VM_PUBLIC_URL
}

# Writes ${ROOT}/.env.vite-build (Docker + Vite). Delegates to scripts/ci/prepare-vite-build-env.sh.
deploy_prepare_vite_build_env() {
  local root="${1:?root}"
  local env_file="${root}/.env"

  if [[ -f "${env_file}" ]]; then
    if [[ -z "${VITE_GOOGLE_CLIENT_ID:-}" ]]; then
      VITE_GOOGLE_CLIENT_ID="$(
        grep -E '^VITE_GOOGLE_CLIENT_ID=' "${env_file}" | head -1 | cut -d= -f2- | tr -d '\r' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//'
      )"
      export VITE_GOOGLE_CLIENT_ID
    fi
    if [[ -z "${VITE_GOOGLE_API_KEY:-}" ]]; then
      VITE_GOOGLE_API_KEY="$(
        grep -E '^VITE_GOOGLE_API_KEY=' "${env_file}" | head -1 | cut -d= -f2- | tr -d '\r' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//'
      )"
      export VITE_GOOGLE_API_KEY
    fi
  fi

  "${root}/scripts/ci/prepare-vite-build-env.sh"
}

deploy_load_google_build_args() {
  local root="${1:?root}"
  local snip="${root}/.env.vite-build"
  if [[ ! -f "${snip}" ]]; then
    deploy_prepare_vite_build_env "${root}" || return 1
  fi
  VITE_GOOGLE_CLIENT_ID="$(
    grep -E '^VITE_GOOGLE_CLIENT_ID=' "${snip}" | head -1 | cut -d= -f2- | tr -d '\r' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//'
  )"
  VITE_GOOGLE_API_KEY="$(
    grep -E '^VITE_GOOGLE_API_KEY=' "${snip}" | head -1 | cut -d= -f2- | tr -d '\r' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//'
  )"
  export VITE_GOOGLE_CLIENT_ID VITE_GOOGLE_API_KEY
  if [[ -z "${VITE_GOOGLE_CLIENT_ID}" || -z "${VITE_GOOGLE_API_KEY}" ]]; then
    echo "Missing VITE_GOOGLE_* in ${snip}" >&2
    return 1
  fi
  return 0
}

deploy_docker_login_registry() {
  if ! command -v yc >/dev/null 2>&1; then
    echo "yc CLI not found" >&2
    return 1
  fi
  # Mac with `yc container registry configure-docker` uses cred helper; plain login fails.
  if [[ -f "${HOME}/.docker/config.json" ]] && python3 -c "
import json, sys
p = '${HOME}/.docker/config.json'
c = json.load(open(p))
sys.exit(0 if c.get('credHelpers', {}).get('cr.yandex') else 1)
" 2>/dev/null; then
    echo "==> Docker: using yc credential helper for cr.yandex"
    return 0
  fi
  local token
  token="$(yc iam create-token)"
  if echo "${token}" | docker login --username iam --password-stdin cr.yandex 2>/dev/null; then
    return 0
  fi
  echo "==> Docker login (isolated config; yc credential helper bypass)"
  DEPLOY_DOCKER_CONFIG="${DEPLOY_DOCKER_CONFIG:-$(mktemp -d)}"
  export DOCKER_CONFIG="${DEPLOY_DOCKER_CONFIG}"
  mkdir -p "${DOCKER_CONFIG}"
  printf '%s\n' '{}' > "${DOCKER_CONFIG}/config.json"
  echo "${token}" | docker login --username iam --password-stdin cr.yandex
}

deploy_verify_image_has_google_keys() {
  local image="${1:?image}"
  if docker run --rm --entrypoint sh "${image}" -c \
    'grep -rq "googleusercontent" /app/frontend/dist 2>/dev/null'; then
    echo "==> Verify: Google OAuth client id present in frontend bundle"
    return 0
  fi
  echo "WARN: googleusercontent not found in ${image} frontend dist — Google Drive button will be hidden" >&2
  return 1
}

deploy_post_health_check() {
  local url="${1:?url}"
  local i
  for i in 1 2 3 4 5 6 7 8 9 10 11 12; do
    if curl -sfk "${url}/api/health" >/dev/null 2>&1; then
      echo "==> Health OK: ${url}/api/health"
      return 0
    fi
    sleep 5
  done
  echo "WARN: health check timed out (app may still be warming reranker ~2-3 min)" >&2
  return 1
}
