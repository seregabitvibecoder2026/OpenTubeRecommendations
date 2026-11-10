#!/usr/bin/env bash
# Launcher for non-Nix systems (needs `uv`: https://docs.astral.sh/uv/). On NixOS use ./start (it enters the Nix shell).
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

if [ -z "${IN_NIX_SHELL:-}" ] && { [ -e /etc/NIXOS ] || grep -qi '^ID=nixos' /etc/os-release 2>/dev/null; }; then
  echo "Вы на NixOS вне dev-shell: Python от uv и готовые wheels здесь не запускаются
(ошибка «Could not start dynamically linked executable»). Запускайте через ./start —
он сам заходит в нужное окружение Nix. Если Nix не отвечает, ./start подскажет, что проверить." >&2
  exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "Не найден uv. Установите: curl -LsSf https://astral.sh/uv/install.sh | sh  (или через пакетный менеджер)" >&2
  exit 1
fi
export UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-$PWD/.venv}"

# A leftover .venv whose Python cannot start (made by another machine or a failed run) is recreated.
if [ "$UV_PROJECT_ENVIRONMENT" = "$PWD/.venv" ] && [ -e .venv ] && ! .venv/bin/python -c 'import sys' >/dev/null 2>&1; then
  echo "Окружение .venv сломано, пересоздаю." >&2
  rm -rf .venv
fi

EXTRAS=()
if [ -f data/extras.txt ]; then
  for e in $(cat data/extras.txt); do EXTRAS+=(--extra "$e"); done
fi
# offline first (works without internet once installed), then online
uv sync --frozen --offline "${EXTRAS[@]}" -q 2>/dev/null || uv sync --frozen "${EXTRAS[@]}"
exec "$UV_PROJECT_ENVIRONMENT/bin/python" -m app "$@"
