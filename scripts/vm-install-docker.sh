#!/usr/bin/env bash
# Установка Docker на Ubuntu VM (Yandex Compute Cloud) и вход в Container Registry.
# Запуск с Mac (нужны yc CLI и OS Login):
#   export YC_VM_ID=fv4qdpndf1f3c70ugkd3   # или имя ВМ
#   ./scripts/vm-install-docker.sh
set -euo pipefail

VM_ID="${YC_VM_ID:-fv4qdpndf1f3c70ugkd3}"
REGISTRY="cr.yandex"

echo "==> VM: $VM_ID"
echo "==> Проверка SSH..."
yc compute ssh --id "$VM_ID" -- "uname -a"

echo "==> Установка Docker (если ещё нет)..."
yc compute ssh --id "$VM_ID" -- 'set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
if command -v docker >/dev/null 2>&1; then
  docker --version
  docker compose version
  exit 0
fi
curl -fsSL https://get.docker.com | sudo sh
sudo systemctl enable docker
sudo systemctl start docker
sudo usermod -aG docker "$USER"
docker --version
docker compose version
'

echo "==> Вход в Container Registry (IAM token с Mac)..."
TOKEN="$(yc iam create-token)"
yc compute ssh --id "$VM_ID" -- "echo '$TOKEN' | sudo docker login --username iam --password-stdin $REGISTRY"

echo "==> Копия credentials для пользователя OS Login (docker без sudo после перелогина)..."
yc compute ssh --id "$VM_ID" -- 'set -euo pipefail
U="$USER"
sudo mkdir -p "/home/$U/.docker"
sudo cp /root/.docker/config.json "/home/$U/.docker/config.json"
sudo chown -R "$U:$U" "/home/$U/.docker"
'

echo "Готово. Проверка: yc compute ssh --id $VM_ID -- \"sudo docker ps\""
