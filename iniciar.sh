#!/usr/bin/env bash
# Inicia a interface da staff (prepara o ambiente se for a primeira vez). É o alvo do atalho "Pesquisas Nave".
cd "$(dirname "$0")" || exit 1
exec ./setup/staff.sh --sem-atalho "$@"
