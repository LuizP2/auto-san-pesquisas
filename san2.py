#!/usr/bin/env python3
"""Cliente do SAN2 (painel do staff) para puxar frequentadores e turmas e
deduzir as respostas de perfil da pesquisa de satisfação.

Fluxo mapeado em docs/san2-fluxo.md: o login é OAuth2 (PKCE) em
contas.navedoconhecimento.rio — feito aqui pelo navegador, invisível, só para
capturar o token — e o resto são consultas GET com um JSON no parâmetro `q`.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date, datetime

import pesquisa

API = "https://api.navedoconhecimento.rio/"
SAN2 = "https://san2.navedoconhecimento.rio/"
SENHA_PADRAO = ""  # a senha padrão dos frequentadores fica só no config.json (nunca no repositório)
CARGA_MAXIMA_OFICINA = 6  # horas-aula; acima disso é curso
TEMPO_LOGIN = 45  # segundos

(P_SEXO, P_REDE, P_PERIODO, P_FAIXA, P_ATIVIDADE) = (p for p, _ in pesquisa.PERGUNTAS_PERFIL)


class ErroSan2(Exception):
    pass


# ---------------------------------------------------------------------------
# Regras: dados do cadastro -> respostas de perfil
# ---------------------------------------------------------------------------


def sexo(gender: str | None) -> str | None:
    return {"M": "Masculino", "F": "Feminino"}.get((gender or "").upper())


def faixa_etaria(nascimento: str | None, hoje: date | None = None) -> str | None:
    """nascimento no formato dd/mm/aaaa (como a API devolve)."""
    if not nascimento:
        return None
    try:
        nasc = datetime.strptime(nascimento[:10], "%d/%m/%Y").date()
    except ValueError:
        return None
    hoje = hoje or date.today()
    idade = hoje.year - nasc.year - ((hoje.month, hoje.day) < (nasc.month, nasc.day))
    if idade <= 5:
        return "0 a 5 anos"
    if idade <= 11:
        return "06 a 11 anos"
    if idade <= 17:
        return "12 a 17 anos"
    if idade <= 60:
        return "18 a 60 anos"
    return "Acima de 60 anos"


def periodo(grades: list[dict]) -> str | None:
    """grades: [{"date": "dd/mm/aaaa", "start_time": "HH:MM:SS"}] (aulas da turma).

    Fim de semana vence; senão o turno mais frequente pelo horário de início."""
    votos: Counter[str] = Counter()
    for g in grades:
        try:
            dia = datetime.strptime((g.get("date") or "")[:10], "%d/%m/%Y").date()
            hora = int((g.get("start_time") or "")[:2])
        except ValueError:
            continue
        if dia.weekday() >= 5:
            votos["Final de Semana"] += 1
        elif hora < 12:
            votos["Manhã"] += 1
        elif hora < 18:
            votos["Tarde"] += 1
        else:
            votos["Noite"] += 1
    if not votos:
        return None
    if votos["Final de Semana"]:
        return "Final de Semana"
    return votos.most_common(1)[0][0]


def atividade(carga_horaria) -> str | None:
    if carga_horaria is None:
        return None
    return "Oficina" if float(carga_horaria) <= CARGA_MAXIMA_OFICINA else "Curso"


def rede_municipal(person: dict) -> str:
    instituicao = person.get("educational_institution") or {}
    tipo = ((instituicao.get("type") or {}).get("name") or "")
    return "Sim" if "municipal" in pesquisa.normalizar(tipo) else "Não"


def respostas_de(person: dict, carga_horaria, grades: list[dict]) -> dict:
    """Só as respostas que dá para deduzir; o que faltar fica para o padrão do formulário."""
    deduzidas = {
        P_SEXO: sexo(person.get("gender")),
        P_REDE: rede_municipal(person),
        P_PERIODO: periodo(grades),
        P_FAIXA: faixa_etaria(person.get("birthdate")),
        P_ATIVIDADE: atividade(carga_horaria),
    }
    return {p: r for p, r in deduzidas.items() if r}


# ---------------------------------------------------------------------------
# Login do staff (navegador invisível) e sessão
# ---------------------------------------------------------------------------


def entrar(usuario: str, senha: str, headless: bool = True) -> dict:
    """Faz o login no SAN2 e devolve o token: {"access_token", "expires_in", "obtido_em"}."""
    token: dict = {}
    with pesquisa.sync_playwright() as pw:
        navegador = pesquisa.abrir_navegador(pw, headless)
        pagina = navegador.new_page()

        def capturar(resposta):
            if "oauth2/token" in resposta.url and resposta.request.method == "POST" and resposta.ok:
                try:
                    token.update(resposta.json())
                except ValueError:
                    pass

        pagina.on("response", capturar)
        try:
            pagina.goto(SAN2)
            pagina.locator("input[name=username]").fill(usuario)
            pagina.locator("input[name=password]").fill(senha)
            pagina.get_by_role("button", name="Entrar").click()
            limite = time.monotonic() + TEMPO_LOGIN
            while time.monotonic() < limite and not token.get("access_token"):
                pagina.wait_for_timeout(250)
                if "contas." in pagina.url:  # ainda na tela de login: o site recusou?
                    aviso = mensagem_de_erro(pagina)
                    if aviso:
                        raise ErroSan2(f"Login no SAN2 recusado: {aviso}")
        except pesquisa.ErroPlaywright as e:
            raise ErroSan2(f"Falha no navegador durante o login do SAN2: {e.message.splitlines()[0]}") from None
        finally:
            navegador.close()
    if not token.get("access_token"):
        raise ErroSan2("Login no SAN2 não completou (tempo esgotado).")
    token["obtido_em"] = time.time()
    return token


def mensagem_de_erro(pagina) -> str | None:
    """Texto de erro visível na tela de login do contas (Bulma: .help.is-danger), se houver.

    Devolve None também quando a página está navegando (o contexto some no meio)."""
    try:
        texto = pagina.evaluate(
            "() => [...document.querySelectorAll('.help.is-danger, .notification.is-danger, [role=alert], "
            ".text-danger, .invalid-feedback, .error')].map(e => e.textContent.trim()).filter(Boolean).join(' | ')"
        )
    except pesquisa.ErroPlaywright:
        return None
    return texto or None


class Sessao:
    """Guarda o token e renova quando vence."""

    def __init__(self) -> None:
        self.token: dict = {}
        self.usuario: str | None = None

    def valida(self, usuario: str) -> bool:
        if self.usuario != usuario or not self.token.get("access_token"):
            return False
        validade = self.token["obtido_em"] + int(self.token.get("expires_in") or 0) - 120
        return time.time() < validade

    def cliente(self, usuario: str, senha: str) -> "San2":
        if not self.valida(usuario):
            self.token = entrar(usuario, senha)
            self.usuario = usuario
        return San2(self.token["access_token"])


# ---------------------------------------------------------------------------
# Consultas
# ---------------------------------------------------------------------------


class San2:
    def __init__(self, token: str) -> None:
        self.token = token

    def buscar(self, rota: str, q: dict, **params) -> dict:
        consulta = {"language": "pt", "q": json.dumps(q, ensure_ascii=False), **params}
        url = API + rota + "?" + urllib.parse.urlencode(consulta)
        req = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise ErroSan2("A sessão do SAN2 expirou; tente de novo.") from None
            raise ErroSan2(f"A API respondeu {e.code} em {rota}: {e.read().decode(errors='replace')[:200]}") from None
        except urllib.error.URLError as e:
            raise ErroSan2(f"Sem resposta da API ({e.reason}).") from None

    def paginado(self, rota: str, q: dict, por_pagina: int = 100) -> list[dict]:
        itens, pagina = [], 1
        while True:
            resposta = self.buscar(rota, {**q, "page": pagina, "max": por_pagina})
            itens += resposta.get("data") or []
            if not (resposta.get("metadata") or {}).get("pages", {}).get("url_next"):
                return itens
            pagina += 1

    def turma(self, codigo_ou_id: str) -> dict | None:
        campo = "id" if str(codigo_ou_id).isdigit() else "code"
        valor = int(codigo_ou_id) if campo == "id" else str(codigo_ou_id).strip().upper()
        dados = self.buscar("capacitation/group/search", {
            "with": ["course.category.type", "unit", "satisfactionSurvey.survey"],
            "filters": [{"conditions": [{"field": campo, "value": valor}]}],
        }).get("data") or []
        return dados[0] if dados else None

    def grades(self, group_id: int) -> list[dict]:
        return self.paginado("capacitation/grid/search", {
            "filters": [{"conditions": [{"field": "group_id", "value": group_id}]}],
        })

    def matriculados(self, group_id: int) -> list[dict]:
        return self.paginado("capacitation/enrollment/search", {
            "with-has": ["group.course", "frequenter.user.person"],
            "with": ["frequencies.grid", "frequenter.user.person.educationalInstitution.type"],
            "filters": [{"conditions": [{"field": "group_id", "value": group_id}]}],
        })

    def frequentadores(self, termo: str) -> list[dict]:
        """Por login exato; se não achar, por nome (contém)."""
        base = {
            "with": ["person.educationalInstitution.type"],
            "sort": [{"field": "id", "order": "desc"}],
            "max": 25,
        }
        ativo = {"operator": "has", "relationship": "frequenter", "conditions": [{"field": "enabled", "value": 1}]}
        por_login = self.buscar("user/search", {
            **base, "filters": [ativo, {"conditions": [{"field": "username", "value": termo.strip()}]}],
        }).get("data") or []
        if por_login:
            return por_login
        return self.buscar("user/search", {
            **base, "filters": [ativo, {
                "operator": "has", "relationship": "person", "conditions": [
                    {"type": "search", "field": "full_name", "value": termo.strip()},
                    {"operator": "or", "type": "search", "field": "social_name", "value": termo.strip()},
                ],
            }],
        }).get("data") or []

    _ATIVO = {"operator": "has", "relationship": "frequenter", "conditions": [{"field": "enabled", "value": 1}]}
    _COM_PERFIL = {"with": ["person.educationalInstitution.type"], "max": 25}

    def _por_pessoa(self, condicoes: list[dict]) -> list[dict]:
        return self.buscar("user/search", {
            **self._COM_PERFIL,
            "filters": [self._ATIVO, {"operator": "has", "relationship": "person", "conditions": condicoes}],
        }).get("data") or []

    def por_login(self, login: str) -> list[dict]:
        return self.buscar("user/search", {
            **self._COM_PERFIL, "filters": [self._ATIVO, {"conditions": [{"field": "username", "value": login.strip()}]}],
        }).get("data") or []

    def por_cpf(self, cpf: str) -> list[dict]:
        return self._por_pessoa([{"field": "cpf_number", "value": cpf}])

    def por_nome(self, nome: str) -> list[dict]:
        """Igualdade (o SAN ignora caixa e acentos); se nada, a busca aproximada filtrada
        localmente por quem tem todas as palavras do nome."""
        iguais = self._por_pessoa([
            {"field": "full_name", "value": nome},
            {"operator": "or", "field": "social_name", "value": nome},
        ])
        if iguais:
            return iguais
        palavras = set(pesquisa.normalizar(nome).split())
        aproximados = self._por_pessoa([{"type": "search", "field": "full_name", "value": nome}])
        return [
            u for u in aproximados
            if u.get("person") and palavras <= set(pesquisa.normalizar(u["person"].get("full_name") or "").split())
        ]

    def matriculas(self, user_id: int, maximo: int = 10) -> list[dict]:
        return self.buscar("capacitation/enrollment/search", {
            "with-has": ["group.course"],
            "with": ["frequencies.grid"],
            "sort": [{"field": "id", "order": "desc"}],
            "max": maximo,
            "filters": [{"operator": "has", "relationship": "frequenter.user", "conditions": [{"field": "id", "value": user_id}]}],
        }).get("data") or []


# ---------------------------------------------------------------------------
# Importação: turma inteira ou um frequentador -> contas para a lista
# ---------------------------------------------------------------------------


def grades_da_matricula(matricula: dict) -> list[dict]:
    return [f["grid"] for f in matricula.get("frequencies") or [] if f.get("grid")]


def conta_de(user: dict, carga_horaria, grades: list[dict], senha: str) -> dict:
    person = user.get("person") or {}
    return {
        "usuario": user["username"],
        "senha": senha,
        "nome": (person.get("social_name") or person.get("full_name") or "").strip(),
        "respostas": respostas_de(person, carga_horaria, grades),
    }


def importar_turma(cliente: San2, codigo: str, senha: str = SENHA_PADRAO) -> dict:
    turma = cliente.turma(codigo)
    if not turma:
        raise ErroSan2(f'Turma "{codigo}" não encontrada.')
    carga = (turma.get("course") or {}).get("workload")
    grade_turma = cliente.grades(turma["id"])
    contas = []
    for m in cliente.matriculados(turma["id"]):
        if m.get("canceled_at"):
            continue
        user = ((m.get("frequenter") or {}).get("user")) or {}
        if not user.get("username"):
            continue
        contas.append(conta_de(user, carga, grades_da_matricula(m) or grade_turma, senha))
    return {
        "turma": {
            "id": turma["id"], "codigo": turma["code"], "curso": (turma.get("course") or {}).get("name"),
            "carga_horaria": carga, "tem_pesquisa": bool(turma.get("satisfaction_survey")),
        },
        "contas": contas,
    }


def matricula_atual(matriculas: list[dict], hoje: date | None = None) -> dict:
    """A matrícula mais recente cuja turma já começou (a pesquisa é sobre ela); se
    nenhuma começou, a mais recente. `matriculas` vem ordenada da mais nova para a mais velha."""
    hoje = hoje or date.today()
    for m in matriculas:
        inicio = ((m.get("group") or {}).get("start_date") or "")[:10]
        try:
            if datetime.strptime(inicio, "%d/%m/%Y").date() <= hoje:
                return m
        except ValueError:
            continue
    return matriculas[0]


def importar_frequentador(cliente: San2, termo: str, senha: str = SENHA_PADRAO) -> dict:
    encontrados = cliente.frequentadores(termo)
    if not encontrados:
        raise ErroSan2(f'Nenhum frequentador encontrado para "{termo}".')
    if len(encontrados) > 1:
        nomes = ", ".join(f'{u["username"]}' for u in encontrados[:8])
        raise ErroSan2(f"{len(encontrados)} frequentadores batem com \"{termo}\"; use o login exato. Logins: {nomes}")
    user = encontrados[0]
    matriculas = [m for m in cliente.matriculas(user["id"]) if not m.get("canceled_at")]
    carga, grades, turma = None, [], None
    if matriculas:
        ultima = matricula_atual(matriculas)
        turma = ultima.get("group") or {}
        carga = (turma.get("course") or {}).get("workload")
        grades = grades_da_matricula(ultima) or cliente.grades(turma["id"])
    conta = conta_de(user, carga, grades, senha)
    return {
        "turma": {"codigo": turma.get("code"), "curso": (turma.get("course") or {}).get("name"), "carga_horaria": carga} if turma else None,
        "contas": [conta],
    }


# ---------------------------------------------------------------------------
# Importação por planilha: cada linha vira uma busca (login -> CPF -> nome)
# ---------------------------------------------------------------------------


def localizar(cliente: San2, linha: dict) -> dict:
    """linha: {"nome", "login", "cpf", "nascimento"} -> {"status": ok|ambiguo|nao_encontrado, "user", "via", "candidatos"}."""
    tentativas = []
    if linha.get("login"):
        tentativas.append(("login", lambda: cliente.por_login(linha["login"])))
    if linha.get("cpf"):
        tentativas.append(("CPF", lambda: cliente.por_cpf(linha["cpf"])))
    if linha.get("nome"):
        tentativas.append(("nome", lambda: cliente.por_nome(linha["nome"])))

    for via, buscar in tentativas:
        achados = [u for u in buscar() if u.get("username")]
        if not achados:
            continue
        if len(achados) > 1 and linha.get("nascimento"):
            achados = [u for u in achados if (u.get("person") or {}).get("birthdate") == linha["nascimento"]] or achados
        if len(achados) == 1:
            return {"status": "ok", "user": achados[0], "via": via, "candidatos": []}
        return {"status": "ambiguo", "user": None, "via": via, "candidatos": achados}
    return {"status": "nao_encontrado", "user": None, "via": None, "candidatos": []}


def importar_planilha(cliente: San2, linhas: list[dict], turma_codigo: str | None = None, senha: str = SENHA_PADRAO) -> dict:
    """Localiza cada aluno da planilha. Com o código da turma, período e atividade
    vêm dela; sem ele, ficam para o padrão do formulário."""
    turma, carga, grades = None, None, []
    if turma_codigo:
        turma = cliente.turma(turma_codigo)
        if not turma:
            raise ErroSan2(f'Turma "{turma_codigo}" não encontrada.')
        carga = (turma.get("course") or {}).get("workload")
        grades = cliente.grades(turma["id"])

    contas, relatorio = [], []
    for linha in linhas:
        rotulo = linha.get("nome") or linha.get("login") or linha.get("cpf")
        r = localizar(cliente, linha)
        item = {"linha": linha["n"], "aluno": rotulo, "status": r["status"], "via": r["via"]}
        if r["status"] == "ok":
            contas.append(conta_de(r["user"], carga, grades, senha))
            item["login"] = r["user"]["username"]
        elif r["status"] == "ambiguo":
            item["candidatos"] = [
                {"login": u["username"], "nascimento": (u.get("person") or {}).get("birthdate")} for u in r["candidatos"][:6]
            ]
        relatorio.append(item)
    return {
        "turma": {
            "id": turma["id"], "codigo": turma["code"], "curso": (turma.get("course") or {}).get("name"),
            "carga_horaria": carga, "tem_pesquisa": bool(turma.get("satisfaction_survey")),
        } if turma else None,
        "contas": contas,
        "relatorio": relatorio,
    }
