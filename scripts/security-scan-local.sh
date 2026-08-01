#!/usr/bin/env bash
# Local Shift-Left security pass (mirrors CI intent).
# Usage: ./scripts/security-scan-local.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> SCA: pip-audit (backend/requirements-core.txt)"
python3 -m pip install -q --user "pip-audit==2.9.0" || true
if python3 -m pip_audit --version >/dev/null 2>&1; then
  python3 -m pip_audit --requirement backend/requirements-core.txt --progress-spinner off --desc on || {
    echo "pip-audit found issues (inventory). CI uploads reports; Dependabot opens fix PRs."
  }
else
  echo "pip-audit not available locally; CI job will run it."
fi

echo "==> SCA: npm audit high+ (frontend production tree)"
(
  cd frontend
  if [ ! -d node_modules ]; then
    npm ci --legacy-peer-deps
  fi
  npm audit --audit-level=high --omit=dev || {
    echo "npm audit found high/critical issues. Prefer non-breaking 'npm audit fix', then Dependabot."
  }
)

echo "==> SAST: Semgrep ERROR severity"
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  docker run --rm -v "$ROOT:/src" -w /src semgrep/semgrep \
    semgrep scan \
      --config p/default \
      --config p/python \
      --config p/javascript \
      --config p/typescript \
      --severity ERROR \
      --metrics=off \
      --error \
      backend/app \
      frontend/src
elif python3 -m pip show semgrep >/dev/null 2>&1; then
  semgrep scan \
    --config p/default \
    --config p/python \
    --config p/javascript \
    --config p/typescript \
    --severity ERROR \
    --metrics=off \
    --error \
    backend/app \
    frontend/src
else
  echo "Semgrep skipped (start Docker Desktop or: pip install semgrep)."
fi

echo "==> Done."
echo "DAST: GitHub → Actions → DAST ZAP → Run workflow with staging HTTPS URL"
echo "      (or set repository variable ZAP_TARGET_URL for Monday cron)."
