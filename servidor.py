#!/usr/bin/env python3
"""Interface web local para a automação das pesquisas.

    python3 servidor.py            -> abre http://127.0.0.1:8765 no navegador

Só usa a biblioteca padrão: a página (web/index.html) conversa com este
servidor por JSON e acompanha o progresso da execução por polling.
Além da conta única do config.json, mantém uma lista de contas (contas.json)
que pode ser executada em lote.
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import re
import sys
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pesquisa  # também garante o .venv (re-executa este script com o Python certo)
import planilha
import san2

PAGINA = pesquisa.RECURSOS / "web" / "index.html"
CONTAS = pesquisa.PASTA / "contas.json"
CAPTURAS = pesquisa.PASTA / "capturas"
ESCALA = ["Muito Satisfeito", "Satisfeito", "Indiferente", "Insatisfeito", "Muito Insatisfeito"]
TEMPO_MAX_AGUARDANDO = 30 * 60  # segundos com o navegador aberto esperando o usuário
log = pesquisa.log
SESSAO_SAN2 = san2.Sessao()


class RequisicaoInvalida(Exception):
    pass


# ---------------------------------------------------------------------------
# Execução da automação em segundo plano (uma por vez)
# ---------------------------------------------------------------------------


class Execucao:
    """Estado da execução atual: ocioso | executando | aguardando | concluido | erro.

    'aguardando' é quando a automação terminou (ou falhou) com o navegador
    visível e o mantém aberto até o usuário mandar fechar — igual ao
    comportamento da linha de comando. No lote não há essa pausa: uma conta
    que falha é registrada (com captura da tela) e a próxima segue.
    """

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.estado = "ocioso"
        self.linhas: list[dict] = []
        self.captura = False
        self.fechar = threading.Event()
        self.thread: threading.Thread | None = None

    def registrar(self, nivel: str, texto: str, captura: str | None = None) -> None:
        with self.lock:
            linha = {"n": len(self.linhas), "nivel": nivel, "texto": texto}
            if captura:
                linha["captura"] = captura
            self.linhas.append(linha)

    def snapshot(self, desde: int) -> dict:
        with self.lock:
            return {
                "estado": self.estado,
                "linhas": self.linhas[desde:],
                "total": len(self.linhas),
                "captura": self.captura,
            }

    def _comecar(self, alvo, *args) -> bool:
        with self.lock:
            if self.estado in ("executando", "aguardando"):
                return False
            self.estado, self.linhas, self.captura = "executando", [], False
            self.fechar.clear()
            self.thread = threading.Thread(target=alvo, args=args, daemon=True)
            self.thread.start()
            return True

    def iniciar(self, config: dict, senha: str, enviar: bool, headless: bool) -> bool:
        return self._comecar(self._rodar, config, senha, enviar, headless)

    def iniciar_lote(self, contas: list[dict], enviar: bool, headless: bool) -> bool:
        return self._comecar(self._rodar_lote, contas, enviar, headless)

    def pedir_fechamento(self) -> None:
        self.fechar.set()

    def _terminar(self, resultado: str) -> None:
        with self.lock:
            self.estado = resultado

    def _rodar(self, config: dict, senha: str, enviar: bool, headless: bool) -> None:
        resultado = "concluido"
        try:
            with pesquisa.sync_playwright() as pw:
                navegador = pesquisa.abrir_navegador(pw, headless)
                pagina = navegador.new_page()
                try:
                    pesquisa.executar(pagina, config, senha, enviar=enviar)
                    if not enviar and not headless:
                        self._aguardar("Confira o preenchimento no navegador e clique em “Fechar navegador”.")
                except pesquisa.ErroAutomacao as e:
                    resultado = "erro"
                    log.error("❌ %s", e)
                    self.captura = pesquisa.salvar_captura(pagina)
                    if not headless:
                        self._aguardar("O navegador continua aberto para você terminar manualmente.")
                except pesquisa.ErroPlaywright as e:
                    resultado = "erro"
                    log.error("❌ Erro no navegador: %s", e.message.splitlines()[0])
                    self.captura = pesquisa.salvar_captura(pagina)
                finally:
                    navegador.close()
        except Exception:  # falha inesperada: registra e mantém o servidor vivo
            resultado = "erro"
            log.exception("❌ Falha inesperada")
        self._terminar(resultado)

    def _rodar_lote(self, contas: list[dict], enviar: bool, headless: bool) -> None:
        falhas: list[str] = []
        ignoradas: list[str] = []
        try:
            with pesquisa.sync_playwright() as pw:
                navegador = pesquisa.abrir_navegador(pw, headless)
                for i, conta in enumerate(contas, 1):
                    log.info("Conta %d/%d: %s", i, len(contas), conta["usuario"])
                    contexto = navegador.new_context()  # sessão limpa para cada conta
                    pagina = contexto.new_page()
                    try:
                        pesquisa.executar(pagina, conta["config"], conta["senha"], enviar=enviar)
                    except pesquisa.ErroAutomacao as e:
                        if str(e).startswith("Login falhou"):
                            # senha diferente da padrão: a pessoa é pulada, sem alarde
                            ignoradas.append(conta["usuario"])
                            log.warning("⏭ Ignorada — o site recusou o login (senha diferente da padrão?)")
                        else:
                            falhas.append(conta["usuario"])
                            self._registrar_falha(pagina, i, conta["usuario"], str(e))
                    except pesquisa.ErroPlaywright as e:
                        falhas.append(conta["usuario"])
                        self._registrar_falha(pagina, i, conta["usuario"], e.message.splitlines()[0])
                    finally:
                        contexto.close()
                navegador.close()
        except Exception:
            log.exception("❌ Falha inesperada")
            self._terminar("erro")
            return
        ok = len(contas) - len(falhas) - len(ignoradas)
        partes = [f"{ok} de {len(contas)} conta(s) OK"]
        if ignoradas:
            partes.append(f"{len(ignoradas)} ignorada(s) por senha diferente: {', '.join(ignoradas)}")
        if falhas:
            partes.append(f"{len(falhas)} com erro: {', '.join(falhas)}")
        (log.error if falhas else log.info)("Resumo: " + ". ".join(partes) + ".")
        self._terminar("erro" if falhas else "concluido")

    def _registrar_falha(self, pagina, indice: int, usuario: str, mensagem: str) -> None:
        arquivo = nome_captura(indice, usuario)
        salvou = pesquisa.salvar_captura(pagina, CAPTURAS / arquivo, avisar=False)
        log.error("❌ %s", mensagem, extra={"captura": arquivo if salvou else None})

    def _aguardar(self, mensagem: str) -> None:
        log.info(mensagem)
        with self.lock:
            self.estado = "aguardando"
        self.fechar.wait(TEMPO_MAX_AGUARDANDO)
        with self.lock:
            self.estado = "executando"


class ManipuladorLog(logging.Handler):
    """Copia as mensagens do logger 'pesquisa' para a execução atual."""

    def __init__(self, execucao: Execucao) -> None:
        super().__init__()
        self.execucao = execucao

    def emit(self, registro: logging.LogRecord) -> None:
        self.execucao.registrar(
            registro.levelname.lower(), self.format(registro), getattr(registro, "captura", None)
        )


EXECUCAO = Execucao()


def nome_captura(indice: int, usuario: str) -> str:
    seguro = re.sub(r"[^A-Za-z0-9_.-]+", "_", usuario).strip("_") or "conta"
    return f"{indice:02d}-{seguro}.png"


# ---------------------------------------------------------------------------
# Configuração (mesmo config.json da linha de comando) e lista de contas
# ---------------------------------------------------------------------------


def config_publica() -> dict:
    """O que a página precisa para se montar (sem a senha)."""
    config = pesquisa.carregar_config(pesquisa.CONFIG_PADRAO) or {}
    respostas = config.get("respostas") or {}
    return {
        "usuario": config.get("usuario", ""),
        "senha_salva": bool(config.get("senha")),
        "perguntas": [{"texto": p, "opcoes": o} for p, o in pesquisa.PERGUNTAS_PERFIL],
        "respostas": {
            p: pesquisa.resolver_resposta(p, respostas) for p, _ in pesquisa.PERGUNTAS_PERFIL
        },
        "escala": ESCALA,
        "resposta_padrao": config.get("resposta_padrao") or pesquisa.RESPOSTA_PADRAO,
        "contas": contas_publicas(),
        "san2_usuario": config.get("san2_usuario", ""),
        "san2_senha_salva": bool(config.get("san2_senha")),
        "senha_padrao": config.get("senha_padrao") or "",
    }


def contas_publicas() -> list[dict]:
    return [{**c, "senha": ""} for c in carregar_contas()]  # senhas nunca voltam à página


def carregar_contas() -> list[dict]:
    if not CONTAS.exists():
        return []
    with open(CONTAS, encoding="utf-8") as f:
        return json.load(f).get("contas", [])


def salvar_contas(contas: list[dict]) -> None:
    with open(CONTAS, "w", encoding="utf-8") as f:
        json.dump({"contas": contas}, f, ensure_ascii=False, indent=2)
        f.write("\n")


def validar_respostas(respostas: dict) -> dict:
    for pergunta, opcoes in pesquisa.PERGUNTAS_PERFIL:
        if respostas.get(pergunta) not in opcoes:
            raise RequisicaoInvalida(f"Responda: {pergunta}")
    return {p: respostas[p] for p, _ in pesquisa.PERGUNTAS_PERFIL}


def validar_contas(dados: dict) -> list[dict]:
    """Lista enviada pela página. Senha em branco mantém a que já estava salva."""
    salvas = {c["usuario"]: c for c in carregar_contas()}
    contas, vistos = [], set()
    for item in dados.get("contas") or []:
        usuario = str(item.get("usuario") or "").strip()
        if not usuario:
            raise RequisicaoInvalida("Há uma conta sem usuário.")
        if usuario in vistos:
            raise RequisicaoInvalida(f"Conta repetida: {usuario}")
        vistos.add(usuario)
        senha = str(item.get("senha") or "") or salvas.get(usuario, {}).get("senha", "")
        if not senha:
            raise RequisicaoInvalida(f"Falta a senha de {usuario}.")
        contas.append({
            "usuario": usuario,
            "senha": senha,
            "nome": str(item.get("nome") or salvas.get(usuario, {}).get("nome") or ""),
            "respostas": validar_respostas(item.get("respostas") or {}),
        })
    return contas


def mesclar_contas(existentes: list[dict], novas: list[dict], padrao: dict) -> tuple[list[dict], int, int]:
    """Junta as contas importadas às salvas: mesmo usuário atualiza respostas/nome e
    mantém a senha salva; o que a importação não deduziu vem de `padrao`."""
    por_usuario = {c["usuario"]: c for c in existentes}
    adicionadas = atualizadas = 0
    for nova in novas:
        respostas = {**padrao, **nova["respostas"]}
        faltando = [p for p, _ in pesquisa.PERGUNTAS_PERFIL if not respostas.get(p)]
        if faltando:
            raise RequisicaoInvalida(
                f'Não consegui deduzir "{faltando[0]}" para {nova["usuario"]}; marque uma resposta padrão no formulário ou informe a turma.'
            )
        atual = por_usuario.get(nova["usuario"])
        if atual:
            atual["respostas"] = respostas
            atual["nome"] = nova.get("nome") or atual.get("nome", "")
            atualizadas += 1
        else:
            por_usuario[nova["usuario"]] = {"usuario": nova["usuario"], "senha": nova["senha"], "nome": nova.get("nome", ""), "respostas": respostas}
            adicionadas += 1
    return list(por_usuario.values()), adicionadas, atualizadas


def cliente_san2(dados: dict) -> tuple[san2.San2, str]:
    """Valida/salva as credenciais do SAN2 e a senha padrão; devolve (cliente logado, senha padrão)."""
    usuario = str(dados.get("san2_usuario") or "").strip()
    if not usuario:
        raise RequisicaoInvalida("Informe o usuário do SAN2.")
    config = pesquisa.carregar_config(pesquisa.CONFIG_PADRAO) or {}
    senha = str(dados.get("san2_senha") or "") or config.get("san2_senha") or ""
    if not senha:
        raise RequisicaoInvalida("Informe a senha do SAN2.")
    senha_padrao = str(dados.get("senha_padrao") or "").strip() or str(config.get("senha_padrao") or "")
    if not senha_padrao:
        raise RequisicaoInvalida("Informe a senha padrão dos frequentadores.")

    config["san2_usuario"] = usuario
    config["senha_padrao"] = senha_padrao
    if dados.get("guardar_san2"):
        config["san2_senha"] = senha
    else:
        config.pop("san2_senha", None)
    pesquisa.salvar_config(pesquisa.CONFIG_PADRAO, config)

    try:
        return SESSAO_SAN2.cliente(usuario, senha), senha_padrao
    except san2.ErroSan2 as e:
        raise RequisicaoInvalida(str(e)) from None


def guardar_importacao(dados: dict, resultado: dict) -> dict:
    """Mescla as contas importadas na lista e monta a resposta para a página."""
    padrao = {p: r for p, r in (dados.get("respostas_padrao") or {}).items() if r}
    contas, adicionadas, atualizadas = mesclar_contas(carregar_contas(), resultado["contas"], padrao)
    salvar_contas(contas)
    return {
        "ok": True,
        "turma": resultado.get("turma"),
        "adicionadas": adicionadas,
        "atualizadas": atualizadas,
        "contas": contas_publicas(),
    }


def importar_do_san2(dados: dict) -> dict:
    """Importação de uma turma inteira ou de um frequentador."""
    termo = str(dados.get("termo") or "").strip()
    if not termo:
        raise RequisicaoInvalida("Informe o código da turma ou o login/nome do frequentador.")
    modo = dados.get("modo") or "turma"
    if modo not in ("turma", "frequentador"):
        raise RequisicaoInvalida("Modo inválido.")
    cliente, senha_padrao = cliente_san2(dados)
    try:
        importar = san2.importar_turma if modo == "turma" else san2.importar_frequentador
        resultado = importar(cliente, termo, senha_padrao)
    except san2.ErroSan2 as e:
        raise RequisicaoInvalida(str(e)) from None
    return guardar_importacao(dados, resultado)


LIMITE_PLANILHA = 5 * 1024 * 1024


def importar_planilha(dados: dict) -> dict:
    """Planilha (.xlsx/.csv em base64) com nome/login/CPF dos alunos: localiza cada um no SAN."""
    nome_arquivo = str(dados.get("arquivo_nome") or "planilha.xlsx")
    try:
        conteudo = base64.b64decode(str(dados.get("arquivo_b64") or ""), validate=True)
    except ValueError:
        raise RequisicaoInvalida("Arquivo inválido.") from None
    if not conteudo:
        raise RequisicaoInvalida("Escolha a planilha (.xlsx ou .csv).")
    if len(conteudo) > LIMITE_PLANILHA:
        raise RequisicaoInvalida("A planilha é grande demais (limite de 5 MB).")
    try:
        linhas, _ = planilha.ler_planilha(nome_arquivo, conteudo)
    except planilha.ErroPlanilha as e:
        raise RequisicaoInvalida(str(e)) from None

    cliente, senha_padrao = cliente_san2(dados)
    turma = str(dados.get("turma") or "").strip() or None
    try:
        resultado = san2.importar_planilha(cliente, linhas, turma, senha_padrao)
    except san2.ErroSan2 as e:
        raise RequisicaoInvalida(str(e)) from None

    resposta = guardar_importacao(dados, resultado)
    relatorio = resultado["relatorio"]
    resposta["relatorio"] = relatorio
    resposta["resumo"] = {
        "linhas": len(relatorio),
        "encontrados": sum(1 for r in relatorio if r["status"] == "ok"),
        "ambiguos": sum(1 for r in relatorio if r["status"] == "ambiguo"),
        "nao_encontrados": sum(1 for r in relatorio if r["status"] == "nao_encontrado"),
    }
    return resposta


def validar_pedido(dados: dict) -> tuple[dict, str, bool, bool]:
    """Valida o JSON do botão Executar; devolve (config, senha, enviar, headless)."""
    usuario = str(dados.get("usuario") or "").strip()
    if not usuario:
        raise RequisicaoInvalida("Informe o usuário.")
    respostas = validar_respostas(dados.get("respostas") or {})
    resposta_padrao = str(dados.get("resposta_padrao") or "").strip()
    if not resposta_padrao:
        raise RequisicaoInvalida("Escolha a resposta para as demais perguntas.")

    config = pesquisa.carregar_config(pesquisa.CONFIG_PADRAO) or {}
    senha = str(dados.get("senha") or "") or config.get("senha") or ""
    if not senha:
        raise RequisicaoInvalida("Informe a senha.")

    config["usuario"] = usuario
    config["resposta_padrao"] = resposta_padrao
    config.setdefault("respostas", {}).update(respostas)
    if dados.get("guardar_senha"):
        config["senha"] = senha
    else:
        config.pop("senha", None)
    pesquisa.salvar_config(pesquisa.CONFIG_PADRAO, config)

    return config, senha, bool(dados.get("enviar", True)), bool(dados.get("headless", False))


def montar_lote(dados: dict) -> tuple[list[dict], bool, bool]:
    """Prepara a lista salva para execução: cada conta vira um config próprio."""
    contas = carregar_contas()
    if not contas:
        raise RequisicaoInvalida("A lista de contas está vazia.")
    resposta_padrao = str(dados.get("resposta_padrao") or "").strip() or pesquisa.RESPOSTA_PADRAO
    base = pesquisa.carregar_config(pesquisa.CONFIG_PADRAO) or {}
    base.pop("senha", None)
    lote = []
    for conta in contas:
        config = dict(base)
        config["usuario"] = conta["usuario"]
        config["resposta_padrao"] = resposta_padrao
        config["respostas"] = {**(base.get("respostas") or {}), **conta["respostas"]}
        lote.append({"usuario": conta["usuario"], "senha": conta["senha"], "config": config})
    return lote, bool(dados.get("enviar", True)), bool(dados.get("headless", False))


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


class Manipulador(BaseHTTPRequestHandler):
    def log_message(self, formato, *args):  # silencia o log de cada requisição
        pass

    def do_GET(self) -> None:
        rota = urlparse(self.path)
        if rota.path == "/":
            self._arquivo(PAGINA, "text/html; charset=utf-8")
        elif rota.path == "/api/config":
            self._json(config_publica())
        elif rota.path == "/api/estado":
            desde = int(parse_qs(rota.query).get("desde", ["0"])[0] or 0)
            self._json(EXECUCAO.snapshot(desde))
        elif rota.path == "/erro.png":
            self._arquivo(pesquisa.CAPTURA_ERRO, "image/png")
        elif rota.path.startswith("/capturas/"):
            nome = Path(rota.path).name  # só o nome: nada de subir de pasta
            self._arquivo(CAPTURAS / nome, "image/png")
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        rota = urlparse(self.path)
        try:
            if rota.path == "/api/executar":
                config, senha, enviar, headless = validar_pedido(self._ler_json())
                if not EXECUCAO.iniciar(config, senha, enviar, headless):
                    raise RequisicaoInvalida("Já existe uma execução em andamento.", HTTPStatus.CONFLICT)
                self._json({"ok": True})
            elif rota.path == "/api/executar-lote":
                lote, enviar, headless = montar_lote(self._ler_json())
                if not EXECUCAO.iniciar_lote(lote, enviar, headless):
                    raise RequisicaoInvalida("Já existe uma execução em andamento.", HTTPStatus.CONFLICT)
                self._json({"ok": True, "contas": len(lote)})
            elif rota.path == "/api/contas":
                contas = validar_contas(self._ler_json())
                salvar_contas(contas)
                self._json({"ok": True, "contas": len(contas)})
            elif rota.path == "/api/san2/importar":
                self._json(importar_do_san2(self._ler_json()))
            elif rota.path == "/api/san2/planilha":
                self._json(importar_planilha(self._ler_json()))
            elif rota.path == "/api/fechar":
                EXECUCAO.pedir_fechamento()
                self._json({"ok": True})
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except RequisicaoInvalida as e:
            status = e.args[1] if len(e.args) > 1 else HTTPStatus.BAD_REQUEST
            self._json({"erro": e.args[0]}, status)

    def _ler_json(self) -> dict:
        tamanho = int(self.headers.get("Content-Length") or 0)
        try:
            dados = json.loads(self.rfile.read(tamanho) or b"{}")
        except ValueError:
            raise RequisicaoInvalida("JSON inválido.") from None
        if not isinstance(dados, dict):
            raise RequisicaoInvalida("JSON inválido.")
        return dados

    def _json(self, dados: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def _arquivo(self, caminho: Path, tipo: str) -> None:
        if not caminho.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        corpo = caminho.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)


def criar_servidor(porta: int) -> ThreadingHTTPServer:
    servidor = ThreadingHTTPServer(("127.0.0.1", porta), Manipulador)
    servidor.daemon_threads = True
    return servidor


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Interface web local da automação de pesquisas.")
    parser.add_argument("--porta", type=int, default=8765)
    parser.add_argument("--sem-abrir", action="store_true", help="não abre o navegador automaticamente")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    log.addHandler(ManipuladorLog(EXECUCAO))

    servidor = criar_servidor(args.porta)
    endereco = f"http://127.0.0.1:{args.porta}/"
    print(f"Interface disponível em {endereco}")
    print("Feche esta janela (ou Ctrl+C) para encerrar o servidor.", flush=True)
    if not args.sem_abrir:
        webbrowser.open(endereco)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrado.")
    finally:
        servidor.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
