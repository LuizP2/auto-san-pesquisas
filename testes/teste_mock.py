"""Testa a automação contra o frontend REAL do site, com a API simulada.

O Playwright intercepta todas as chamadas a https://api.navedoconhecimento.rio/
e responde com pesquisas falsas, então nada é enviado de verdade.

Rodar:  .venv/bin/python -m unittest testes/teste_mock.py -v
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qs

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pesquisa  # noqa: E402

USUARIO, SENHA = "aluno.teste", "segredo"

SATISFACAO = [
    "Qual o seu grau de satisfação com relação ao número de cursos/oficinas oferecidos?",
    "Qual o seu grau de satisfação com relação à qualidade dos conteúdos oferecidos nos cursos e oficinas?",
    "Qual o seu grau de satisfação com relação à disponibilidade de recursos de material didático?",
    "Qual o seu grau de satisfação com relação à criatividade do instrutor com a preparação das aulas?",
    "Qual o seu grau de satisfação com relação ao atendimento de sua expectativa por parte do curso/oficina?",
]
ESCALA = ["Muito Satisfeito", "Satisfeito", "Indiferente", "Insatisfeito", "Muito Insatisfeito"]

CONFIG = {
    "usuario": USUARIO,
    "respostas": {
        "Sexo": "Feminino",
        "É aluno da rede municipal de ensino?": "Sim",
        "Em que período você frequenta a Nave do Conhecimento?": "Tarde",
        "Qual a sua faixa etária?": "12 a 17 anos",
        "Qual atividade você realizou?": "Curso",
    },
    "resposta_padrao": "Muito Satisfeito",
}


def montar_turma(gid: int, codigo: str, curso: str, escala: list[str] = ESCALA) -> dict:
    perguntas = []

    def pergunta(texto, alternativas):
        qid = gid * 100 + len(perguntas) + 1
        perguntas.append({
            "id": qid,
            "type": "MULTIPLE-ONE",
            "text": texto,
            "alternatives": [
                {"id": qid * 10 + i, "text": t, "justifiable": False}
                for i, t in enumerate(alternativas, 1)
            ],
        })

    for texto, opcoes in pesquisa.PERGUNTAS_PERFIL:
        pergunta(texto, opcoes)
    for texto in SATISFACAO:
        pergunta(texto, escala)
    return {
        "id": gid,
        "code": codigo,
        "course": {"name": curso},
        "unit": {"id": 7},
        "satisfaction_survey": {
            "survey": {
                "id": 500 + gid,
                "name": "Pesquisa de Satisfação - Oficinas & Cursos (Usina Social)",
                "questions": perguntas,
            }
        },
    }


class ApiFalsa:
    def __init__(self, turmas: list[dict]):
        self.fila = list(turmas)
        self.envios: list[dict] = []

    def tratar(self, rota, requisicao):
        cors = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Methods": "*",
        }
        if requisicao.method == "OPTIONS":
            rota.fulfill(status=204, headers=cors)
            return
        url, status = requisicao.url, 200
        if "/oauth2/token" in url:
            dados = parse_qs(requisicao.post_data or "")
            if dados.get("username") == [USUARIO] and dados.get("password") == [SENHA]:
                corpo = {"access_token": "token-falso", "token_type": "Bearer"}
            else:
                corpo, status = {"error": "invalid_credentials"}, 401
        elif "/user/me/info" in url:
            corpo = {"user": {"id": 1, "name": "Aluno Teste"}}
        elif "/user/me/satisfaction-survey-to-answer" in url:
            corpo = {"group": self.fila[0] if self.fila else None}
        elif "/user/me/survey-answers" in url:
            self.envios.append(json.loads(requisicao.post_data))
            self.fila.pop(0)
            corpo = {"ok": True}
        else:
            corpo, status = {"erro": "rota desconhecida"}, 404
        rota.fulfill(
            status=status,
            headers={**cors, "Content-Type": "application/json"},
            body=json.dumps(corpo),
        )


def esperado(turma: dict) -> dict:
    """{id da pergunta: id da alternativa} que a automação deve escolher."""
    resultado = {}
    for q in turma["satisfaction_survey"]["survey"]["questions"]:
        resposta = pesquisa.resolver_resposta(q["text"], CONFIG["respostas"]) or CONFIG["resposta_padrao"]
        alt = next(a for a in q["alternatives"] if a["text"] == resposta)
        resultado[str(q["id"])] = alt["id"]
    return resultado


class TesteAutomacao(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.navegador = cls.pw.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.navegador.close()
        cls.pw.stop()

    def abrir(self, api: ApiFalsa):
        contexto = self.navegador.new_context()
        contexto.route("https://api.navedoconhecimento.rio/**", api.tratar)
        self.addCleanup(contexto.close)
        return contexto.new_page()

    def test_responde_todas_as_pesquisas_pendentes(self):
        turmas = [
            montar_turma(1, "PDM.IKCC.P1.6", "Informática Kids - Componentes do Computador"),
            montar_turma(2, "PDM.ROB.P2.1", "Robótica"),
        ]
        api = ApiFalsa(turmas)
        pagina = self.abrir(api)

        total = pesquisa.executar(pagina, CONFIG, SENHA)

        self.assertEqual(total, 2)
        self.assertEqual(len(api.envios), 2)
        self.assertTrue(pesquisa.em_pagina_final(pagina))
        for turma, envio in zip(turmas, api.envios):
            self.assertEqual(envio["group_id"], turma["id"])
            self.assertEqual(envio["survey_id"], turma["satisfaction_survey"]["survey"]["id"])
            self.assertEqual(envio["unit_id"], 7)
            marcadas = {qid: q["answer"]["alternative_id"] for qid, q in envio["questions"].items()}
            # O próprio site reaproveita o objeto de respostas entre pesquisas, então o 2º envio
            # também carrega as perguntas da 1ª; o que importa é que as desta turma estejam certas.
            self.assertEqual({q: marcadas.get(q) for q in esperado(turma)}, esperado(turma))

    def test_sem_pesquisa_pendente(self):
        api = ApiFalsa([])
        pagina = self.abrir(api)
        self.assertEqual(pesquisa.executar(pagina, CONFIG, SENHA), 0)
        self.assertEqual(api.envios, [])
        self.assertTrue(pesquisa.em_pagina_final(pagina))

    def test_login_invalido(self):
        api = ApiFalsa([montar_turma(1, "X", "Curso")])
        pagina = self.abrir(api)
        with self.assertRaises(pesquisa.ErroAutomacao) as ctx:
            pesquisa.executar(pagina, CONFIG, "senha-errada")
        self.assertIn("credenciais", str(ctx.exception).lower())
        self.assertEqual(api.envios, [])

    def test_resposta_padrao_inexistente_nao_envia(self):
        turma = montar_turma(1, "X", "Curso", escala=["Ótimo", "Bom", "Ruim"])
        api = ApiFalsa([turma])
        pagina = self.abrir(api)
        with self.assertRaises(pesquisa.ErroAutomacao) as ctx:
            pesquisa.executar(pagina, CONFIG, SENHA)
        self.assertIn("Muito Satisfeito", str(ctx.exception))
        self.assertIn("Ótimo, Bom, Ruim", str(ctx.exception))
        self.assertEqual(api.envios, [])

    def test_sem_enviar_preenche_e_para(self):
        turma = montar_turma(1, "X", "Curso")
        api = ApiFalsa([turma])
        pagina = self.abrir(api)
        self.assertEqual(pesquisa.executar(pagina, CONFIG, SENHA, enviar=False), 0)
        self.assertEqual(api.envios, [])
        marcadas = pagina.evaluate(
            "() => [...document.querySelectorAll('input[type=radio]:checked')].map(r => r.value)"
        )
        self.assertEqual(sorted(map(int, marcadas)), sorted(esperado(turma).values()))


class TesteComparacao(unittest.TestCase):
    def test_resolver_resposta_ignora_acentos_e_pontuacao(self):
        respostas = {"faixa etaria": "18 a 60 anos", "Sexo": "Masculino"}
        self.assertEqual(pesquisa.resolver_resposta("Qual a sua faixa etária?", respostas), "18 a 60 anos")
        self.assertEqual(pesquisa.resolver_resposta("SEXO", respostas), "Masculino")
        self.assertIsNone(pesquisa.resolver_resposta("Grau de satisfação?", respostas))

    def test_atividade_nao_casa_com_criatividade(self):
        respostas = dict(CONFIG["respostas"])
        self.assertIsNone(
            pesquisa.resolver_resposta("Qual o seu grau de satisfação com relação à criatividade do instrutor?", respostas)
        )

    def test_escolher_alternativa(self):
        alts = [{"texto": t} for t in ESCALA]
        self.assertEqual(pesquisa.escolher_alternativa("muito satisfeito", alts)["texto"], "Muito Satisfeito")
        self.assertEqual(pesquisa.escolher_alternativa("Satisfeito", alts)["texto"], "Satisfeito")
        self.assertIsNone(pesquisa.escolher_alternativa("Muito", alts))  # ambíguo
        self.assertEqual(pesquisa.escolher_alternativa("Indif", alts)["texto"], "Indiferente")


if __name__ == "__main__":
    unittest.main()
