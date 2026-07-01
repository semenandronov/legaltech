#!/usr/bin/env bash
# Postgres on Yandex VM (pgvector, Docker Compose).
#
#   ./scripts/vm-postgres.sh setup    — upload compose, start postgres only
#   ./scripts/vm-postgres.sh status   — container + pg_isready
#   ./scripts/vm-postgres.sh start    — start postgres (idempotent)
#   ./scripts/vm-postgres.sh stop     — stop postgres (keeps volume)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lib/vm-common.sh
source "${ROOT}/scripts/lib/vm-common.sh"

REMOTE_COMPOSE="${VM_REMOTE_DIR}/docker-compose.vm.yml"
COMPOSE_LOCAL="${ROOT}/docker-compose.vm.yml"

vm_upload_compose() {
  vm_ssh "mkdir -p '${VM_REMOTE_DIR}' '${VM_REMOTE_DIR}/uploads' && chmod 755 '${VM_REMOTE_DIR}/uploads'"
  echo "==> Upload docker-compose.vm.yml"
  vm_upload_file "${COMPOSE_LOCAL}" "${REMOTE_COMPOSE}"
}

vm_compose_postgres() {
  local action="$1"
  vm_postgres_credentials "${ROOT}/.env"
  vm_ssh bash -s <<EOF
set -euo pipefail
cd '${VM_REMOTE_DIR}'
export POSTGRES_USER='${POSTGRES_USER}'
export POSTGRES_PASSWORD='${POSTGRES_PASSWORD}'
export LEGAL_AI_IMAGE='cr.yandex/crpllsmk62iiorpelole/legal-ai:latest'
case '${action}' in
  up) sudo env POSTGRES_USER="\${POSTGRES_USER}" POSTGRES_PASSWORD="\${POSTGRES_PASSWORD}" \\
    LEGAL_AI_IMAGE="\${LEGAL_AI_IMAGE}" docker compose -f docker-compose.vm.yml up -d postgres ;;
  stop) sudo docker compose -f docker-compose.vm.yml stop postgres ;;
  *) echo "unknown action: ${action}" >&2; exit 1 ;;
esac
EOF
}

cmd_setup() {
  vm_upload_compose
  echo "==> Start Postgres on VM"
  vm_compose_postgres up
  echo "==> Postgres setup complete"
  cmd_status
}

cmd_start() {
  vm_upload_compose
  vm_compose_postgres up
  cmd_status
}

cmd_stop() {
  vm_compose_postgres stop
}

cmd_status() {
  vm_ssh bash -s <<'EOF'
set -euo pipefail
if sudo docker ps --format '{{.Names}}' | grep -qx legal-ai-postgres; then
  echo "Postgres container: running"
  sudo docker exec legal-ai-postgres pg_isready -U user -d legal_ai && echo "pg_isready: OK"
else
  echo "Postgres container: not running"
fi
sudo docker volume ls | grep legal_ai_pgdata || true
EOF
}

case "${1:-}" in
  setup) cmd_setup ;;
  start) cmd_start ;;
  stop) cmd_stop ;;
  status) cmd_status ;;
  *)
    echo "Usage: $0 {setup|start|stop|status}" >&2
    exit 1
    ;;
esac
