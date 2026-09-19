"""Testa o leitor de planilhas (.xlsx/.csv) sem dependências.

Rodar:  .venv/bin/python -m unittest testes/teste_planilha.py -v
"""

from __future__ import annotations

import io
import sys
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import planilha  # noqa: E402

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def xlsx(tabela: list[list], compartilhadas: bool = True) -> bytes:
    """Gera um .xlsx mínimo. Strings viram sharedStrings (ou inlineStr); números ficam como <v>."""
    sst, idx, linhas = [], {}, []
    for r, linha in enumerate(tabela, 1):
        celulas = []
        for i, v in enumerate(linha):
            if v == "" or v is None:
                continue
            ref = f"{chr(65 + i)}{r}"
            if isinstance(v, (int, float)):
                celulas.append(f'<c r="{ref}"><v>{v}</v></c>')
            elif compartilhadas:
                idx.setdefault(v, len(sst)) == len(sst) and sst.append(v)
                celulas.append(f'<c r="{ref}" t="s"><v>{idx[v]}</v></c>')
            else:
                celulas.append(f'<c r="{ref}" t="inlineStr"><is><t>{v}</t></is></c>')
        linhas.append(f'<row r="{r}">{"".join(celulas)}</row>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", "<workbook/>")
        if compartilhadas:
            z.writestr("xl/sharedStrings.xml", f'<sst xmlns="{NS}">' + "".join(f"<si><t>{v}</t></si>" for v in sst) + "</sst>")
        z.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{NS}"><sheetData>{"".join(linhas)}</sheetData></worksheet>')
    return buf.getvalue()


class TesteLeitor(unittest.TestCase):
    def test_xlsx_com_shared_strings(self):
        conteudo = xlsx([
            ["Nome", "Login", "CPF", "Data de Nascimento"],
            ["Ana  Maria", "ana.m", 12833993773, "14/05/1989"],
            ["", "", 1234567890, ""],  # CPF que perdeu o zero à esquerda no Excel
            ["", "", "", ""],          # linha vazia: ignorada
        ])
        linhas, mapa = planilha.ler_planilha("alunos.xlsx", conteudo)
        self.assertEqual(mapa, {"login": 1, "cpf": 2, "nascimento": 3, "nome": 0})
        self.assertEqual(linhas, [
            {"n": 2, "nome": "Ana Maria", "login": "ana.m", "cpf": "12833993773", "nascimento": "14/05/1989"},
            {"n": 3, "nome": "", "login": "", "cpf": "01234567890", "nascimento": ""},
        ])

    def test_xlsx_inline_strings_como_o_export_do_san2(self):
        conteudo = xlsx([
            ["Data da Inscrição", "Nome", "Nascimento", "Login", "Telefones", "Gênero"],
            ["19/08/2026 14:58:28", "WALLACE GROSSI", "14/05/1989", "wallacegrossi", "(21) 9", "Masculino"],
        ], compartilhadas=False)
        linhas, mapa = planilha.ler_planilha("san2-PDM.X.xlsx", conteudo)
        self.assertEqual(mapa, {"login": 3, "nascimento": 2, "nome": 1})
        self.assertEqual(linhas[0]["login"], "wallacegrossi")
        self.assertEqual(linhas[0]["nascimento"], "14/05/1989")

    def test_cabecalho_fora_da_primeira_linha_e_titulos_variados(self):
        conteudo = xlsx([
            ["Lista da turma 3º ano"],
            [],
            ["Nome da mãe", "NOME DO ALUNO", "CPF do aluno", "Usuário", "Dt Nasc"],
            ["Maria", "João da Silva", "123.456.789-01", "joao", 32642],  # data como número de série do Excel
        ])
        linhas, mapa = planilha.ler_planilha("lista.xlsx", conteudo)
        self.assertEqual(mapa, {"login": 3, "nascimento": 4, "cpf": 2, "nome": 1})
        self.assertEqual(linhas, [{"n": 4, "nome": "João da Silva", "login": "joao", "cpf": "12345678901", "nascimento": "14/05/1989"}])

    def test_cpf_em_notacao_cientifica_e_data_iso(self):
        conteudo = xlsx([["nome", "cpf", "nascimento"], ["X", "1.2833993773E10", "1989-05-14"]])
        linhas, _ = planilha.ler_planilha("a.xlsx", conteudo)
        self.assertEqual((linhas[0]["cpf"], linhas[0]["nascimento"]), ("12833993773", "14/05/1989"))

    def test_csv_ponto_e_virgula_latin1(self):
        conteudo = "Nome;CPF\r\nJosé Ção;123\r\nAna;\r\n".encode("latin-1")
        linhas, mapa = planilha.ler_planilha("alunos.csv", conteudo)
        self.assertEqual(mapa, {"cpf": 1, "nome": 0})
        self.assertEqual([l["nome"] for l in linhas], ["José Ção", "Ana"])
        self.assertEqual(linhas[0]["cpf"], "00000000123")

    def test_csv_virgula_utf8_com_bom(self):
        conteudo = "﻿Login,Nome\nab,Zé\n".encode("utf-8")
        linhas, _ = planilha.ler_planilha("x.csv", conteudo)
        self.assertEqual(linhas, [{"n": 2, "nome": "Zé", "login": "ab", "cpf": "", "nascimento": ""}])

    def test_erros(self):
        with self.assertRaises(planilha.ErroPlanilha):
            planilha.ler_planilha("a.xlsx", b"")
        with self.assertRaises(planilha.ErroPlanilha):
            planilha.ler_planilha("a.xls", b"\xd0\xcf\x11\xe0")
        with self.assertRaises(planilha.ErroPlanilha):
            planilha.ler_planilha("a.pdf", b"%PDF")
        with self.assertRaises(planilha.ErroPlanilha):
            planilha.ler_planilha("a.xlsx", b"PK\x03\x04lixo")
        with self.assertRaises(planilha.ErroPlanilha) as ctx:
            planilha.ler_planilha("a.xlsx", xlsx([["Telefone", "E-mail"], ["1", "a@b"]]))
        self.assertIn("Telefone, E-mail", str(ctx.exception))
        with self.assertRaises(planilha.ErroPlanilha):
            planilha.ler_planilha("a.xlsx", xlsx([["Nome"], [""]]))


if __name__ == "__main__":
    unittest.main()
