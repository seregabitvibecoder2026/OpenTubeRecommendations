#!/usr/bin/env bash
# Fallback launcher for non-Nix systems (needs `uv`: https://docs.astral.sh/uv/).
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
if ! command -v uv >/dev/null 2>&1; then
  echo "Не найден uv. Установите: curl -LsSf https://astral.sh/uv/install.sh | sh  (или через пакетный менеджер)" >&2
  exit 1
fi
export UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-$PWD/.venv}"
EXTRAS=()
if [ -f data/extras.txt ]; then
  for e in $(cat data/extras.txt); do EXTRAS+=(--extra "$e"); done
fi
# offline first (works without internet once installed), then online
uv sync --frozen --offline "${EXTRAS[@]}" -q 2>/dev/null || uv sync --frozen "${EXTRAS[@]}"
exec "$UV_PROJECT_ENVIRONMENT/bin/python" -m app "$@"
