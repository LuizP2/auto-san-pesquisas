"""Testa a interface web (servidor.py) com a automação simulada.

Rodar:  .venv/bin/python -m unittest testes/teste_servidor.py -v
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pesquisa  # noqa: E402
import san2  # noqa: E402
import servidor  # noqa: E402

RESPOSTAS = {
    "Sexo": "Feminino",
    "É aluno da rede municipal de ensino?": "Sim",
    "Em que período você frequenta a Nave do Conhecimento?": "Noite",
    "Qual a sua faixa etária?": "18 a 60 anos",
    "Qual atividade você realizou?": "Oficina",
}


class NavegadorFalso:
    """Substitui sync_playwright(): nada de navegador de verdade."""

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    @property
    def chromium(self):
        return self

    def launch(self, headless, **opcoes):
        return self

    def new_context(self):
        return self

    def new_page(self):
        pagina = mock.Mock(name="pagina")
        pagina.screenshot.side_effect = lambda path, **k: Path(path).write_bytes(b"png")
        return pagina

    def close(self):
        pass


class TesteServidor(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.TemporaryDirectory()
        self.addCleanup(self.pasta.cleanup)
        self.config = Path(self.pasta.name) / "config.json"
        self.captura = Path(self.pasta.name) / "erro.png"
        self.contas = Path(self.pasta.name) / "contas.json"
        self.capturas = Path(self.pasta.name) / "capturas"
        for modulo, alvo, valor in (
            (pesquisa, "CONFIG_PADRAO", self.config),
            (pesquisa, "CAPTURA_ERRO", self.captura),
            (pesquisa, "sync_playwright", NavegadorFalso),
            (servidor, "CONTAS", self.contas),
            (servidor, "CAPTURAS", self.capturas),
        ):
            p = mock.patch.object(modulo, alvo, valor)
            p.start()
            self.addCleanup(p.stop)

        servidor.EXECUCAO = servidor.Execucao()
        pesquisa.log.addHandler(servidor.ManipuladorLog(servidor.EXECUCAO))
        self.addCleanup(lambda: pesquisa.log.handlers.clear())
        pesquisa.log.setLevel("INFO")

        self.http = servidor.criar_servidor(0)
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.addCleanup(self.http.server_close)
        self.addCleanup(self.http.shutdown)
        self.base = f"http://127.0.0.1:{self.http.server_address[1]}"

    # -- utilitários --------------------------------------------------------

    def get(self, caminho):
        with urlopen(self.base + caminho) as r:
            return r.status, r.headers.get("Content-Type"), r.read()

    def post(self, caminho, dados=None):
        req = Request(
            self.base + caminho,
            data=json.dumps(dados or {}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(req) as r:
                return r.status, json.loads(r.read())
        except HTTPError as e:
            with e:
                corpo = e.read()
            return e.code, json.loads(corpo) if corpo.startswith(b"{") else corpo.decode()

    def esperar_estado(self, *estados, timeout=5):
        limite = time.monotonic() + timeout
        while time.monotonic() < limite:
            _, _, corpo = self.get("/api/estado")
            s = json.loads(corpo)
            if s["estado"] in estados:
                return s
            time.sleep(0.05)
        self.fail(f"estado {estados} não alcançado; último: {s}")

    def pedido(self, **extra):
        return {"usuario": "aluna", "senha": "1234", "respostas": RESPOSTAS,
                "resposta_padrao": "Muito Satisfeito", "enviar": True, "headless": True, **extra}

    # -- testes -------------------------------------------------------------

    def test_pagina_e_config_inicial(self):
        status, tipo, corpo = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", tipo)
        self.assertIn("Pesquisa de Satisfação", corpo.decode())

        _, _, corpo = self.get("/api/config")
        c = json.loads(corpo)
        self.assertEqual(c["usuario"], "")
        self.assertFalse(c["senha_salva"])
        self.assertEqual([p["texto"] for p in c["perguntas"]], [p for p, _ in pesquisa.PERGUNTAS_PERFIL])
        self.assertEqual(c["resposta_padrao"], "Muito Satisfeito")
        self.assertEqual(c["contas"], [])
        self.assertEqual(c["san2_usuario"], "")
        self.assertFalse(c["san2_senha_salva"])
        self.assertEqual(c["senha_padrao"], "")

    def test_validacao(self):
        self.assertEqual(self.post("/api/executar", self.pedido(usuario=""))[1]["erro"], "Informe o usuário.")
        self.assertIn("Responda: Sexo", self.post("/api/executar", self.pedido(respostas={}))[1]["erro"])
        self.assertEqual(self.post("/api/executar", self.pedido(senha=""))[1]["erro"], "Informe a senha.")
        self.assertFalse(self.config.exists())  # nada salvo enquanto o pedido é inválido

    def test_executa_salva_config_e_registra(self):
        def executar_falso(pagina, config, senha, enviar=True):
            pesquisa.log.info("Login OK (%s)", config["usuario"])
            pesquisa.log.info("  ✔ Sexo → %s", config["respostas"]["Sexo"])
            pesquisa.log.info("  ✅ Pesquisa respondida com sucesso!")
            return 1

        with mock.patch.object(pesquisa, "executar", executar_falso):
            status, corpo = self.post("/api/executar", self.pedido(guardar_senha=False))
            self.assertEqual((status, corpo), (200, {"ok": True}))
            s = self.esperar_estado("concluido")

        textos = [l["texto"] for l in s["linhas"]]
        self.assertEqual(textos, ["Login OK (aluna)", "  ✔ Sexo → Feminino", "  ✅ Pesquisa respondida com sucesso!"])
        self.assertFalse(s["captura"])

        salvo = json.loads(self.config.read_text(encoding="utf-8"))
        self.assertEqual(salvo["usuario"], "aluna")
        self.assertEqual(salvo["respostas"], RESPOSTAS)
        self.assertNotIn("senha", salvo)
        self.assertTrue(json.loads(self.get("/api/config")[2])["respostas"]["Sexo"] == "Feminino")

        # polling incremental: só devolve as linhas novas
        _, _, corpo = self.get("/api/estado?desde=2")
        self.assertEqual([l["n"] for l in json.loads(corpo)["linhas"]], [2])

    def test_senha_guardada_e_reutilizada(self):
        with mock.patch.object(pesquisa, "executar", lambda *a, **k: 0):
            self.post("/api/executar", self.pedido(guardar_senha=True))
            self.esperar_estado("concluido")
        self.assertEqual(json.loads(self.config.read_text())["senha"], "1234")
        self.assertTrue(json.loads(self.get("/api/config")[2])["senha_salva"])

        recebidas = []
        with mock.patch.object(pesquisa, "executar", lambda p, c, senha, **k: recebidas.append(senha)):
            status, _ = self.post("/api/executar", self.pedido(senha="", guardar_senha=True))
            self.assertEqual(status, 200)
            self.esperar_estado("concluido")
        self.assertEqual(recebidas, ["1234"])

    def test_erro_gera_captura_e_aguarda_navegador_visivel(self):
        def executar_falso(pagina, config, senha, enviar=True):
            raise pesquisa.ErroAutomacao("Login falhou: credenciais incorretas")

        with mock.patch.object(pesquisa, "executar", executar_falso):
            self.post("/api/executar", self.pedido(headless=False))
            s = self.esperar_estado("aguardando")
            self.assertTrue(s["captura"])
            self.assertEqual(self.get("/erro.png")[1], "image/png")
            self.assertIn("❌ Login falhou: credenciais incorretas", [l["texto"] for l in s["linhas"]])

            # enquanto aguarda, não aceita outra execução
            self.assertEqual(self.post("/api/executar", self.pedido())[0], 409)

            self.assertEqual(self.post("/api/fechar")[0], 200)
            s = self.esperar_estado("erro")
        self.assertEqual(s["estado"], "erro")

    def test_erro_sem_navegador_visivel_termina_direto(self):
        def executar_falso(*a, **k):
            raise pesquisa.ErroAutomacao("qualquer coisa")

        with mock.patch.object(pesquisa, "executar", executar_falso):
            self.post("/api/executar", self.pedido(headless=True))
            s = self.esperar_estado("erro")
        self.assertTrue(s["captura"])
        self.assertTrue(self.captura.exists())

    def test_sem_enviar_com_navegador_visivel_aguarda(self):
        with mock.patch.object(pesquisa, "executar", lambda *a, **k: 0):
            self.post("/api/executar", self.pedido(enviar=False, headless=False))
            s = self.esperar_estado("aguardando")
            self.assertIn("Fechar navegador", s["linhas"][-1]["texto"])
            self.post("/api/fechar")
            self.esperar_estado("concluido")

    def test_falha_inesperada_nao_derruba_servidor(self):
        def executar_falso(*a, **k):
            raise RuntimeError("bum")

        with mock.patch.object(pesquisa, "executar", executar_falso):
            self.post("/api/executar", self.pedido())
            s = self.esperar_estado("erro")
        self.assertTrue(any("Falha inesperada" in l["texto"] for l in s["linhas"]))
        self.assertEqual(self.get("/")[0], 200)

    # -- várias contas ------------------------------------------------------

    def contas_exemplo(self):
        return [
            {"usuario": "ana", "senha": "a1", "respostas": RESPOSTAS},
            {"usuario": "bia", "senha": "b2", "respostas": {**RESPOSTAS, "Sexo": "Masculino", "Qual a sua faixa etária?": "06 a 11 anos"}},
        ]

    def test_contas_salvar_validar_e_nao_expor_senha(self):
        status, corpo = self.post("/api/contas", {"contas": self.contas_exemplo()})
        self.assertEqual((status, corpo), (200, {"ok": True, "contas": 2}))
        salvo = json.loads(self.contas.read_text(encoding="utf-8"))["contas"]
        self.assertEqual([c["senha"] for c in salvo], ["a1", "b2"])

        publico = json.loads(self.get("/api/config")[2])["contas"]
        self.assertEqual([c["usuario"] for c in publico], ["ana", "bia"])
        self.assertEqual([c["senha"] for c in publico], ["", ""])

        # a página devolve a lista sem senhas; as salvas são mantidas
        status, _ = self.post("/api/contas", {"contas": publico})
        self.assertEqual(status, 200)
        self.assertEqual([c["senha"] for c in json.loads(self.contas.read_text())["contas"]], ["a1", "b2"])

        self.assertIn("Falta a senha de novo", self.post("/api/contas", {"contas": [{"usuario": "novo", "respostas": RESPOSTAS}]})[1]["erro"])
        self.assertIn("repetida", self.post("/api/contas", {"contas": self.contas_exemplo() + self.contas_exemplo()[:1]})[1]["erro"])
        self.assertIn("Responda: Sexo", self.post("/api/contas", {"contas": [{"usuario": "x", "senha": "1", "respostas": {}}]})[1]["erro"])
        self.assertIn("sem usuário", self.post("/api/contas", {"contas": [{"usuario": " ", "senha": "1", "respostas": RESPOSTAS}]})[1]["erro"])

    def test_lote_vazio(self):
        self.assertEqual(self.post("/api/executar-lote", {})[1]["erro"], "A lista de contas está vazia.")

    def test_lote_executa_cada_conta_com_seu_config(self):
        self.post("/api/contas", {"contas": self.contas_exemplo()})
        recebidos = []

        def executar_falso(pagina, config, senha, enviar=True):
            recebidos.append((config["usuario"], senha, config["respostas"]["Sexo"], config["resposta_padrao"], enviar))
            pesquisa.log.info("  ✅ Pesquisa respondida com sucesso!")
            return 1

        with mock.patch.object(pesquisa, "executar", executar_falso):
            status, corpo = self.post("/api/executar-lote", {"resposta_padrao": "Satisfeito", "enviar": False, "headless": True})
            self.assertEqual((status, corpo), (200, {"ok": True, "contas": 2}))
            s = self.esperar_estado("concluido")

        self.assertEqual(recebidos, [
            ("ana", "a1", "Feminino", "Satisfeito", False),
            ("bia", "b2", "Masculino", "Satisfeito", False),
        ])
        textos = [l["texto"] for l in s["linhas"]]
        self.assertEqual(textos[0], "Conta 1/2: ana")
        self.assertEqual(textos[2], "Conta 2/2: bia")
        self.assertEqual(textos[-1], "Resumo: 2 de 2 conta(s) OK.")

    def test_lote_continua_apos_falha_e_gera_captura_por_conta(self):
        self.post("/api/contas", {"contas": self.contas_exemplo()})

        def executar_falso(pagina, config, senha, enviar=True):
            if config["usuario"] == "ana":
                raise pesquisa.ErroAutomacao('A resposta "Muito Satisfeito" não existe na pergunta "X".')
            return 1

        with mock.patch.object(pesquisa, "executar", executar_falso):
            self.post("/api/executar-lote", {"headless": False})
            s = self.esperar_estado("erro")

        erro = next(l for l in s["linhas"] if l["nivel"] == "error" and "não existe" in l["texto"])
        self.assertEqual(erro["captura"], "01-ana.png")
        self.assertEqual(self.get("/capturas/01-ana.png")[1], "image/png")
        self.assertEqual(s["linhas"][-1]["texto"], "Resumo: 1 de 2 conta(s) OK. 1 com erro: ana.")
        self.assertFalse(s["captura"])  # a captura geral (erro.png) é só da conta única

    def test_lote_ignora_senha_diferente_da_padrao(self):
        self.post("/api/contas", {"contas": self.contas_exemplo()})

        def executar_falso(pagina, config, senha, enviar=True):
            if config["usuario"] == "ana":
                raise pesquisa.ErroAutomacao("Login falhou: As credenciais estão incorretas.")
            return 1

        with mock.patch.object(pesquisa, "executar", executar_falso):
            self.post("/api/executar-lote", {})
            s = self.esperar_estado("concluido")  # ignorar não é erro
        textos = [l["texto"] for l in s["linhas"]]
        self.assertIn("⏭ Ignorada — o site recusou o login (senha diferente da padrão?)", textos)
        self.assertEqual(textos[-1], "Resumo: 1 de 2 conta(s) OK. 1 ignorada(s) por senha diferente: ana.")
        self.assertFalse(any(l.get("captura") for l in s["linhas"]))

    # -- importação do SAN2 -------------------------------------------------

    def importacao_falsa(self, resultado):
        """Substitui o login/consulta do SAN2 por um resultado pronto."""
        sessao = mock.Mock()
        sessao.cliente.return_value = "cliente-falso"
        p1 = mock.patch.object(servidor, "SESSAO_SAN2", sessao)
        p2 = mock.patch.object(san2, "importar_turma", lambda cliente, termo, senha: resultado)
        p3 = mock.patch.object(san2, "importar_frequentador", lambda cliente, termo, senha: resultado)
        for p in (p1, p2, p3):
            p.start()
            self.addCleanup(p.stop)
        return sessao

    def test_importar_do_san2_valida_e_salva_credenciais(self):
        r = self.post("/api/san2/importar", {"termo": "PDM.X", "san2_senha": "s"})[1]
        self.assertEqual(r["erro"], "Informe o usuário do SAN2.")
        r = self.post("/api/san2/importar", {"san2_usuario": "staff", "san2_senha": "s"})[1]
        self.assertIn("código da turma", r["erro"])
        r = self.post("/api/san2/importar", {"san2_usuario": "staff", "termo": "PDM.X"})[1]
        self.assertEqual(r["erro"], "Informe a senha do SAN2.")
        r = self.post("/api/san2/importar", {"san2_usuario": "staff", "san2_senha": "s", "termo": "PDM.X"})[1]
        self.assertEqual(r["erro"], "Informe a senha padrão dos frequentadores.")

        sessao = self.importacao_falsa({"turma": None, "contas": []})
        status, r = self.post("/api/san2/importar", {
            "san2_usuario": "staff", "san2_senha": "segredo", "guardar_san2": True, "modo": "frequentador",
            "termo": "alguem", "senha_padrao": "654321",
        })
        self.assertEqual(status, 200)
        sessao.cliente.assert_called_once_with("staff", "segredo")
        salvo = json.loads(self.config.read_text(encoding="utf-8"))
        self.assertEqual((salvo["san2_usuario"], salvo["san2_senha"], salvo["senha_padrao"]), ("staff", "segredo", "654321"))
        publico = json.loads(self.get("/api/config")[2])
        self.assertTrue(publico["san2_senha_salva"])

        # senha em branco reaproveita a salva
        status, r = self.post("/api/san2/importar", {"san2_usuario": "staff", "termo": "x", "guardar_san2": False})
        self.assertEqual(status, 200)
        self.assertEqual(sessao.cliente.call_args.args, ("staff", "segredo"))
        self.assertNotIn("san2_senha", json.loads(self.config.read_text(encoding="utf-8")))

    def test_importar_do_san2_mescla_na_lista(self):
        self.post("/api/contas", {"contas": self.contas_exemplo()})  # ana, bia já existem
        self.importacao_falsa({
            "turma": {"id": 1, "codigo": "PDM.X.1", "curso": "Curso X", "carga_horaria": 3, "tem_pesquisa": True},
            "contas": [
                {"usuario": "ana", "senha": "senha-padrao-x", "nome": "ANA", "respostas": {**RESPOSTAS, "Sexo": "Masculino"}},
                {"usuario": "carlos", "senha": "senha-padrao-x", "nome": "CARLOS", "respostas": {"Sexo": "Masculino"}},  # resto vem do padrão
            ],
        })
        status, r = self.post("/api/san2/importar", {
            "san2_usuario": "staff", "san2_senha": "s", "termo": "PDM.X.1", "modo": "turma", "respostas_padrao": RESPOSTAS,
            "senha_padrao": "p",
        })
        self.assertEqual(status, 200)
        self.assertEqual((r["adicionadas"], r["atualizadas"]), (1, 1))
        self.assertEqual(r["turma"]["codigo"], "PDM.X.1")
        self.assertEqual([c["usuario"] for c in r["contas"]], ["ana", "bia", "carlos"])
        self.assertEqual([c["senha"] for c in r["contas"]], ["", "", ""])  # sem senhas na resposta

        salvo = {c["usuario"]: c for c in json.loads(self.contas.read_text(encoding="utf-8"))["contas"]}
        self.assertEqual(salvo["ana"]["senha"], "a1")  # senha salva mantida
        self.assertEqual(salvo["ana"]["respostas"]["Sexo"], "Masculino")
        self.assertEqual(salvo["ana"]["nome"], "ANA")
        self.assertEqual(salvo["carlos"]["senha"], "senha-padrao-x")
        self.assertEqual(salvo["carlos"]["respostas"], {**RESPOSTAS, "Sexo": "Masculino"})

    def test_importar_do_san2_sem_padrao_para_o_que_falta(self):
        self.importacao_falsa({"turma": None, "contas": [{"usuario": "x", "senha": "1", "nome": "", "respostas": {"Sexo": "Feminino"}}]})
        status, r = self.post("/api/san2/importar", {"san2_usuario": "staff", "san2_senha": "s", "termo": "x", "respostas_padrao": {}, "senha_padrao": "p"})
        self.assertEqual(status, 400)
        self.assertIn("Não consegui deduzir", r["erro"])
        self.assertFalse(self.contas.exists())

    def test_importar_do_san2_erro_do_san2_vira_400(self):
        sessao = mock.Mock()
        sessao.cliente.side_effect = san2.ErroSan2("Login no SAN2 recusado: senha inválida")
        with mock.patch.object(servidor, "SESSAO_SAN2", sessao):
            status, r = self.post("/api/san2/importar", {"san2_usuario": "staff", "san2_senha": "s", "termo": "x", "senha_padrao": "p"})
        self.assertEqual((status, r["erro"]), (400, "Login no SAN2 recusado: senha inválida"))

    def test_planilha_valida_arquivo_antes_do_login(self):
        base = {"san2_usuario": "staff", "san2_senha": "s", "senha_padrao": "p"}
        self.assertEqual(self.post("/api/san2/planilha", base)[1]["erro"], "Escolha a planilha (.xlsx ou .csv).")
        self.assertEqual(self.post("/api/san2/planilha", {**base, "arquivo_b64": "@@@"})[1]["erro"], "Arquivo inválido.")
        import base64
        csv = base64.b64encode("Telefone;Email\n1;a\n".encode()).decode()
        r = self.post("/api/san2/planilha", {**base, "arquivo_nome": "x.csv", "arquivo_b64": csv})[1]
        self.assertIn("Não achei uma coluna", r["erro"])
        self.assertFalse(self.config.exists())  # não chegou a salvar credenciais

    def test_planilha_importa_e_relata(self):
        import base64
        self.post("/api/contas", {"contas": self.contas_exemplo()})  # ana já existe
        recebido = {}

        def importar_falso(cliente, linhas, turma, senha):
            recebido.update(linhas=linhas, turma=turma, senha=senha)
            return {
                "turma": {"id": 1, "codigo": "PDM.X.1", "curso": "Curso X", "carga_horaria": 3, "tem_pesquisa": True},
                "contas": [
                    {"usuario": "ana", "senha": senha, "nome": "ANA", "respostas": {**RESPOSTAS, "Sexo": "Masculino"}},
                    {"usuario": "davi", "senha": senha, "nome": "DAVI", "respostas": {**RESPOSTAS}},
                ],
                "relatorio": [
                    {"linha": 2, "aluno": "Ana", "status": "ok", "via": "nome", "login": "ana"},
                    {"linha": 3, "aluno": "Davi", "status": "ok", "via": "CPF", "login": "davi"},
                    {"linha": 4, "aluno": "Maria", "status": "ambiguo", "via": "nome", "candidatos": [{"login": "m1", "nascimento": None}]},
                    {"linha": 5, "aluno": "Zé", "status": "nao_encontrado", "via": None},
                ],
            }

        sessao = mock.Mock()
        sessao.cliente.return_value = "cliente-falso"
        csv = base64.b64encode("Nome;CPF\nAna;1\nDavi;2\nMaria;\nZé;\n".encode()).decode()
        with mock.patch.object(servidor, "SESSAO_SAN2", sessao), mock.patch.object(san2, "importar_planilha", importar_falso):
            status, r = self.post("/api/san2/planilha", {
                "san2_usuario": "staff", "san2_senha": "s", "senha_padrao": "p", "turma": "pdm.x.1",
                "arquivo_nome": "alunos.csv", "arquivo_b64": csv, "respostas_padrao": RESPOSTAS,
            })
        self.assertEqual(status, 200)
        self.assertEqual([l["nome"] for l in recebido["linhas"]], ["Ana", "Davi", "Maria", "Zé"])
        self.assertEqual((recebido["turma"], recebido["senha"]), ("pdm.x.1", "p"))
        self.assertEqual(r["resumo"], {"linhas": 4, "encontrados": 2, "ambiguos": 1, "nao_encontrados": 1})
        self.assertEqual((r["adicionadas"], r["atualizadas"]), (1, 1))
        self.assertEqual([c["usuario"] for c in r["contas"]], ["ana", "bia", "davi"])
        self.assertEqual(len(r["relatorio"]), 4)
        salvo = {c["usuario"]: c for c in json.loads(self.contas.read_text(encoding="utf-8"))["contas"]}
        self.assertEqual(salvo["ana"]["senha"], "a1")  # mantida
        self.assertEqual(salvo["davi"]["senha"], "p")

    def test_captura_nao_permite_sair_da_pasta(self):
        self.capturas.mkdir()
        (self.capturas / "ok.png").write_bytes(b"png")
        with self.assertRaises(HTTPError) as ctx:
            self.get("/capturas/../config.json")
        ctx.exception.close()
        self.assertEqual(ctx.exception.code, 404)
        self.assertEqual(servidor.nome_captura(3, "maria silva/ção"), "03-maria_silva_o.png")

    def test_rotas_desconhecidas(self):
        with self.assertRaises(HTTPError) as ctx:
            self.get("/nao-existe")
        ctx.exception.close()
        self.assertEqual(ctx.exception.code, 404)
        self.assertEqual(self.post("/api/nada")[0], 404)


if __name__ == "__main__":
    unittest.main()
