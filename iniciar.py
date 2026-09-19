#!/usr/bin/env python3
"""Lançador da interface da staff — é a fonte do "Pesquisas Nave.exe" que o
setup gera na raiz do projeto (Windows). No Linux, iniciar.sh faz o mesmo.

Se o .venv já existe ao lado, inicia o servidor.py; senão roda o setup, que
instala tudo e inicia. Só usa a biblioteca padrão.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

EMPACOTADO = bool(getattr(sys, "frozen", False))
RAIZ = Path(sys.executable).resolve().parent if EMPACOTADO else Path(__file__).resolve().parent
WINDOWS = os.name == "nt"
PYTHON_VENV = RAIZ / (".venv/Scripts/python.exe" if WINDOWS else ".venv/bin/python")


def main() -> int:
    os.chdir(RAIZ)
    argumentos = sys.argv[1:]
    if PYTHON_VENV.exists():
        codigo = subprocess.call([str(PYTHON_VENV), str(RAIZ / "servidor.py"), *argumentos])
    elif WINDOWS:
        codigo = subprocess.call(["cmd", "/c", str(RAIZ / "setup" / "staff.bat"), "--sem-exe", *argumentos])
    else:
        codigo = subprocess.call([str(RAIZ / "setup" / "staff.sh"), "--sem-exe", *argumentos])
    if codigo != 0 and EMPACOTADO and sys.stdin and sys.stdin.isatty():
        input("\nAlgo deu errado (veja acima). Pressione Enter para fechar.")
    return codigo


if __name__ == "__main__":
    sys.exit(main())
