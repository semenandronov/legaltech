#!/usr/bin/env bash
# Скачать образ приложения на VM.
#   export YC_VM_ID=fv4qdpndf1f3c70ugkd3
#   export IMAGE_TAG=latest   # или legal-ai:20260518-1457-amd64
#   ./scripts/vm-pull-image.sh
set -euo pipefail

VM_ID="${YC_VM_ID:-fv4qdpndf1f3c70ugkd3}"
IMAGE="${IMAGE:-cr.yandex/crpllsmk62iiorpelole/legal-ai:${IMAGE_TAG:-latest}}"

echo "==> Pull $IMAGE on VM $VM_ID"
yc compute ssh --id "$VM_ID" -- "sudo docker pull $IMAGE && sudo docker images $(echo "$IMAGE" | cut -d: -f1) --format '{{.Repository}}:{{.Tag}} {{.Size}}'"
