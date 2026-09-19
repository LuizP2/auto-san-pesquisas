# SAN2 — como o site busca os dados do frequentador

Mapeado a partir do monitor de rede (sessão de 19/09/2026). Tudo do SAN2 fala
com a mesma API do site de pesquisas: `https://api.navedoconhecimento.rio/`.

## Autenticação (staff)

OAuth2 *authorization code* com PKCE, em `contas.navedoconhecimento.rio`:

1. `GET https://san2.navedoconhecimento.rio/` → redireciona para
   `GET https://contas.navedoconhecimento.rio/oauth2/authorize?client_id=<client_id do SAN2>&response_type=code&redirect_uri=https://san2.navedoconhecimento.rio/login&scope=…&code_challenge=…&code_challenge_method=S256`
   → `302 /login` (tela de usuário/senha).
2. `POST https://contas.navedoconhecimento.rio/login?language=pt` com JSON
   `{"username": "...", "password": "..."}` (XHR).
3. Nova chamada ao `/oauth2/authorize` → `302 https://san2.navedoconhecimento.rio/login?code=…`.
4. O SAN2 troca o código: `POST https://api.navedoconhecimento.rio/oauth2/token`
   (JSON: `grant_type=authorization_code, client_id, code, redirect_uri, code_verifier`)
   → `{"token_type":"Bearer","expires_in":28800,"access_token":"<JWT>","refresh_token":"…"}`.
5. Toda chamada seguinte leva `Authorization: Bearer <JWT>` (validade 8 h).

Para automatizar: o mais simples é fazer o login pelo Playwright (headless) e
capturar o `access_token` na resposta do `oauth2/token`; daí em diante chamar
a API direto, sem navegador.

Os *scopes* do staff incluem `user_search`, `person_search`,
`capacitation_enrollment_search`, `capacitation_group_search`, `survey_search`
e `user_update_password`. **Não há** scope para responder pesquisa em nome de
outro usuário.

## Formato das buscas

Todos os `*/search` são `GET` com um parâmetro `q` contendo JSON (URL-encoded):

```json
{
  "page": 1, "max": 25,
  "sort": [{"field": "id", "order": "desc"}],
  "with": ["frequenter", "person.specialNeeds"],
  "with-has": ["group.course"],
  "filters": [
    {"operator": "has", "relationship": "frequenter", "conditions": [{"field": "enabled", "value": 1}]},
    {"conditions": [{"type": "search", "field": "username", "value": "fulano"}]}
  ]
}
```

- `with` carrega relações; `with-has` carrega e exige que existam.
- `filters[].conditions[]`: `{"field","value"}` é igualdade; `"type":"search"` é
  "contém"; `"operator":"or"` encadeia; `"operator":"has","relationship":…`
  filtra por relação.
- Resposta: `{"data":[…], "metadata":{"records":{"total","page"},"pages":{"total","current","url_next","url_previous"}}}`.

## Endpoints usados na aba Frequentadores

| Passo | Chamada |
| --- | --- |
| Busca por usuário | `GET /user/search?language=pt&q=…` com `{"type":"search","field":"username","value":"…"}` |
| Busca por nome | mesma rota, `operator:has, relationship:person` com `full_name` **ou** `social_name` (`type:search`). Atenção: `type:search` é **aproximada** (até 25 candidatos por relevância; `total` fixo em 100); a condição de **igualdade** (`{"field":"full_name","value":…}`, sem `type`) funciona e ignora caixa/acentos |
| Busca por CPF | mesma rota, `relationship:person`, `{"field":"cpf_number","value":"<11 dígitos, sem pontuação>"}` |
| Abrir o frequentador | `GET /user/search` com `{"field":"id","value":<user_id>}` e `with` amplo (`person`, `person.units`, `person.neighborhood`, `frequenter.responsibles…`) |
| Matrículas dele | `GET /capacitation/enrollment/search` com `operator:has, relationship:"frequenter.user", field:id` e `with-has:["group.course","group.unit"]` |
| Listas auxiliares | `GET /special_needs`, `/federative_unit`, `/city?federative_unit_id=`, `/neighborhood?city_id=`, `/educational_stage` |

Pelo lado das turmas:

| Passo | Chamada |
| --- | --- |
| Detalhe da turma | `GET /capacitation/group/search` com `{"field":"id","value":<group_id>}` e `with:["course.category.type","unit","place","satisfactionSurvey.survey",…]` — traz a **pesquisa de satisfação da turma com perguntas e IDs das alternativas** |
| Matriculados da turma | `GET /capacitation/enrollment/search` com `{"field":"group_id","value":<group_id>}`, `with-has:["group","frequenter.user.person"]`, `with:["frequencies.grid","certificates.template","assessment…"]`, `max:100` |

## De onde sai cada resposta do perfil (implementado em `san2.py`)

| Pergunta da pesquisa | Campo no SAN2 | Regra |
| --- | --- | --- |
| Sexo | `person.gender` (`M`/`F`) | M → Masculino, F → Feminino |
| Faixa etária | `person.birthdate` (`dd/mm/aaaa`) | idade hoje: ≤5 / 6–11 / 12–17 / 18–60 / ≥61 |
| Período | `frequencies[].grid` da matrícula (ou `capacitation/grid/search` da turma, se não houver presença) | aula em sábado/domingo → Final de Semana; senão pelo horário de início mais frequente: <12h Manhã, <18h Tarde, senão Noite |
| Atividade | `course.workload` (horas-aula) | ≤ 6 → Oficina; > 6 → Curso |
| Aluno da rede municipal | `person.educational_institution.type.name` — só vem com `with: ["person.educationalInstitution.type"]` (é o que a tela **Editar** pede; a tela Visualizar não carrega e mostra "Não estuda") | contém "municipal" → Sim; qualquer outro ou vazio → Não |
| Login da pesquisa | `user.username` | direto |
| Senha da pesquisa | não existe na API | a senha padrão da unidade (configurada na página, guardada só no `config.json`); se o site recusar o login, a conta é **ignorada** no lote |

Importação por turma: `matriculados(group_id)` sem `canceled_at`. Por
frequentador: a matrícula mais recente cuja turma já começou (senão a mais
recente) define período e atividade.

## Pesquisa de satisfação (lado do site de pesquisas)

- `POST /oauth2/token` com `grant_type=frequenter`, `client_id`/`client_secret` do app de pesquisas (estão no JS público do site), `username`, `password`, `scope=me_info,me_survey_to_answer,me_store_survey_answers`.
- `GET /user/me/satisfaction-survey-to-answer?group_id=` → turma + pesquisa.
- `POST /user/me/survey-answers` com `{questions:{<qid>:{answer:{alternative_id}}}, unit_id, location_id:1, survey_id, group_id}`.
- A tela de login aceita `?user=<access_token>&group_id=<id>&redirect=<url>` — entra direto com um token já emitido para o frequentador.
