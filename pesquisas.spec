# -*- mode: python ; coding: utf-8 -*-
"""Receita do PyInstaller para o executável da interface web.

Antes de rodar, instale o Chromium DENTRO do pacote do Playwright para ele
ir junto no executável:

    PLAYWRIGHT_BROWSERS_PATH=0 playwright install chromium

Depois:  pyinstaller --noconfirm pesquisas.spec  ->  dist/PesquisasNave/
(construir_windows.bat faz tudo isso no Windows.)
"""

# O próprio Playwright traz um hook do PyInstaller que recolhe o pacote inteiro
# (driver node + JS + o Chromium instalado em .local-browsers).
a = Analysis(
    ["servidor.py"],
    pathex=["."],
    datas=[("web/index.html", "web"), ("web/icone.png", "web")],
    excludes=["tkinter", "unittest", "test"],
    noarchive=False,
)


def dispensavel(caminho: str) -> bool:
    # O Chromium completo também roda invisível (abrir_navegador usa channel="chromium"),
    # então o "headless shell" e o ffmpeg (gravação de vídeo) só ocupariam espaço.
    nome = caminho.replace("\\", "/")
    return "chromium_headless_shell-" in nome or "/ffmpeg-" in nome


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
coll = COLLECT(exe, a.binaries, a.datas, name="PesquisasNave")
