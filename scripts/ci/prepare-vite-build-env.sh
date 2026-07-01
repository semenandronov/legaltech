#!/usr/bin/env bash
# Build .env.vite-build for production Docker/CI (Vite envDir = /app).
#
# CI: set VITE_GOOGLE_CLIENT_ID and VITE_GOOGLE_API_KEY (GitHub Secrets).
# Local: same vars, or rely on grep from root .env when vars unset.
#
#   ./scripts/ci/prepare-vite-build-env.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SNIP="${ROOT}/.env.vite-build"
VM_UI="${ROOT}/.env.vm-ui"
LOCAL_ENV="${ROOT}/.env"

merge_snip() {
  python3 - "${SNIP}" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
merged: dict[str, str] = {}
prefix: list[str] = []
for line in path.read_text(encoding="utf-8").splitlines():
    stripped = line.strip()
    if stripped.startswith("VITE_") and "=" in stripped:
        merged[stripped.split("=", 1)[0]] = line
    else:
        prefix.append(line)
path.write_text("\n".join(prefix + list(merged.values())).rstrip() + "\n", encoding="utf-8")
PY
}

: >"${SNIP}"

if [[ -f "${LOCAL_ENV}" ]] && [[ -z "${VITE_GOOGLE_CLIENT_ID:-}" || -z "${VITE_GOOGLE_API_KEY:-}" ]]; then
  grep -E '^VITE_' "${LOCAL_ENV}" | sed 's/\r$//' >>"${SNIP}" || true
fi

if [[ -f "${VM_UI}" ]]; then
  echo "" >>"${SNIP}"
  echo "# VM production UI surface (from .env.vm-ui)" >>"${SNIP}"
  grep -E '^VITE_' "${VM_UI}" | sed 's/\r$//' >>"${SNIP}" || true
fi

if [[ -n "${VITE_GOOGLE_CLIENT_ID:-}" ]]; then
  echo "VITE_GOOGLE_CLIENT_ID=${VITE_GOOGLE_CLIENT_ID}" >>"${SNIP}"
fi
if [[ -n "${VITE_GOOGLE_API_KEY:-}" ]]; then
  echo "VITE_GOOGLE_API_KEY=${VITE_GOOGLE_API_KEY}" >>"${SNIP}"
fi

merge_snip

# Production SPA: same-origin /api (no dev VITE_API_URL).
sed -i.bak '/^VITE_API_URL=/d' "${SNIP}" 2>/dev/null || sed -i '' '/^VITE_API_URL=/d' "${SNIP}" || true
rm -f "${SNIP}.bak"
echo "# VITE_API_URL omitted — browser uses relative /api paths" >>"${SNIP}"

if ! grep -qE '^VITE_GOOGLE_CLIENT_ID=.+' "${SNIP}" \
  || ! grep -qE '^VITE_GOOGLE_API_KEY=.+' "${SNIP}"; then
  echo "Missing VITE_GOOGLE_CLIENT_ID / VITE_GOOGLE_API_KEY (env or ${LOCAL_ENV})" >&2
  exit 1
fi

echo "==> Wrote ${SNIP} ($(grep -cE '^VITE_' "${SNIP}" || echo 0) VITE_* keys)"
