#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
PYCACHE_PREFIX="${PYTHONPYCACHEPREFIX:-/private/tmp/codex-pyc}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "ERROR: не найден исполняемый Python в .venv/bin/python" >&2
  echo "Сначала создай окружение и установи зависимости." >&2
  exit 1
fi

echo "== Aventura predeploy check =="
echo "Проект: $ROOT_DIR"
echo

echo "-- Измененные файлы --"
git status --short
echo

echo "-- Синтаксическая проверка Python --"
PYTHONPYCACHEPREFIX="$PYCACHE_PREFIX" "$PYTHON_BIN" -m py_compile \
  aventura_bot/bot.py \
  aventura_bot/config.py \
  aventura_bot/db.py \
  aventura_bot/services/game.py \
  aventura_bot/services/turn_files.py
echo "OK: py_compile"
echo

echo "-- Проверка импорта главного модуля бота --"
PYTHONPYCACHEPREFIX="$PYCACHE_PREFIX" "$PYTHON_BIN" -c "import aventura_bot.bot; print('OK: import aventura_bot.bot')"
echo

echo "-- Напоминание перед выкладкой --"
echo "1. Убедись, что в коммит попали все связанные файлы."
echo "2. Только после этого делай git push."
echo "3. После деплоя проверь /start, /profile, Герой, Миссии, Мой ход, Лавка, Крафт."
echo
echo "Predeploy check completed successfully."
