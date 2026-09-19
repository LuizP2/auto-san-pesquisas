#!/usr/bin/env python3
"""Lê uma planilha de alunos (.xlsx ou .csv) sem dependências externas.

Reconhece as colunas pelo cabeçalho (qualquer ordem, acentos/caixa ignorados):
  nome        -> "Nome", "Nome completo", "Aluno"...
  login       -> "Login", "Usuário", "Username"
  cpf         -> "CPF"
  nascimento  -> "Nascimento", "Data de nascimento"
Só "nome", "login" e "cpf" servem para localizar; "nascimento" desempata homônimos.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import date, timedelta
from xml.etree import ElementTree as ET

import pesquisa

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
COLUNAS = {  # campo -> palavras que identificam o cabeçalho (normalizadas)
    "login": ("login", "usuario", "username", "user"),
    "cpf": ("cpf",),
    "nascimento": ("nascimento", "data de nascimento", "dt nasc", "data nasc"),
    "nome": ("nome", "aluno", "frequentador", "estudante"),
}
CAMPOS_DE_BUSCA = ("nome", "login", "cpf")


class ErroPlanilha(Exception):
    pass


# ---------------------------------------------------------------------------
# xlsx
# ---------------------------------------------------------------------------


def _texto(elemento) -> str:
    return "".join(t.text or "" for t in elemento.iter(NS + "t"))


def _coluna(ref: str) -> int:
    letras = re.match(r"[A-Z]+", ref or "").group(0)
    n = 0
    for ch in letras:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _ler_xlsx(conteudo: bytes) -> list[list[str]]:
    try:
        z = zipfile.ZipFile(io.BytesIO(conteudo))
        planilhas = sorted(n for n in z.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n))
        if not planilhas:
            raise ErroPlanilha("O arquivo .xlsx não tem planilhas.")
        compartilhadas = []
        if "xl/sharedStrings.xml" in z.namelist():
            compartilhadas = [_texto(si) for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(NS + "si")]
        folha = ET.fromstring(z.read(planilhas[0]))
    except (zipfile.BadZipFile, ET.ParseError, KeyError) as e:
        raise ErroPlanilha(f"Não consegui ler o .xlsx ({e}). Se for um .xls antigo, salve como .xlsx.") from None

    linhas = []
    for linha in folha.iter(NS + "row"):
        celulas: list[str] = []
        for c in linha.findall(NS + "c"):
            tipo, v = c.get("t"), c.find(NS + "v")
            if tipo == "s" and v is not None:
                valor = compartilhadas[int(v.text)]
            elif tipo == "inlineStr":
                valor = _texto(c)
            elif v is not None:
                valor = v.text or ""
            else:
                valor = ""
            idx = _coluna(c.get("r", ""))
            while len(celulas) < idx:
                celulas.append("")
            celulas.append(valor.strip())
        linhas.append(celulas)
    return linhas


# ---------------------------------------------------------------------------
# csv
# ---------------------------------------------------------------------------


def _ler_csv(conteudo: bytes) -> list[list[str]]:
    for codificacao in ("utf-8-sig", "latin-1"):
        try:
            texto = conteudo.decode(codificacao)
            break
        except UnicodeDecodeError:
            continue
    amostra = texto[:4096]
    try:
        dialeto = csv.Sniffer().sniff(amostra, delimiters=";,\t")
    except csv.Error:
        dialeto = csv.excel
        dialeto.delimiter = ";" if amostra.count(";") >= amostra.count(",") else ","
    return [[c.strip() for c in linha] for linha in csv.reader(io.StringIO(texto), dialeto)]


# ---------------------------------------------------------------------------
# Interpretação das colunas
# ---------------------------------------------------------------------------


def _mapear_cabecalho(cabecalho: list[str]) -> dict[str, int]:
    """campo -> índice da coluna. Primeiro títulos iguais à chave, depois títulos que a contêm."""
    titulos = [pesquisa.normalizar(t) for t in cabecalho]
    mapa: dict[str, int] = {}

    def casa(titulo: str, chave: str, exato: bool) -> bool:
        if exato:
            return titulo == chave
        return chave in titulo if " " in chave else chave in titulo.split()

    for exato in (True, False):
        for campo, chaves in COLUNAS.items():
            if campo in mapa:
                continue
            for i, titulo in enumerate(titulos):
                if not titulo or i in mapa.values():
                    continue
                if campo == "nome" and any(x in titulo.split() for x in ("mae", "pai", "responsavel", "social")):
                    continue
                if any(casa(titulo, k, exato) for k in chaves):
                    mapa[campo] = i
                    break
    return mapa


def _limpar_cpf(valor: str) -> str:
    digitos = re.sub(r"\D", "", valor)
    if not digitos:
        return ""
    if "." in valor and "e" in valor.lower():  # notação científica do Excel (1.2833993773E10)
        try:
            digitos = str(int(float(valor)))
        except ValueError:
            pass
    return digitos.zfill(11) if len(digitos) <= 11 else digitos


def _limpar_data(valor: str) -> str:
    valor = valor.strip()
    if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}.*", valor):
        d, m, a = valor[:10].split("/")
        return f"{int(d):02d}/{int(m):02d}/{a}"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", valor):
        a, m, d = valor[:10].split("-")
        return f"{d}/{m}/{a}"
    if re.fullmatch(r"\d+(\.\d+)?", valor):  # número de série do Excel
        try:
            return (date(1899, 12, 30) + timedelta(days=int(float(valor)))).strftime("%d/%m/%Y")
        except (ValueError, OverflowError):
            return valor
    return valor


def ler_planilha(nome_arquivo: str, conteudo: bytes) -> tuple[list[dict], dict[str, int]]:
    """Devolve (linhas, mapa de colunas). Cada linha: {"n", "nome", "login", "cpf", "nascimento"}."""
    if not conteudo:
        raise ErroPlanilha("O arquivo está vazio.")
    extensao = nome_arquivo.rsplit(".", 1)[-1].lower() if "." in nome_arquivo else ""
    if extensao == "xlsx" or conteudo[:2] == b"PK":
        tabela = _ler_xlsx(conteudo)
    elif extensao in ("csv", "txt", ""):
        tabela = _ler_csv(conteudo)
    elif extensao == "xls":
        raise ErroPlanilha("Formato .xls antigo não é suportado: abra no Excel e salve como .xlsx.")
    else:
        raise ErroPlanilha(f"Formato .{extensao} não é suportado: use .xlsx ou .csv.")

    # cabeçalho = primeira linha em que alguma coluna conhecida aparece
    inicio, mapa = None, {}
    for i, linha in enumerate(tabela[:20]):
        m = _mapear_cabecalho(linha)
        if any(c in m for c in CAMPOS_DE_BUSCA):
            inicio, mapa = i, m
            break
    if inicio is None:
        vistos = ", ".join(c for c in (tabela[0] if tabela else []) if c) or "(nenhum)"
        raise ErroPlanilha(
            "Não achei uma coluna de Nome, Login ou CPF na planilha. "
            f"Cabeçalhos encontrados na primeira linha: {vistos}."
        )

    linhas = []
    for n, celulas in enumerate(tabela[inicio + 1:], start=inicio + 2):
        def campo(nome):
            i = mapa.get(nome)
            return celulas[i] if i is not None and i < len(celulas) else ""
        registro = {
            "n": n,
            "nome": " ".join(campo("nome").split()),
            "login": campo("login").strip(),
            "cpf": _limpar_cpf(campo("cpf")),
            "nascimento": _limpar_data(campo("nascimento")),
        }
        if any(registro[c] for c in CAMPOS_DE_BUSCA):
            linhas.append(registro)
    if not linhas:
        raise ErroPlanilha("A planilha não tem nenhuma linha de aluno preenchida.")
    return linhas, mapa
