#!/usr/bin/env bash
# HTTPS для legal-ai на Yandex VM (Caddy).
# Решает crypto.randomUUID и другие Web Crypto API на проде — нужен secure context (HTTPS).
#
# С доменом (Let's Encrypt):
#   export VM_DOMAIN=app.example.com
#   export VM_ACME_EMAIL=you@example.com   # опционально
#   ./scripts/vm-setup-https.sh
#
# Только IP (самоподписанный сертификат, браузер покажет предупреждение один раз):
#   export YC_VM_ID=fv4qdpndf1f3c70ugkd3
#   ./scripts/vm-setup-https.sh
#
# После установки открывайте: https://<VM_DOMAIN или IP>
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"

VM_ID="${YC_VM_ID:-fv4qdpndf1f3c70ugkd3}"
VM_DOMAIN="${VM_DOMAIN:-}"
VM_ACME_EMAIL="${VM_ACME_EMAIL:-}"
REMOTE_CADDY_DIR="${REMOTE_CADDY_DIR:-/home/andronovsemen04/legal-ai/caddy}"

if [[ -z "${VM_DOMAIN}" ]]; then
  VM_DOMAIN="$(yc compute instance get "${VM_ID}" --format json 2>/dev/null | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('network_interfaces', [{}])[0].get('primary_v4_address', {}).get('one_to_one_nat', {}).get('address', '') or '')
" 2>/dev/null || true)"
fi

if [[ -z "${VM_DOMAIN}" ]]; then
  echo "Set VM_DOMAIN or ensure yc can read VM public IP." >&2
  exit 1
fi

# IP → self-signed; hostname → Let's Encrypt
if [[ "${VM_DOMAIN}" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  TLS_DIRECTIVE="tls internal"
  SITE_URL="https://${VM_DOMAIN}"
  echo "==> Site: ${SITE_URL} (self-signed certificate for IP)"
  echo "    Browser will warn once — accept to continue. For production use a domain + VM_DOMAIN."
else
  TLS_DIRECTIVE=""
  SITE_URL="https://${VM_DOMAIN}"
  echo "==> Site: ${SITE_URL} (Let's Encrypt)"
fi

TMP_CADDY="$(mktemp)"
trap 'rm -f "${TMP_CADDY}"' EXIT
{
  if [[ -n "${VM_ACME_EMAIL}" ]]; then
    echo "{"
    echo "	email ${VM_ACME_EMAIL}"
    echo "}"
    echo ""
  fi
  if [[ -n "${TLS_DIRECTIVE}" ]]; then
    # IP without domain: openssl cert with IP SAN (browsers need secure context)
    echo ":443 {"
    echo "	tls /etc/caddy/certs/cert.pem /etc/caddy/certs/key.pem"
    echo ""
    echo "	reverse_proxy 127.0.0.1:8000"
    echo ""
    echo "	encode gzip"
    echo ""
    echo "	header {"
    echo "		Strict-Transport-Security \"max-age=31536000; includeSubDomains\""
    echo "	}"
    echo "}"
    echo ""
    echo ":80 {"
    echo "	redir https://{host}{uri} permanent"
    echo "}"
  else
    echo "${VM_DOMAIN} {"
    echo ""
    echo "	reverse_proxy 127.0.0.1:8000"
    echo ""
    echo "	encode gzip"
    echo ""
    echo "	header {"
    echo "		Strict-Transport-Security \"max-age=31536000; includeSubDomains\""
    echo "	}"
    echo "}"
  fi
} > "${TMP_CADDY}"

echo "==> Rebind legal-ai to 127.0.0.1:8000 (free :80/:443 for Caddy)"
chmod +x scripts/vm-restart-legal-ai.sh
./scripts/vm-restart-legal-ai.sh

echo "==> Upload Caddyfile to VM"
yc compute ssh --id "${VM_ID}" -- "mkdir -p '${REMOTE_CADDY_DIR}'"
yc compute ssh --id "${VM_ID}" -- "cat > '${REMOTE_CADDY_DIR}/Caddyfile'" < "${TMP_CADDY}"

echo "==> Install Caddy and configure systemd (if needed)"
yc compute ssh --id "${VM_ID}" -- bash -s <<'REMOTE'
set -euo pipefail
if ! command -v caddy >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https curl
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
  sudo apt-get update -qq
  sudo apt-get install -y -qq caddy
fi
caddy version
REMOTE

echo "==> Point systemd caddy at our Caddyfile"
yc compute ssh --id "${VM_ID}" -- bash -s <<REMOTE
set -euo pipefail
CADDY_DIR='${REMOTE_CADDY_DIR}'
VM_IP='${VM_DOMAIN}'
sudo mkdir -p /etc/caddy /etc/caddy/certs
if [[ "${VM_DOMAIN}" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  if [[ ! -f /etc/caddy/certs/cert.pem ]]; then
    sudo openssl req -x509 -nodes -days 825 -newkey rsa:2048 \
      -keyout /etc/caddy/certs/key.pem -out /etc/caddy/certs/cert.pem \
      -subj "/CN=legal-ai" \
      -addext "subjectAltName=IP:\${VM_IP},DNS:localhost"
    sudo chown -R caddy:caddy /etc/caddy/certs
    sudo chmod 600 /etc/caddy/certs/key.pem
    sudo chmod 644 /etc/caddy/certs/cert.pem
  fi
fi
sudo cp "\${CADDY_DIR}/Caddyfile" /etc/caddy/Caddyfile
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl enable caddy
sudo systemctl restart caddy
sleep 2
sudo systemctl is-active caddy
curl -sk https://127.0.0.1/api/health || true
REMOTE

echo "==> Sync .env (HTTPS CORS)"
export VM_PUBLIC_URL="${SITE_URL}"
chmod +x scripts/vm-sync-env.sh
VM_PUBLIC_URL="${SITE_URL}" ./scripts/vm-sync-env.sh

echo ""
echo "==> HTTPS ready: ${SITE_URL}"
echo "    CORS updated in .env. Use this URL in the browser (not http://)."
