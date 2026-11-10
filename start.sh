#!/usr/bin/env bash
# Launcher without Nix: installs uv if missing, uv fetches Python 3.12 and the dependencies, then runs the app.
# (On NixOS use ./start: it enters the Nix shell. With nix-ld enabled this script works there too.)
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

is_nixos() { [ -e /etc/NIXOS ] || grep -qi '^ID=nixos' /etc/os-release 2>/dev/null; }

if [ -z "${IN_NIX_SHELL:-}" ] && [ -z "${NIX_LD:-}" ] && is_nixos; then
  echo "Вы на NixOS вне dev-shell: Python от uv и готовые wheels здесь не запускаются
(ошибка «Could not start dynamically linked executable»). Запускайте через ./start —
он сам заходит в нужное окружение Nix. Или включите в конфигурации NixOS programs.nix-ld.enable = true;" >&2
  exit 1
fi

ensure_uv() {
  command -v uv >/dev/null 2>&1 && return 0
  if [ -x "$HOME/.local/bin/uv" ]; then export PATH="$HOME/.local/bin:$PATH"; return 0; fi
  echo "Для запуска нужен uv (менеджер Python, ~30 МБ, официальный установщик с astral.sh)." >&2
  if [ -t 0 ]; then
    read -r -p "Установить в ~/.local/bin? [Y/n] " ans
    case "${ans:-Y}" in
      [Nn]*) echo "Установите uv сами (https://docs.astral.sh/uv/) и запустите ./start ещё раз." >&2; exit 1 ;;
    esac
  fi
  if command -v curl >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | UV_NO_MODIFY_PATH=1 sh >&2
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- https://astral.sh/uv/install.sh | UV_NO_MODIFY_PATH=1 sh >&2
  else
    echo "Нужен curl или wget, чтобы скачать uv. Установите один из них или сам uv." >&2
    exit 1
  fi
  export PATH="$HOME/.local/bin:$PATH"
  command -v uv >/dev/null 2>&1 || { echo "Не удалось установить uv: https://docs.astral.sh/uv/" >&2; exit 1; }
}
ensure_uv

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
if ! uv sync --frozen --offline "${EXTRAS[@]}" -q 2>/dev/null; then
  echo "Первый запуск: скачиваются Python и зависимости (~150 МБ), это один раз." >&2
  uv sync --frozen "${EXTRAS[@]}" || {
    echo "Не удалось установить зависимости. Нужен интернет: github.com (Python), pypi.org и files.pythonhosted.org." >&2
    echo "За файрволом/прокси задайте HTTPS_PROXY или откройте эти адреса." >&2
    exit 1
  }
fi
exec "$UV_PROJECT_ENVIRONMENT/bin/python" -m app "$@"
