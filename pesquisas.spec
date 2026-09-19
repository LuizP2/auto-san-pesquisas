# -*- mode: python ; coding: utf-8 -*-
"""Receita do PyInstaller para o executável da interface web.

Requisitos (construir_windows.bat faz tudo): o .venv com o Playwright e o
Chromium instalado no lugar padrão (`playwright install chromium`). O Chromium
é copiado do cache padrão para dentro do pacote, em ms-playwright/.

    pyinstaller --noconfirm pesquisas.spec  ->  dist/PesquisasNave/
"""

import json
import os
import sys
from pathlib import Path

import playwright


def cache_playwright() -> Path:
    """Onde `playwright install` guarda os navegadores."""
    definido = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if definido and definido != "0":
        return Path(definido)
    if sys.platform == "win32":
        return Path(os.environ["LOCALAPPDATA"]) / "ms-playwright"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "ms-playwright"
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "ms-playwright"


pacote = Path(playwright.__file__).parent / "driver" / "package"
revisao = next(b["revision"] for b in json.loads((pacote / "browsers.json").read_text())["browsers"] if b["name"] == "chromium")
chromium = cache_playwright() / f"chromium-{revisao}"
if not chromium.is_dir():
    raise SystemExit(f"Chromium {revisao} não encontrado em {chromium}. Rode: python -m playwright install chromium")
print(f"Embutindo {chromium}")

a = Analysis(
    ["servidor.py"],
    pathex=["."],
    datas=[("web/index.html", "web"), ("web/icone.png", "web")],
    excludes=["tkinter", "unittest", "test"],
    noarchive=False,
)


def dispensavel(caminho: str) -> bool:
    # Se alguém instalou navegadores dentro do pacote (PLAYWRIGHT_BROWSERS_PATH=0), não duplicar.
    return ".local-browsers" in caminho.replace("\\", "/")


a.datas = [d for d in a.datas if not dispensavel(d[0])]
a.binaries = [b for b in a.binaries if not dispensavel(b[0])]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PesquisasNave",
    icon="web/icone.ico",
    console=True,  # a janela mostra o registro; fechar a janela encerra o servidor
    upx=False,
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    Tree(str(chromium), prefix=f"ms-playwright/chromium-{revisao}"),
    name="PesquisasNave",
)
