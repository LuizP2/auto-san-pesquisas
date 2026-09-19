"""Testa as regras de dedução e a importação do SAN2 (com um cliente falso).

Rodar:  .venv/bin/python -m unittest testes/teste_san2.py -v
"""

from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import san2  # noqa: E402

HOJE = date(2026, 9, 19)


def pessoa(gender="F", nascimento="01/01/2012", instituicao="Municipal", nome="ALUNA TESTE"):
    return {
        "gender": gender, "birthdate": nascimento, "full_name": nome, "social_name": "",
        "educational_institution": {"type": {"name": instituicao}} if instituicao else None,
    }


def matricula(username, person, grades=(), cancelada=False, grupo=None):
    return {
        "canceled_at": "01/01/2026" if cancelada else None,
        "frequenter": {"user": {"id": hash(username) % 10000, "username": username, "person": person}},
        "frequencies": [{"grid": g} for g in grades],
        "group": grupo or {},
    }


class ClienteFalso:
    def __init__(self, turma=None, matriculados=(), grade=(), usuarios=(), matriculas=()):
        self._turma, self._matriculados, self._grade = turma, list(matriculados), list(grade)
        self._usuarios, self._matriculas = list(usuarios), list(matriculas)

    def turma(self, codigo):
        if self._turma and str(codigo).upper() in (self._turma["code"], str(self._turma["id"])):
            return self._turma
        return None

    def matriculados(self, group_id):
        return self._matriculados

    def grades(self, group_id):
        return self._grade

    def frequentadores(self, termo):
        return self._usuarios

    def matriculas(self, user_id, maximo=10):
        return self._matriculas


class TesteRegras(unittest.TestCase):
    def test_sexo(self):
        self.assertEqual(san2.sexo("M"), "Masculino")
        self.assertEqual(san2.sexo("f"), "Feminino")
        self.assertIsNone(san2.sexo(None))

    def test_faixa_etaria_limites(self):
        casos = {
            "19/09/2021": "0 a 5 anos",      # faz 5 hoje
            "20/09/2020": "0 a 5 anos",      # faz 6 amanhã
            "19/09/2020": "06 a 11 anos",    # faz 6 hoje
            "20/09/2014": "06 a 11 anos",
            "19/09/2014": "12 a 17 anos",
            "20/09/2008": "12 a 17 anos",
            "19/09/2008": "18 a 60 anos",
            "19/09/1966": "18 a 60 anos",    # faz 60 hoje
            "18/09/1966": "18 a 60 anos",    # fez 60 ontem
            "19/09/1965": "Acima de 60 anos",  # faz 61 hoje
        }
        for nasc, esperado in casos.items():
            self.assertEqual(san2.faixa_etaria(nasc, HOJE), esperado, nasc)
        self.assertIsNone(san2.faixa_etaria(None))
        self.assertIsNone(san2.faixa_etaria("data ruim"))

    def test_periodo(self):
        self.assertEqual(san2.periodo([{"date": "17/09/2026", "start_time": "14:00:00"}]), "Tarde")
        self.assertEqual(san2.periodo([{"date": "17/09/2026", "start_time": "09:30:00"}]), "Manhã")
        self.assertEqual(san2.periodo([{"date": "17/09/2026", "start_time": "18:00:00"}]), "Noite")
        self.assertEqual(san2.periodo([{"date": "19/09/2026", "start_time": "10:00:00"}]), "Final de Semana")  # sábado
        # curso com aulas em turnos diferentes: o mais frequente vence; fim de semana vence sempre
        self.assertEqual(san2.periodo([
            {"date": "14/09/2026", "start_time": "08:00:00"},
            {"date": "15/09/2026", "start_time": "14:00:00"},
            {"date": "16/09/2026", "start_time": "14:00:00"},
        ]), "Tarde")
        self.assertEqual(san2.periodo([
            {"date": "14/09/2026", "start_time": "08:00:00"},
            {"date": "20/09/2026", "start_time": "08:00:00"},
        ]), "Final de Semana")
        self.assertIsNone(san2.periodo([]))
        self.assertIsNone(san2.periodo([{"date": None, "start_time": None}]))

    def test_atividade(self):
        self.assertEqual(san2.atividade(3), "Oficina")
        self.assertEqual(san2.atividade(6), "Oficina")
        self.assertEqual(san2.atividade(6.5), "Curso")
        self.assertEqual(san2.atividade(40), "Curso")
        self.assertIsNone(san2.atividade(None))

    def test_rede_municipal(self):
        self.assertEqual(san2.rede_municipal(pessoa(instituicao="Municipal")), "Sim")
        self.assertEqual(san2.rede_municipal(pessoa(instituicao="Rede Municipal")), "Sim")
        self.assertEqual(san2.rede_municipal(pessoa(instituicao="Particular")), "Não")
        self.assertEqual(san2.rede_municipal(pessoa(instituicao="Estadual")), "Não")
        self.assertEqual(san2.rede_municipal(pessoa(instituicao=None)), "Não")
        self.assertEqual(san2.rede_municipal({}), "Não")

    def test_respostas_de_omite_o_que_nao_deduz(self):
        r = san2.respostas_de(pessoa(gender=None, nascimento=None), None, [])
        self.assertEqual(r, {san2.P_REDE: "Sim"})

    def test_matricula_atual_prefere_turma_ja_iniciada(self):
        futura = {"group": {"start_date": "29/09/2026", "code": "F"}}
        passada = {"group": {"start_date": "03/08/2026", "code": "P"}}
        self.assertEqual(san2.matricula_atual([futura, passada], HOJE)["group"]["code"], "P")
        self.assertEqual(san2.matricula_atual([futura], HOJE)["group"]["code"], "F")


class TesteImportacao(unittest.TestCase):
    def test_importar_turma(self):
        turma = {"id": 38538, "code": "PDM.IKCC.P1.7", "course": {"name": "Informática Kids", "workload": 3},
                 "satisfaction_survey": {"id": 1}}
        grade = [{"date": "17/09/2026", "start_time": "14:00:00"}]
        cliente = ClienteFalso(turma=turma, grade=grade, matriculados=[
            matricula("ana", pessoa("F", "01/01/2012", "Municipal"), grades=grade),
            matricula("bruno", pessoa("M", "01/01/2000", "Particular")),          # sem presença: usa a grade da turma
            matricula("cancelado", pessoa("M", "01/01/2000", None), cancelada=True),
            {"canceled_at": None, "frequenter": {"user": {"id": 1, "person": {}}}},  # sem login: pulado
        ])
        r = san2.importar_turma(cliente, "pdm.ikcc.p1.7", senha="senha-padrao-x")
        self.assertEqual(r["turma"], {"id": 38538, "codigo": "PDM.IKCC.P1.7", "curso": "Informática Kids", "carga_horaria": 3, "tem_pesquisa": True})
        self.assertEqual([c["usuario"] for c in r["contas"]], ["ana", "bruno"])
        ana, bruno = r["contas"]
        self.assertEqual(ana["senha"], "senha-padrao-x")
        self.assertEqual(ana["nome"], "ALUNA TESTE")
        self.assertEqual(ana["respostas"], {
            san2.P_SEXO: "Feminino", san2.P_REDE: "Sim", san2.P_PERIODO: "Tarde",
            san2.P_FAIXA: san2.faixa_etaria("01/01/2012"), san2.P_ATIVIDADE: "Oficina",
        })
        self.assertEqual(bruno["respostas"][san2.P_PERIODO], "Tarde")
        self.assertEqual(bruno["respostas"][san2.P_REDE], "Não")

    def test_importar_turma_inexistente(self):
        with self.assertRaises(san2.ErroSan2):
            san2.importar_turma(ClienteFalso(), "NADA")

    def test_importar_frequentador(self):
        usuario = {"id": 7, "username": "wallace", "person": pessoa("M", "14/05/1989", "Particular", "W G")}
        grupo = {"id": 9, "code": "PDM.X.1", "start_date": "03/08/2026", "course": {"name": "IA", "workload": 40}}
        cliente = ClienteFalso(usuarios=[usuario], grade=[{"date": "03/08/2026", "start_time": "19:00:00"}],
                               matriculas=[matricula("wallace", usuario["person"], grupo=grupo)])
        r = san2.importar_frequentador(cliente, "wallace")
        self.assertEqual(r["turma"], {"codigo": "PDM.X.1", "curso": "IA", "carga_horaria": 40})
        c = r["contas"][0]
        self.assertEqual(c["usuario"], "wallace")
        self.assertEqual(c["respostas"][san2.P_ATIVIDADE], "Curso")
        self.assertEqual(c["respostas"][san2.P_PERIODO], "Noite")
        self.assertEqual(c["respostas"][san2.P_SEXO], "Masculino")

    def test_importar_frequentador_sem_matricula_ou_ambiguo(self):
        usuario = {"id": 7, "username": "novo", "person": pessoa("F", "01/01/2015", None)}
        r = san2.importar_frequentador(ClienteFalso(usuarios=[usuario]), "novo")
        self.assertIsNone(r["turma"])
        self.assertNotIn(san2.P_PERIODO, r["contas"][0]["respostas"])
        self.assertNotIn(san2.P_ATIVIDADE, r["contas"][0]["respostas"])
        with self.assertRaises(san2.ErroSan2) as ctx:
            san2.importar_frequentador(ClienteFalso(usuarios=[usuario, {**usuario, "username": "novo2"}]), "nov")
        self.assertIn("use o login exato", str(ctx.exception))
        with self.assertRaises(san2.ErroSan2):
            san2.importar_frequentador(ClienteFalso(), "ninguem")


if __name__ == "__main__":
    unittest.main()
