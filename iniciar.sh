#!/usr/bin/env bash
# Inicia a interface da staff (prepara o ambiente se for a primeira vez). Equivalente Linux do Pesquisas Nave.exe.
cd "$(dirname "$0")" || exit 1
exec ./setup/staff.sh --sem-exe "$@"
