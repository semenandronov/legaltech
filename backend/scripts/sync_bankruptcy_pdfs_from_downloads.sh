#!/usr/bin/env bash
# Копирует doc1.pdf, doc2.pdf, doc3.pdf в каталог системных шаблонов банкротства.
# Использование: ./sync_bankruptcy_pdfs_from_downloads.sh [путь_к_папке]
# По умолчанию: ~/Downloads
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# backend/scripts → backend/app/templates/bankruptcy
DEST="$(cd "$SCRIPT_DIR/../app/templates/bankruptcy" && pwd)"
SRC="${1:-$HOME/Downloads}"
mkdir -p "$DEST"
for f in doc1.pdf doc2.pdf doc3.pdf; do
  if [[ ! -f "$SRC/$f" ]]; then
    echo "Не найден файл: $SRC/$f" >&2
    exit 1
  fi
  cp -f "$SRC/$f" "$DEST/"
  echo "OK $f -> $DEST/"
done
echo "Готово. Перезапустите бэкенд, если манифест уже кэшируется в процессе."
