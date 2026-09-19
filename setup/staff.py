#!/usr/bin/env python3
"""Prepara a máquina da staff e abre a interface de pesquisas.

    Windows: dois cliques em setup\\staff.bat      Linux: ./setup/staff.sh

Faz, nesta ordem (pulando o que já estiver pronto):
  1. cria o ambiente Python do projeto (.venv);
  2. instala as dependências (Playwright);
  3. baixa o Chromium do Playwright (uma vez, ~150 MB);
  4. no Windows, gera "Pesquisas Nave.exe" na raiz do projeto (lançador da
     interface; no Linux o equivalente é o iniciar.sh);
  5. inicia o servidor local, que abre o navegador na interface.

Opções: --so-instalar (para nos passos 1-3), --sem-exe (pula o passo 4);
outras opções (ex.: --porta 8080, --sem-abrir) vão para o servidor.py. Só usa
a biblioteca padrão: roda com o Python do sistema.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
VENV = RAIZ / ".venv"
WINDOWS = os.name == "nt"
PYTHON_VENV = VENV / ("Scripts/python.exe" if WINDOWS else "bin/python")
NOME_EXE = "Pesquisas Nave"


class Falha(Exception):
    pass


def passo(n: int, texto: str) -> None:
    print(f"\n[{n}/5] {texto}", flush=True)


def rodar(comando: list[str], dica: str = "") -> None:
    """Executa mostrando a saída; se falhar, explica qual comando foi."""
    print("  $", " ".join(str(c) for c in comando), flush=True)
    resultado = subprocess.run([str(c) for c in comando])
    if resultado.returncode != 0:
        mensagem = f"O comando falhou (código {resultado.returncode}): {' '.join(str(c) for c in comando)}"
        raise Falha(mensagem + (f"\n{dica}" if dica else ""))


# ---------------------------------------------------------------------------
# Passos
# ---------------------------------------------------------------------------


def criar_venv() -> None:
    if PYTHON_VENV.exists():
        print("  .venv já existe.")
        return
    if sys.version_info < (3, 10):
        raise Falha(f"Python {sys.version.split()[0]} é antigo demais; instale o 3.10 ou mais novo.")
    rodar(
        [sys.executable, "-m", "venv", str(VENV)],
        dica="No Debian/Ubuntu o módulo venv vem separado: sudo apt install python3-venv" if not WINDOWS else "",
    )


def instalar_dependencias() -> None:
    rodar(
        [PYTHON_VENV, "-m", "pip", "install", "--disable-pip-version-check", "-r", RAIZ / "requirements.txt"],
        dica="Sem internet ou proxy bloqueando o pypi.org? Tente de novo numa rede sem restrições.",
    )


def instalar_chromium() -> None:
    # No lugar padrão do Playwright (caminho curto): evita o limite de 260 caracteres do Windows.
    ambiente = {k: v for k, v in os.environ.items() if k != "PLAYWRIGHT_BROWSERS_PATH"}
    print("  $", f"{PYTHON_VENV} -m playwright install chromium", flush=True)
    r = subprocess.run([str(PYTHON_VENV), "-m", "playwright", "install", "chromium"], env=ambiente)
    if r.returncode != 0:
        raise Falha(
            "Não consegui baixar o Chromium. Sem internet, ou a rede bloqueia cdn.playwright.dev / "
            "playwright.download.prss.microsoft.com? Tente de novo em outra rede."
        )
    if not WINDOWS and shutil.which("apt-get"):
        # Bibliotecas do sistema que o Chromium precisa (Debian/Ubuntu); pede a senha do sudo.
        sudo = [] if os.geteuid() == 0 else (["sudo"] if shutil.which("sudo") else None)
        if sudo is None:
            print("  (pulei as bibliotecas do sistema: sem sudo)")
            return
        r = subprocess.run([*sudo, str(PYTHON_VENV), "-m", "playwright", "install-deps", "chromium"], env=ambiente)
        if r.returncode != 0:
            print("  Aviso: não instalei as bibliotecas do sistema. Se o navegador não abrir, rode:")
            print(f"    sudo {PYTHON_VENV} -m playwright install-deps chromium")


def gerar_exe() -> Path | None:
    """Windows: empacota o iniciar.py num .exe com ícone, na raiz do projeto (PyInstaller)."""
    if not WINDOWS:
        return None
    exe = RAIZ / f"{NOME_EXE}.exe"
    fonte = RAIZ / "iniciar.py"
    if exe.exists() and exe.stat().st_mtime >= fonte.stat().st_mtime:
        print(f"  {exe.name} já existe.")
        return exe
    rodar([PYTHON_VENV, "-m", "pip", "install", "--disable-pip-version-check", "pyinstaller"])
    rodar([
        PYTHON_VENV, "-m", "PyInstaller", "--noconfirm", "--log-level", "WARN", "--onefile", "--console",
        "--name", NOME_EXE, "--icon", RAIZ / "web" / "icone.ico",
        "--distpath", RAIZ, "--workpath", RAIZ / "build", "--specpath", RAIZ / "build", fonte,
    ], dica="Se o antivírus reclamou do PyInstaller, use iniciar.bat no lugar do .exe.")
    return exe


def iniciar_servidor(argumentos: list[str]) -> int:
    print("  Feche a janela (ou Ctrl+C) para encerrar.", flush=True)
    return subprocess.call([str(PYTHON_VENV), str(RAIZ / "servidor.py"), *argumentos], cwd=str(RAIZ))


# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepara a máquina da staff e abre a interface.")
    parser.add_argument("--so-instalar", action="store_true", help="só prepara o ambiente; não cria atalho nem inicia")
    parser.add_argument("--sem-exe", action="store_true", help="não gera o Pesquisas Nave.exe (Windows)")
    args, para_o_servidor = parser.parse_known_args(argv)  # o resto (ex.: --porta 8080) vai para o servidor.py

    print(f"Pesquisas Nave — preparação da máquina (Python {sys.version.split()[0]}, pasta {RAIZ})")
    try:
        passo(1, "Ambiente Python do projeto")
        criar_venv()
        passo(2, "Dependências (Playwright)")
        instalar_dependencias()
        passo(3, "Chromium do Playwright")
        instalar_chromium()
        if args.so_instalar:
            print("\nAmbiente pronto.")
            return 0
        if not WINDOWS:
            passo(4, "Lançador: no Linux use ./iniciar.sh (não há .exe)")
        elif args.sem_exe:
            passo(4, "Pesquisas Nave.exe: pulado")
        else:
            passo(4, "Pesquisas Nave.exe na pasta do projeto")
            print(f"  Pronto: {gerar_exe()}")
        passo(5, "Iniciando o servidor (o navegador abre sozinho)")
        return iniciar_servidor(para_o_servidor)
    except Falha as e:
        print(f"\n❌ {e}", file=sys.stderr)
        print("Copie a mensagem acima para pedir ajuda.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrompido.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
