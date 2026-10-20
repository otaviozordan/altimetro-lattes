#!/bin/sh
# Altimetro no Linux: ./altimetro-linux.sh (ou duplo clique, se o gerenciador de arquivos permitir).
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then
  exec python3 iniciar.py "$@"
else
  echo "Python 3 nao encontrado. Debian/Ubuntu: sudo apt install python3 python3-venv python3-tk"
  exit 1
fi
