"""Testa o monitor de rede com o frontend real do site e a API simulada.

Rodar:  .venv/bin/python -m unittest testes/teste_monitor.py -v
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
import monitor  # noqa: E402
from teste_mock import USUARIO, SENHA, ApiFalsa, montar_turma  # noqa: E402


class TesteMonitor(unittest.TestCase):
    def test_captura_login_e_mascara_senha(self):
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        api = ApiFalsa([montar_turma(1, "PDM.X.1", "Curso Teste")])
        m = monitor.Monitor(Path(pasta.name), previa=80)

        with sync_playwright() as pw:
            navegador = pw.chromium.launch(headless=True)
            contexto = navegador.new_context()
            contexto.route("https://api.navedoconhecimento.rio/**", api.tratar)
            m.instalar(contexto)
            pagina = contexto.new_page()
            pagina.goto(monitor.URL_PADRAO)
            pagina.locator("input[type=text]").first.fill(USUARIO)
            pagina.locator("input[type=password]").first.fill(SENHA)
            pagina.get_by_role("button", name="Entrar").click()
            pagina.wait_for_url("**/satisfaction-survey")
            pagina.wait_for_selector(".survey-box input[type=radio]")
            contexto.close()
            navegador.close()
        m.fechar()

        registros = [json.loads(l) for l in (Path(pasta.name) / "requisicoes.jsonl").read_text(encoding="utf-8").splitlines()]
        por_url = {r["url"].split("?")[0]: r for r in registros}

        token = por_url["https://api.navedoconhecimento.rio/oauth2/token"]
        self.assertEqual(token["metodo"], "POST")
        self.assertEqual(token["status"], 200)
        self.assertEqual(token["envio"]["username"], USUARIO)
        self.assertEqual(token["envio"]["password"], "***")
        self.assertEqual(token["envio"]["client_secret"], "***")
        self.assertEqual(token["resposta"]["token_type"], "Bearer")
        self.assertNotIn(SENHA, json.dumps(registros))

        info = por_url["https://api.navedoconhecimento.rio/user/me/info"]
        self.assertTrue(info["cabecalhos"]["authorization"].startswith("Bearer "))
        self.assertEqual(info["resposta"]["user"]["name"], "Aluno Teste")

        pesquisa_req = por_url["https://api.navedoconhecimento.rio/user/me/satisfaction-survey-to-answer"]
        self.assertEqual(pesquisa_req["resposta"]["group"]["code"], "PDM.X.1")

        # a página inicial (document) também é registrada; imagens/JS não
        self.assertIn("https://pesquisas.navedoconhecimento.rio/", por_url)
        self.assertFalse(any(r["tipo"] in ("script", "image", "stylesheet") for r in registros))

        resumo = m.resumo()
        self.assertIn("POST https://api.navedoconhecimento.rio/oauth2/token?language", resumo)
        self.assertIn("GET https://api.navedoconhecimento.rio/user/me/info?language", resumo)
        self.assertTrue((Path(pasta.name) / "endpoints.txt").exists())


class TesteFuncoes(unittest.TestCase):
    def test_padrao_endpoint_agrupa_ids(self):
        self.assertEqual(
            monitor.padrao_endpoint("https://api.x/user/123/groups/45?page=2&language=pt"),
            "https://api.x/user/{id}/groups/{id}?language,page",
        )
        self.assertEqual(
            monitor.padrao_endpoint("https://api.x/item/3fa85f64-5717-4562-b3fc-2c963f66afa6"),
            "https://api.x/item/{uuid}",
        )

    def test_mascarar_e_interpretar(self):
        dados, formato = monitor.interpretar_corpo("a=1&senha=abc&password=x", "application/x-www-form-urlencoded")
        self.assertEqual(formato, "form")
        self.assertEqual(monitor.mascarar(dados), {"a": "1", "senha": "***", "password": "***"})
        dados, formato = monitor.interpretar_corpo('{"user":{"Senha":"1","nome":"n"}}', "application/json")
        self.assertEqual(formato, "json")
        self.assertEqual(monitor.mascarar(dados), {"user": {"Senha": "***", "nome": "n"}})
        self.assertEqual(monitor.interpretar_corpo("", None), (None, None))

    def test_texto_corpo_corta(self):
        self.assertEqual(monitor.texto_corpo({"a": "x" * 50}, "json", 20), '{"a":"xxxxxxxxxxxxxx… (+38 chars)')


if __name__ == "__main__":
    unittest.main()
