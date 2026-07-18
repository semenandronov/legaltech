# Shared Yandex VM helpers (source only).
# shellcheck shell=bash

vm_common_root() {
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  cd "$(cd "${script_dir}/../.." && pwd)"
  pwd
}

export YC_VM_ID="${YC_VM_ID:-fv4jkhc0aojn5r870h3h}"
export VM_SSH_IDENTITY="${VM_SSH_IDENTITY:-${HOME}/.ssh/yc_rsa_new}"
export VM_SSH_LOGIN="${VM_SSH_LOGIN:-andronovsemen04}"
export VM_REMOTE_DIR="${VM_REMOTE_DIR:-/home/andronovsemen04/legal-ai}"
export VM_POSTGRES_CONTAINER="${VM_POSTGRES_CONTAINER:-legal-ai-postgres}"
export VM_PG_IMAGE="${VM_PG_IMAGE:-pgvector/pgvector:pg16}"
export LOCAL_PG_CONTAINER="${LOCAL_PG_CONTAINER:-legal-ai-vault-db}"

vm_read_env_var() {
  local file="$1"
  local key="$2"
  local default="${3:-}"
  if [[ ! -f "$file" ]]; then
    echo "$default"
    return 0
  fi
  python3 - "$file" "$key" "$default" <<'PY'
import re, sys
from pathlib import Path
path, key, default = sys.argv[1:4]
text = Path(path).read_text(encoding="utf-8")
m = re.search(rf'^{re.escape(key)}\s*=\s*["\']?([^"\'#\n]+)', text, re.M)
print(m.group(1).strip() if m else default)
PY
}

vm_postgres_credentials() {
  local env_file="${1:-$(vm_common_root)/.env}"
  POSTGRES_USER="$(vm_read_env_var "$env_file" POSTGRES_USER user)"
  POSTGRES_PASSWORD="$(vm_read_env_var "$env_file" POSTGRES_PASSWORD password)"
  export POSTGRES_USER POSTGRES_PASSWORD
}

vm_internal_database_url() {
  vm_postgres_credentials "${1:-}"
  echo "postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/legal_ai?sslmode=disable"
}

vm_ssh() {
  local ssh_args=()
  if [[ -f "${VM_SSH_IDENTITY}" ]]; then
    ssh_args+=(--identity-file "${VM_SSH_IDENTITY}")
  fi
  if [[ -n "${VM_SSH_LOGIN:-}" ]]; then
    ssh_args+=(--login "${VM_SSH_LOGIN}")
  fi
  yc compute ssh --id "${YC_VM_ID}" "${ssh_args[@]}" -- "$@"
}

vm_upload_file() {
  local local_path="$1"
  local remote_path="$2"
  vm_ssh "mkdir -p '$(dirname "$remote_path")'"
  vm_ssh "cat > '${remote_path}'" < "${local_path}"
}

vm_upload_text() {
  local remote_path="$1"
  shift
  vm_ssh "mkdir -p '$(dirname "$remote_path")'"
  vm_ssh "cat > '${remote_path}'" <<<"$*"
}

# Считает файлы в uploads на VM (рекурсивно). Диск не изменяет.
vm_uploads_file_count() {
  vm_ssh "find '${VM_REMOTE_DIR}/uploads' -type f 2>/dev/null | wc -l | tr -d ' '"
}

# mkdir -p только; никогда не удаляет существующие файлы дел.
vm_ensure_uploads_dir() {
  vm_ssh "mkdir -p '${VM_REMOTE_DIR}/uploads' && chmod 755 '${VM_REMOTE_DIR}/uploads'"
}

# Проверка: после рестарта файлов на диске не стало меньше.
vm_assert_uploads_preserved() {
  local before="$1"
  local after="$2"
  if [[ -z "${before}" || -z "${after}" ]]; then
    return 0
  fi
  if [[ "${after}" -lt "${before}" ]]; then
    echo "ERROR: uploads file count dropped (${before} -> ${after}). Abort." >&2
    exit 1
  fi
  echo "==> Uploads preserved on VM disk: ${after} file(s) (was ${before})"
}
