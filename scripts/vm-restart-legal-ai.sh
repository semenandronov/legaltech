#!/usr/bin/env bash
# Перезапуск legal-ai на VM после pull/build образа.
# Оригиналы дел хранятся на диске ВМ (volume), не в контейнере.
#
#   export YC_VM_ID=fv4qdpndf1f3c70ugkd3
#   export IMAGE_TAG=latest
#   ./scripts/vm-restart-legal-ai.sh
set -euo pipefail

VM_ID="${YC_VM_ID:-fv4qdpndf1f3c70ugkd3}"
IMAGE="${IMAGE:-cr.yandex/crpllsmk62iiorpelole/legal-ai:${IMAGE_TAG:-latest}}"
ENV_FILE="${ENV_FILE:-/home/andronovsemen04/legal-ai/.env}"
# Постоянная папка на ВМ (создайте один раз: mkdir -p … && chmod 755 …)
UPLOADS_HOST_DIR="${UPLOADS_HOST_DIR:-/home/andronovsemen04/legal-ai/uploads}"
# Путь внутри контейнера (WORKDIR CMD = /app/backend, см. Dockerfile)
UPLOADS_CONTAINER_DIR="${UPLOADS_CONTAINER_DIR:-/app/backend/uploads}"

echo "==> Ensure uploads dir on VM: ${UPLOADS_HOST_DIR}"
yc compute ssh --id "$VM_ID" -- "mkdir -p '${UPLOADS_HOST_DIR}' && chmod 755 '${UPLOADS_HOST_DIR}'"

echo "==> Pull $IMAGE"
yc compute ssh --id "$VM_ID" -- "sudo docker pull $IMAGE"

echo "==> Restart container legal-ai (volume: ${UPLOADS_HOST_DIR} -> ${UPLOADS_CONTAINER_DIR})"
yc compute ssh --id "$VM_ID" -- bash -s <<EOF
set -euo pipefail
sudo docker stop legal-ai 2>/dev/null || true
sudo docker rm legal-ai 2>/dev/null || true
# Only localhost — Caddy terminates TLS on :443 and redirects :80 (see vm-setup-https.sh).
# For HTTP-only debug: export VM_EXPOSE_HTTP_PORTS=1
EXTRA_PORTS=""
if [[ "${VM_EXPOSE_HTTP_PORTS:-}" == "1" ]]; then
  EXTRA_PORTS="-p 80:8000 -p 8000:8000"
else
  EXTRA_PORTS="-p 127.0.0.1:8000:8000"
fi
sudo docker run -d --name legal-ai --restart unless-stopped \\
  \${EXTRA_PORTS} \\
  -v ${UPLOADS_HOST_DIR}:${UPLOADS_CONTAINER_DIR} \\
  --env-file ${ENV_FILE} \\
  ${IMAGE}
sudo docker ps --filter name=legal-ai
echo "==> Mounts:"
sudo docker inspect legal-ai --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{println}}{{end}}'
for i in 1 2 3 4 5 6 7 8 9 10 11 12; do
  if curl -sf http://127.0.0.1:8000/api/health; then echo; echo "health OK (:8000)"; break; fi
  sleep 5
done
if [[ "${VM_EXPOSE_HTTP_PORTS:-}" == "1" ]]; then
  curl -sf http://127.0.0.1/api/health && echo "health OK (:80)" || echo "health :80 — wait for warmup"
fi
EOF
