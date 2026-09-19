#!/usr/bin/env bash
# Prepara a máquina da staff e abre a interface (Linux/macOS). Uso: ./setup/staff.sh [--so-instalar] [--sem-atalho]
cd "$(dirname "$0")/.." || exit 1
if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 não encontrado. Instale com o gerenciador da sua distribuição, ex.:"
    echo "  Debian/Ubuntu: sudo apt install python3 python3-venv     Fedora: sudo dnf install python3     Arch/Manjaro: sudo pacman -S python"
    exit 1
fi
exec python3 setup/staff.py "$@"
