#!/bin/sh
# Altimetro no macOS: duplo clique (na primeira vez: botao direito > Abrir).
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then
  python3 iniciar.py "$@" || { echo; echo "Algo deu errado (veja acima)."; read -r _; }
else
  echo "Python 3 nao encontrado. Instale em https://www.python.org/downloads/macos/"
  read -r _
fi
