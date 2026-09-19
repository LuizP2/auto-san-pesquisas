#!/usr/bin/env python3
"""Monitor de rede: abre o navegador e registra toda requisição que o site faz.

    python3 monitor.py [--url https://...] [--tudo]

Enquanto você navega, o terminal mostra método, status, URL, o corpo enviado
(senhas mascaradas) e uma prévia da resposta. Tudo vai completo para
monitor/<data-hora>/requisicoes.jsonl, e ao fechar o navegador sai um resumo
dos endpoints (também salvo em endpoints.txt). O perfil do navegador fica em
monitor/perfil, então o login persiste entre sessões.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import pesquisa  # garante o .venv com o Playwright

PASTA_MONITOR = pesquisa.PASTA / "monitor"
URL_PADRAO = "https://pesquisas.navedoconhecimento.rio/"
TIPOS_INTERESSANTES = {"xhr", "fetch", "document", "websocket", "other"}
EXTENSOES_ESTATICAS = re.compile(r"\.(js|mjs|css|map|png|jpe?g|gif|svg|webp|ico|woff2?|ttf|eot|mp4|webm)(\?|$)", re.I)
LIMITE_CORPO_ARQUIVO = 500_000  # bytes de resposta guardados por requisição
CAMPOS_SECRETOS = re.compile(r"(senha|password|passwd|pwd|secret|client_secret)", re.I)

CORES = {
    "cinza": "\033[90m", "verde": "\033[32m", "amarelo": "\033[33m", "vermelho": "\033[31m",
    "ciano": "\033[36m", "laranja": "\033[38;5;215m", "negrito": "\033[1m", "fim": "\033[0m",
}


def cor(nome: str, texto: str) -> str:
    if not sys.stdout.isatty():
        return texto
    return f"{CORES[nome]}{texto}{CORES['fim']}"


# ---------------------------------------------------------------------------
# Tratamento dos dados
# ---------------------------------------------------------------------------


def mascarar(valor):
    """Troca valores de campos com nome de senha por *** (recursivo em dicts/listas)."""
    if isinstance(valor, dict):
        return {k: ("***" if CAMPOS_SECRETOS.search(str(k)) else mascarar(v)) for k, v in valor.items()}
    if isinstance(valor, list):
        return [mascarar(v) for v in valor]
    return valor


def interpretar_corpo(texto: str | None, tipo: str | None):
    """Devolve (dados, formato): JSON -> objeto; form -> dict; senão texto puro."""
    if not texto:
        return None, None
    tipo = (tipo or "").lower()
    if "json" in tipo or texto.lstrip()[:1] in "{[":
        try:
            return json.loads(texto), "json"
        except ValueError:
            pass
    if "x-www-form-urlencoded" in tipo or ("=" in texto and "\n" not in texto and " " not in texto.strip()):
        return dict(parse_qsl(texto, keep_blank_values=True)), "form"
    return texto, "texto"


def encurtar_token(cabecalhos: dict) -> dict:
    """Mantém os cabeçalhos, mas corta tokens longos (Authorization, cookies)."""
    saida = {}
    for k, v in cabecalhos.items():
        if k.lower() in ("authorization", "cookie", "set-cookie") and len(v) > 40:
            saida[k] = v[:28] + f"…({len(v)} chars)"
        else:
            saida[k] = v
    return saida


def texto_corpo(dados, formato, limite: int) -> str:
    if dados is None:
        return ""
    if formato == "json":
        s = json.dumps(dados, ensure_ascii=False, separators=(",", ":"))
    elif formato == "form":
        s = "&".join(f"{k}={v}" for k, v in dados.items())
    else:
        s = str(dados).replace("\n", "⏎")
    return s if len(s) <= limite else s[:limite] + f"… (+{len(s) - limite} chars)"


def padrao_endpoint(url: str) -> str:
    """Agrupa URLs parecidas: números e UUIDs no caminho viram {id}; query fica só com as chaves."""
    partes = urlsplit(url)
    caminho = re.sub(r"/[0-9a-f]{8}-[0-9a-f-]{27,}", "/{uuid}", partes.path)
    caminho = re.sub(r"/\d+(?=/|$)", "/{id}", caminho)
    chaves = sorted({k for k, _ in parse_qsl(partes.query, keep_blank_values=True)})
    return f"{partes.scheme}://{partes.netloc}{caminho}" + (f"?{','.join(chaves)}" if chaves else "")


# ---------------------------------------------------------------------------
# Monitor
# ---------------------------------------------------------------------------


class Monitor:
    def __init__(self, pasta: Path, tudo: bool = False, previa: int = 400) -> None:
        self.pasta = pasta
        self.tudo = tudo
        self.previa = previa
        self.pasta.mkdir(parents=True, exist_ok=True)
        self.arquivo = open(self.pasta / "requisicoes.jsonl", "a", encoding="utf-8")
        self.endpoints: dict[str, int] = {}
        self.total = 0

    def instalar(self, contexto) -> None:
        contexto.on("requestfinished", self._terminada)
        contexto.on("requestfailed", self._falhou)

    def fechar(self) -> None:
        self.arquivo.close()

    # -- eventos -------------------------------------------------------------

    def _relevante(self, requisicao) -> bool:
        if self.tudo:
            return True
        # "other" cobre prefetch de JS/CSS (ruído) e também beacons/downloads (interessantes)
        return requisicao.resource_type in TIPOS_INTERESSANTES and not EXTENSOES_ESTATICAS.search(requisicao.url)

    def _terminada(self, requisicao) -> None:
        if not self._relevante(requisicao):
            return
        resposta = requisicao.response()
        corpo_resposta, formato_resposta, tamanho = None, None, 0
        if resposta is not None:
            tipo = resposta.headers.get("content-type", "")
            if any(t in tipo for t in ("json", "text", "xml", "javascript", "x-www-form")) or not tipo:
                try:
                    bruto = resposta.body()
                    tamanho = len(bruto)
                    corpo_resposta, formato_resposta = interpretar_corpo(
                        bruto[:LIMITE_CORPO_ARQUIVO].decode("utf-8", "replace"), tipo
                    )
                except pesquisa.ErroPlaywright:
                    pass
        self._registrar(requisicao, resposta, corpo_resposta, formato_resposta, tamanho, erro=None)

    def _falhou(self, requisicao) -> None:
        if self._relevante(requisicao):
            self._registrar(requisicao, None, None, None, 0, erro=requisicao.failure or "falhou")

    # -- registro ------------------------------------------------------------

    def _registrar(self, requisicao, resposta, corpo_resposta, formato_resposta, tamanho, erro) -> None:
        agora = datetime.now()
        dados_envio, formato_envio = interpretar_corpo(
            requisicao.post_data, requisicao.headers.get("content-type")
        )
        dados_envio = mascarar(dados_envio)
        chave = f"{requisicao.method} {padrao_endpoint(requisicao.url)}"
        self.endpoints[chave] = self.endpoints.get(chave, 0) + 1
        self.total += 1

        registro = {
            "n": self.total,
            "hora": agora.isoformat(timespec="milliseconds"),
            "metodo": requisicao.method,
            "url": requisicao.url,
            "tipo": requisicao.resource_type,
            "cabecalhos": encurtar_token(requisicao.headers),
            "envio": dados_envio,
            "status": resposta.status if resposta else None,
            "cabecalhos_resposta": encurtar_token(resposta.headers) if resposta else None,
            "resposta": corpo_resposta,
            "tamanho_resposta": tamanho,
            "erro": erro,
        }
        self.arquivo.write(json.dumps(registro, ensure_ascii=False) + "\n")
        self.arquivo.flush()
        self._imprimir(registro, dados_envio, formato_envio, corpo_resposta, formato_resposta)

    def _imprimir(self, r, dados_envio, formato_envio, corpo_resposta, formato_resposta) -> None:
        hora = r["hora"][11:19]
        metodo = r["metodo"]
        cor_metodo = "verde" if metodo == "GET" else "laranja"
        if r["erro"]:
            status = cor("vermelho", "FALHOU")
        else:
            s = r["status"]
            status = cor("verde" if s < 300 else "amarelo" if s < 400 else "vermelho", str(s))
        print(f"{cor('cinza', hora)}  {cor(cor_metodo, f'{metodo:<6}')} {status}  {cor('negrito', r['url'])}  {cor('cinza', '[' + r['tipo'] + ']')}")

        recuo = " " * 10
        autorizacao = r["cabecalhos"].get("authorization")
        if autorizacao:
            print(f"{recuo}{cor('cinza', 'auth: ' + autorizacao)}")
        if dados_envio is not None:
            print(f"{recuo}{cor('laranja', '→ ')}{texto_corpo(dados_envio, formato_envio, self.previa)}")
        if r["erro"]:
            print(f"{recuo}{cor('vermelho', '✗ ' + str(r['erro']))}")
        elif r["tipo"] == "document":
            print(f"{recuo}{cor('cinza', f'← (página HTML, {r["tamanho_resposta"]} bytes)')}")
        elif corpo_resposta is not None:
            print(f"{recuo}{cor('ciano', '← ')}{texto_corpo(corpo_resposta, formato_resposta, self.previa)}")
        elif r["tamanho_resposta"]:
            print(f"{recuo}{cor('cinza', f'← ({r['tamanho_resposta']} bytes, binário)')}")
        sys.stdout.flush()

    # -- resumo --------------------------------------------------------------

    def resumo(self) -> str:
        linhas = [f"{n:>4}×  {chave}" for chave, n in sorted(self.endpoints.items(), key=lambda i: (-i[1], i[0]))]
        texto = f"{self.total} requisição(ões), {len(self.endpoints)} endpoint(s) distintos:\n" + "\n".join(linhas)
        (self.pasta / "endpoints.txt").write_text(texto + "\n", encoding="utf-8")
        return texto


# ---------------------------------------------------------------------------
# Linha de comando
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Registra as requisições do site enquanto você navega.")
    parser.add_argument("--url", default=URL_PADRAO, help="página inicial")
    parser.add_argument("--tudo", action="store_true", help="inclui imagens, scripts, CSS etc.")
    parser.add_argument("--previa", type=int, default=400, help="tamanho da prévia dos corpos no terminal")
    args = parser.parse_args(argv)

    sessao = PASTA_MONITOR / datetime.now().strftime("%Y%m%d-%H%M%S")
    monitor = Monitor(sessao, tudo=args.tudo, previa=args.previa)
    print(cor("negrito", "Monitor de rede — navegue à vontade; feche o navegador (ou Ctrl+C) para encerrar."))
    print(f"Registro completo: {sessao / 'requisicoes.jsonl'}")
    print(cor("cinza", "Senhas são mascaradas; tokens aparecem cortados. Ainda assim, mantenha a pasta monitor/ só neste computador.\n"))

    with pesquisa.sync_playwright() as pw:
        contexto = pw.chromium.launch_persistent_context(
            str(PASTA_MONITOR / "perfil"), headless=False, channel="chromium", viewport=None,
            args=["--start-maximized"],
        )
        monitor.instalar(contexto)
        pagina = contexto.pages[0] if contexto.pages else contexto.new_page()
        try:
            pagina.goto(args.url)
            contexto.wait_for_event("close", timeout=0)
        except KeyboardInterrupt:
            print("\nEncerrando…")
        except pesquisa.ErroPlaywright as e:
            if "closed" not in e.message.lower():
                print(cor("vermelho", f"Erro no navegador: {e.message.splitlines()[0]}"))
        finally:
            try:
                contexto.close()
            except pesquisa.ErroPlaywright:
                pass
            monitor.fechar()

    print("\n" + cor("negrito", "Resumo dos endpoints") + "\n" + monitor.resumo())
    print(f"\nArquivos em {sessao}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
