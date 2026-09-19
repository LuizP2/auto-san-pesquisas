#!/usr/bin/env python3
"""Automação da Pesquisa de Satisfação da Nave do Conhecimento.

Fluxo do site (https://pesquisas.navedoconhecimento.rio/):
  login -> /satisfaction-survey (uma pesquisa por vez) -> Enviar
  -> se houver outra pesquisa pendente, ela é carregada na mesma tela
  -> quando não há mais nenhuma, o site vai para /end.

As perguntas de perfil (sexo, rede municipal, período, faixa etária e
atividade) são respondidas pelo usuário antes da execução e ficam no
config.json. Todas as outras perguntas recebem a resposta padrão
("Muito Satisfeito").
"""

from __future__ import annotations

import argparse
import getpass
import json
import logging
import os
import sys
import time
import unicodedata
from pathlib import Path

# Empacotado pelo PyInstaller: os dados (config, capturas) ficam ao lado do executável
# e os recursos embutidos (web/, navegador) na pasta temporária que ele extrai.
EMPACOTADO = bool(getattr(sys, "frozen", False))
PASTA = Path(sys.executable).resolve().parent if EMPACOTADO else Path(__file__).resolve().parent
RECURSOS = Path(getattr(sys, "_MEIPASS", PASTA))
VENV = PASTA / ".venv"
PYTHON_VENV = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def garantir_ambiente() -> None:
    """Se rodou com o Python do sistema, troca para o do .venv (onde está o Playwright)."""
    if EMPACOTADO:
        # Chromium copiado para dentro do pacote pelo pesquisas.spec.
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(RECURSOS / "ms-playwright")
        return
    try:
        import playwright  # noqa: F401
    except ModuleNotFoundError:
        ja_no_venv = Path(sys.prefix).resolve() == VENV.resolve()
        if PYTHON_VENV.exists() and not ja_no_venv:
            if os.name == "nt":  # no Windows execv não substitui o processo; espera o filho
                import subprocess

                sys.exit(subprocess.call([str(PYTHON_VENV), *sys.argv]))
            os.execv(str(PYTHON_VENV), [str(PYTHON_VENV), *sys.argv])
        sys.exit(
            "Playwright não instalado. Na pasta do projeto, rode:\n"
            "  python3 -m venv .venv\n"
            "  .venv/bin/pip install -r requirements.txt\n"
            "  .venv/bin/playwright install chromium"
        )


garantir_ambiente()

from playwright.sync_api import Error as ErroPlaywright  # noqa: E402
from playwright.sync_api import Page, sync_playwright  # noqa: E402

URL = "https://pesquisas.navedoconhecimento.rio/"
CONFIG_PADRAO = PASTA / "config.json"
CAPTURA_ERRO = PASTA / "erro.png"
RESPOSTA_PADRAO = "Muito Satisfeito"
TEMPO_ESPERA = 30  # segundos para o site responder a cada etapa
MAX_PESQUISAS = 30  # trava de segurança contra loop infinito
log = logging.getLogger("pesquisa")  # progresso da automação (terminal ou interface web)

# Perguntas respondidas pelo usuário antes de rodar, com as opções que o site oferece.
PERGUNTAS_PERFIL = [
    ("Sexo", ["Masculino", "Feminino"]),
    ("É aluno da rede municipal de ensino?", ["Sim", "Não"]),
    (
        "Em que período você frequenta a Nave do Conhecimento?",
        ["Manhã", "Tarde", "Noite", "Final de Semana"],
    ),
    (
        "Qual a sua faixa etária?",
        ["0 a 5 anos", "06 a 11 anos", "12 a 17 anos", "18 a 60 anos", "Acima de 60 anos"],
    ),
    ("Qual atividade você realizou?", ["Oficina", "Curso"]),
]

# Lê as perguntas renderizadas na tela: cada b-field com rótulo é uma pergunta.
JS_LER_PERGUNTAS = """
() => [...document.querySelectorAll('.survey-box .field')].flatMap(campo => {
    const rotulo = campo.querySelector('label.label');
    if (!rotulo) return [];
    return [{
        pergunta: rotulo.textContent.trim(),
        alternativas: [...campo.querySelectorAll('input[type=radio]')].map(r => ({
            nome: r.name,
            valor: r.value,
            marcada: r.checked,
            texto: (r.closest('label') || r.parentElement).textContent.trim(),
        })),
        textos: [...campo.querySelectorAll('input:not([type=radio])')].map(i => ({
            nome: i.name,
            visivel: i.offsetParent !== null,
        })),
    }];
})
"""


class ErroAutomacao(Exception):
    """Falha esperada (site recusou, resposta não encontrada etc.)."""


# ---------------------------------------------------------------------------
# Comparação de textos
# ---------------------------------------------------------------------------


def normalizar(texto: str) -> str:
    """Minúsculas, sem acentos, sem pontuação e com espaços únicos."""
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    )
    limpo = "".join(c if c.isalnum() or c.isspace() else " " for c in sem_acento)
    return " ".join(limpo.lower().split())


def resolver_resposta(pergunta: str, respostas: dict[str, str]) -> str | None:
    """Resposta configurada cuja chave casa com a pergunta (a chave mais longa vence)."""
    p = normalizar(pergunta)
    candidatas = []
    for chave, valor in respostas.items():
        c = normalizar(chave)
        if c and (c in p or p in c):
            candidatas.append((len(c), valor))
    return max(candidatas)[1] if candidatas else None


def escolher_alternativa(resposta: str, alternativas: list[dict]) -> dict | None:
    """Alternativa cujo texto é igual à resposta; senão a única que começa com ela."""
    r = normalizar(resposta)
    exatas = [a for a in alternativas if normalizar(a["texto"]) == r]
    if exatas:
        return exatas[0]
    prefixo = [a for a in alternativas if normalizar(a["texto"]).startswith(r)]
    return prefixo[0] if len(prefixo) == 1 else None


# ---------------------------------------------------------------------------
# Configuração (perguntas de perfil + credenciais)
# ---------------------------------------------------------------------------


def carregar_config(caminho: Path) -> dict | None:
    if not caminho.exists():
        return None
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


def salvar_config(caminho: Path, config: dict) -> None:
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
        f.write("\n")


def perguntar_texto(rotulo: str, atual: str = "") -> str:
    sugestao = f" [{atual}]" if atual else ""
    while True:
        digitado = input(f"{rotulo}{sugestao}: ").strip()
        if digitado:
            return digitado
        if atual:
            return atual
        print("  Campo obrigatório.")


def perguntar_sim_nao(rotulo: str, padrao: bool = False) -> bool:
    digitado = input(f"{rotulo} ({'S/n' if padrao else 's/N'}): ").strip().lower()
    if not digitado:
        return padrao
    return digitado.startswith("s")


def escolher(pergunta: str, opcoes: list[str], atual: str | None = None) -> str:
    print(f"\n{pergunta}")
    for i, opcao in enumerate(opcoes, 1):
        print(f"  {i}) {opcao}")
    sugestao = f" [{atual}]" if atual else ""
    while True:
        digitado = input(f"Resposta{sugestao}: ").strip()
        if not digitado and atual:
            return atual
        if digitado.isdigit() and 1 <= int(digitado) <= len(opcoes):
            return opcoes[int(digitado) - 1]
        if digitado:
            escolhida = escolher_alternativa(digitado, [{"texto": o} for o in opcoes])
            if escolhida:
                return escolhida["texto"]
        print("  Opção inválida — digite o número ou o texto de uma das opções.")


def configurar(caminho: Path, config: dict | None = None, somente_faltantes: bool = False) -> dict:
    """Pergunta usuário, senha e as respostas de perfil; salva no config.json.

    Com somente_faltantes=True só pergunta o que ainda não está no arquivo.
    """
    config = dict(config or {})
    respostas = dict(config.get("respostas") or {})
    alterado = False

    if not somente_faltantes:
        print("=== Configuração da automação ===")
        print("As respostas abaixo valem para todas as pesquisas.")
        print(f"Para mudar depois, rode com --configurar ou edite {caminho}.\n")

    if not somente_faltantes or not config.get("usuario"):
        config["usuario"] = perguntar_texto("Usuário do site", config.get("usuario", ""))
        alterado = True

    if not somente_faltantes:
        if perguntar_sim_nao("Guardar a senha no config.json (fica em texto puro)?"):
            config["senha"] = getpass.getpass("Senha: ")
        else:
            config.pop("senha", None)
        alterado = True

    for pergunta, opcoes in PERGUNTAS_PERFIL:
        atual = resolver_resposta(pergunta, respostas)
        if somente_faltantes and atual:
            continue
        respostas[pergunta] = escolher(pergunta, opcoes, atual)
        alterado = True

    config["respostas"] = respostas
    config.setdefault("resposta_padrao", RESPOSTA_PADRAO)
    if alterado or not caminho.exists():
        salvar_config(caminho, config)
        print(f"\nConfiguração salva em {caminho}")
    return config


# ---------------------------------------------------------------------------
# Interação com o site
# ---------------------------------------------------------------------------


def em_pagina_final(pagina: Page) -> bool:
    return pagina.url.rstrip("/").endswith("/end")


def ler_dialogo(pagina: Page) -> str | None:
    """Texto do diálogo (b-dialog) aberto, ou None se não houver."""
    corpo = pagina.locator(".modal.is-active .modal-card-body")
    if corpo.count() and corpo.first.is_visible():
        return " ".join(corpo.first.inner_text().split())
    return None


def fechar_dialogo(pagina: Page) -> None:
    pagina.locator(".modal.is-active .modal-card-foot button").last.click()


def fazer_login(pagina: Page, usuario: str, senha: str) -> None:
    log.info("Abrindo %s", URL)
    pagina.goto(URL)
    pagina.locator("input[type=text]").first.fill(usuario)
    pagina.locator("input[type=password]").first.fill(senha)
    pagina.get_by_role("button", name="Entrar").click()

    limite = time.monotonic() + TEMPO_ESPERA
    while time.monotonic() < limite:
        if "/satisfaction-survey" in pagina.url or em_pagina_final(pagina):
            log.info("Login OK (%s)", usuario)
            return
        mensagem = ler_dialogo(pagina)
        if mensagem:
            raise ErroAutomacao(f"Login falhou: {mensagem}")
        pagina.wait_for_timeout(250)
    raise ErroAutomacao("O site não respondeu ao login.")


def esperar_pesquisa(pagina: Page) -> bool:
    """True quando há uma pesquisa na tela; False quando o site foi para /end."""
    limite = time.monotonic() + TEMPO_ESPERA
    while time.monotonic() < limite:
        if em_pagina_final(pagina):
            return False
        carregando = pagina.locator(".loading-overlay.is-active").count()
        campos = pagina.locator(".survey-box .field input").count()
        if campos and not carregando:
            return True
        pagina.wait_for_timeout(250)
    raise ErroAutomacao("A pesquisa não carregou.")


def ler_titulo(pagina: Page) -> str:
    etiqueta = pagina.locator(".survey-box .tag")
    if etiqueta.count():
        return " ".join(etiqueta.first.inner_text().split())
    return "(turma não identificada)"


def marcar_alternativa(pagina: Page, alternativa: dict) -> None:
    seletor = f'input[name="{alternativa["nome"]}"][value="{alternativa["valor"]}"]'
    # O input do b-radio fica invisível; o clique vai no rótulo que o envolve.
    pagina.locator(f"label:has({seletor})").first.click()
    entrada = pagina.locator(seletor).first
    if not entrada.is_checked():
        entrada.check(force=True)
    if not entrada.is_checked():
        raise ErroAutomacao(f'Não consegui marcar "{alternativa["texto"]}".')


def preencher_pesquisa(pagina: Page, config: dict) -> None:
    respostas = config.get("respostas") or {}
    padrao = config.get("resposta_padrao") or RESPOSTA_PADRAO
    perguntas = pagina.evaluate(JS_LER_PERGUNTAS)
    if not perguntas:
        raise ErroAutomacao("Nenhuma pergunta encontrada na tela.")

    for q in perguntas:
        configurada = resolver_resposta(q["pergunta"], respostas)
        if q["alternativas"]:
            resposta = configurada or padrao
            alternativa = escolher_alternativa(resposta, q["alternativas"])
            if alternativa is None:
                opcoes = ", ".join(a["texto"] for a in q["alternativas"])
                raise ErroAutomacao(
                    f'A resposta "{resposta}" não existe na pergunta "{q["pergunta"]}". '
                    f"Opções: {opcoes}. Acrescente essa pergunta em \"respostas\" no config.json."
                )
            marcar_alternativa(pagina, alternativa)
            log.info("  ✔ %s → %s", q["pergunta"], alternativa["texto"])
        elif q["textos"]:
            if not configurada:
                raise ErroAutomacao(
                    f'A pergunta discursiva "{q["pergunta"]}" não tem resposta configurada. '
                    'Acrescente-a em "respostas" no config.json.'
                )
            for campo in q["textos"]:
                pagina.locator(f'input[name="{campo["nome"]}"]').first.fill(configurada)
            log.info("  ✔ %s → %s", q["pergunta"], configurada)

    # Alternativas "justificáveis" exibem um campo de texto depois de marcadas.
    for q in pagina.evaluate(JS_LER_PERGUNTAS):
        for campo in q["textos"]:
            if q["alternativas"] and campo["visivel"]:
                justificativa = config.get("justificativa")
                if not justificativa:
                    raise ErroAutomacao(
                        f'A alternativa escolhida em "{q["pergunta"]}" pede justificativa. '
                        'Defina "justificativa" no config.json.'
                    )
                pagina.locator(f'input[name="{campo["nome"]}"]').first.fill(justificativa)


def enviar_pesquisa(pagina: Page) -> str:
    """Clica em Enviar e devolve a mensagem de sucesso do site."""
    # Espera sumir o toast da pesquisa anterior para não confundir com o novo.
    pagina.locator(".toast").first.wait_for(state="hidden", timeout=TEMPO_ESPERA * 1000)
    pagina.get_by_role("button", name="Enviar").click()
    toast = pagina.locator(".toast").first
    toast.wait_for(state="visible", timeout=TEMPO_ESPERA * 1000)
    classes = toast.get_attribute("class") or ""
    mensagem = " ".join(toast.inner_text().split())
    if "is-danger" in classes:
        raise ErroAutomacao(f"O site recusou o envio: {mensagem}")
    return mensagem


def esperar_proxima_etapa(pagina: Page, titulo_anterior: str) -> str:
    """Depois do envio: 'fim' (foi para /end) ou 'outra' (carregou outra pesquisa)."""
    limite = time.monotonic() + TEMPO_ESPERA
    while time.monotonic() < limite:
        if em_pagina_final(pagina):
            return "fim"
        mensagem = ler_dialogo(pagina)
        if mensagem:
            if "outra pesquisa" not in normalizar(mensagem):
                raise ErroAutomacao(f"O site exibiu um aviso: {mensagem}")
            fechar_dialogo(pagina)
            try:
                pagina.wait_for_function(
                    "anterior => document.querySelector('.survey-box .tag')?.textContent.trim() !== anterior",
                    arg=titulo_anterior,
                    timeout=5000,
                )
            except ErroPlaywright:
                raise ErroAutomacao(
                    f"O site avisou que há outra pesquisa, mas continuou em {titulo_anterior}."
                ) from None
            return "outra"
        pagina.wait_for_timeout(250)
    raise ErroAutomacao("O site não avançou após o envio.")


def abrir_navegador(pw, headless: bool):
    """Chromium completo tanto visível quanto invisível (dispensa o 'headless shell',
    que ficaria de fora do executável empacotado)."""
    return pw.chromium.launch(headless=headless, channel="chromium")


def executar(pagina: Page, config: dict, senha: str, enviar: bool = True) -> int:
    """Faz login e responde todas as pesquisas pendentes. Devolve quantas enviou."""
    fazer_login(pagina, config["usuario"], senha)
    respondidas = 0
    while respondidas < MAX_PESQUISAS:
        if not esperar_pesquisa(pagina):
            break
        titulo = ler_titulo(pagina)
        log.info("Pesquisa: %s", titulo)
        preencher_pesquisa(pagina, config)
        if not enviar:
            log.info("Pesquisa preenchida, mas NÃO enviada (modo sem enviar).")
            return respondidas
        mensagem = enviar_pesquisa(pagina)
        respondidas += 1
        log.info("  ✅ %s", mensagem)
        if esperar_proxima_etapa(pagina, titulo) == "fim":
            break

    if respondidas == 0:
        log.info("Nenhuma pesquisa pendente para este usuário.")
    else:
        log.info("%d pesquisa(s) respondida(s).", respondidas)
    return respondidas


# ---------------------------------------------------------------------------
# Linha de comando
# ---------------------------------------------------------------------------


def segurar_navegador(args: argparse.Namespace, mensagem: str) -> None:
    if not args.headless and sys.stdin.isatty():
        input(f"\n{mensagem} Pressione Enter para fechar o navegador.")


def salvar_captura(pagina: Page, caminho: Path | None = None, avisar: bool = True) -> bool:
    caminho = caminho or CAPTURA_ERRO
    try:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        pagina.screenshot(path=str(caminho), full_page=True)
    except (ErroPlaywright, OSError):
        return False
    if avisar:
        log.info("Captura da tela salva em %s", caminho)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Responde as pesquisas de satisfação da Nave do Conhecimento."
    )
    parser.add_argument("--config", type=Path, default=CONFIG_PADRAO, help="arquivo de configuração")
    parser.add_argument(
        "--configurar", action="store_true", help="refaz as perguntas de perfil e salva o config"
    )
    parser.add_argument("--headless", action="store_true", help="roda sem mostrar o navegador")
    parser.add_argument(
        "--sem-enviar", action="store_true", help="preenche mas não clica em Enviar (para conferir)"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)

    config = carregar_config(args.config)
    if config is None or args.configurar:
        config = configurar(args.config, config)
    else:
        config = configurar(args.config, config, somente_faltantes=True)

    senha = config.get("senha") or os.environ.get("SAN_SENHA")
    if not senha:
        senha = getpass.getpass(f"Senha de {config['usuario']}: ")

    codigo = 0
    with sync_playwright() as pw:
        navegador = abrir_navegador(pw, args.headless)
        pagina = navegador.new_page()
        try:
            executar(pagina, config, senha, enviar=not args.sem_enviar)
            if args.sem_enviar:
                segurar_navegador(args, "Confira o preenchimento no navegador.")
        except ErroAutomacao as e:
            codigo = 1
            log.error("❌ %s", e)
            salvar_captura(pagina)
            segurar_navegador(args, "O navegador continua aberto para você terminar manualmente.")
        except ErroPlaywright as e:
            codigo = 1
            log.error("❌ Erro no navegador: %s", e.message.splitlines()[0])
            salvar_captura(pagina)
            segurar_navegador(args, "O navegador continua aberto para você terminar manualmente.")
        except KeyboardInterrupt:
            codigo = 130
            print("\nInterrompido.")
        finally:
            navegador.close()
    return codigo


if __name__ == "__main__":
    sys.exit(main())
