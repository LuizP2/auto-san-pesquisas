# auto-san-pesquisas

Automação que entra em <https://pesquisas.navedoconhecimento.rio/>, faz login e
responde as pesquisas de satisfação pendentes.

- As 5 perguntas de perfil (**Sexo**, **aluno da rede municipal**, **período**,
  **faixa etária** e **atividade**) são respondidas por você antes de rodar e
  ficam guardadas no `config.json`.
- Todas as outras perguntas recebem **Muito Satisfeito** (ou o que você escolher).
- Se houver mais de uma pesquisa pendente, todas são respondidas em sequência.
- Dá para cadastrar **várias contas** e responder todas de uma vez.

## Instalação: pasta `setup/`

Dois scripts, cada um com uma versão para Windows (dois cliques no `.bat`) e
para Linux (`./setup/xxx.sh`):

| Para quem | Windows | Linux | O que faz |
| --- | --- | --- | --- |
| **Staff** | `setup\staff.bat` | `./setup/staff.sh` | Prepara a máquina (instala o Python pelo `winget` se faltar, cria o `.venv`, instala o Playwright e baixa o Chromium), cria o atalho **Pesquisas Nave** na área de trabalho e abre a interface no navegador. Pode rodar de novo à vontade: só refaz o que faltar. |
| **Frequentadores** | `setup\frequentador.bat` | `./setup/frequentador.sh` | Cria o atalho **Pesquisa Nave** na área de trabalho, que abre o site da pesquisa no navegador padrão para o aluno responder sozinho, e já abre o site. Não precisa de Python. |

A lógica do de staff está em `setup/staff.py` (roda nos dois sistemas; os
`.bat`/`.sh` só chamam ele). Opções: `--so-instalar` (não cria atalho nem
abre), `--sem-atalho`, e qualquer outra vai para o servidor (`--porta 8080`,
`--sem-abrir`). Depois da instalação, o atalho **Pesquisas Nave** (ou
`iniciar.bat` / `iniciar.sh`) abre a interface direto.

Se algo falhar, o script diz exatamente qual comando falhou — copie a mensagem.

### Opcional: executável para Windows

`construir_windows.bat` roda o setup acima e ainda gera
`dist\PesquisasNave\PesquisasNave.exe` com o Chromium embutido (~550 MB) e um
atalho para ele. Só vale a pena para levar o programa a uma máquina **sem**
Python; o `.exe` não é assinado, então o SmartScreen pode perguntar na primeira
vez. A receita está em `pesquisas.spec` e foi validada gerando o mesmo pacote
no Linux.

## Interface web (Linux/macOS/Windows)

```bash
python3 servidor.py
```

Abre <http://127.0.0.1:8765/> no navegador. Na página:

- **Acesso** — usuário e senha (com opção de guardar a senha no `config.json`).
- **Respostas de perfil** — as 5 perguntas; valem para a conta acima e como
  padrão para a lista de contas.
- **Demais perguntas** — o que todas as outras perguntas recebem.
- **Várias contas → Importar do SAN2** — informe seu usuário/senha de staff do
  SAN2, escolha **Turma** (código, ex. `PDM.IKCC.P1.7`) ou **Frequentador**
  (login ou nome) e clique em **Buscar e adicionar**. O programa entra no SAN2
  (navegador invisível, token guardado em memória por 8 h), puxa os
  matriculados e deduz as 5 respostas do cadastro: sexo, faixa etária (data
  de nascimento), período (horário das aulas), atividade (carga horária ≤ 6 h
  = oficina) e rede municipal (tipo da instituição de ensino). A senha de cada
  conta é a **senha padrão** que a unidade usa (você informa uma vez na página;
  fica só no seu `config.json`); na execução, quem tiver senha diferente é
  **ignorado** e o resumo diz quem foi. As regras estão em
  `docs/san2-fluxo.md`.
- **Várias contas → Ou cole uma lista** — uma conta por linha (`usuário;senha`)
  e **Adicionar em massa**. Na mesma linha você pode informar as respostas de
  perfil daquela pessoa: `usuário;senha;Sexo;Rede municipal;Período;Faixa
  etária;Atividade` (aceita abreviações, sem acento, e colunas separadas por
  Tab — dá para colar direto de uma planilha). O que faltar usa as respostas
  marcadas acima. As linhas com problema ficam na caixa com a explicação. A
  lista aparece numa tabela onde cada resposta pode ser ajustada, e fica salva
  em `contas.json`.
- **Execução** — **Executar conta acima** ou **Executar lista (N contas)**. O
  progresso aparece ao vivo no painel "Registro"; no lote, cada conta ganha um
  cabeçalho e, se falhar, um link "ver tela" com a captura do site. As demais
  contas continuam; no fim há um resumo com as falhas.

Opções: "Mostrar o navegador" deixa o Chromium visível (na conta única, se der
erro ou em "só preencher", a janela fica aberta para você terminar à mão —
clique em **Fechar navegador** quando acabar); "Só preencher, sem enviar"
serve para conferir. O servidor só escuta em `127.0.0.1`. Flags:
`--porta 8080`, `--sem-abrir`.

## Linha de comando

```bash
python3 pesquisa.py
```

Na primeira execução pergunta usuário, senha e as 5 respostas e salva em
`config.json` (a senha só se você aceitar; senão é pedida a cada vez ou lida da
variável `SAN_SENHA`). Opções: `--configurar`, `--sem-enviar`, `--headless`,
`--config ARQ`. Se algo der errado, salva `erro.png`, mostra o motivo e deixa o
navegador aberto para você terminar à mão.

## Instalação manual

Equivale ao `setup/staff.py --so-instalar`:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt      # Windows: .venv\Scripts\pip
.venv/bin/playwright install chromium
```

Os scripts detectam o `.venv` sozinhos: `python3 servidor.py` funciona mesmo
com o Python do sistema.

## config.json

Veja `config.example.json`. As chaves de `respostas` são comparadas com o texto
da pergunta ignorando acentos, maiúsculas e pontuação. Para dar uma resposta
diferente da padrão a qualquer outra pergunta, acrescente-a ali:

```json
"Qual o seu grau de satisfação com relação ao número de cursos/oficinas oferecidos?": "Satisfeito"
```

Se alguma pergunta pedir justificativa ou for discursiva, o script avisa e
para; defina `"justificativa"` ou acrescente a pergunta em `respostas`.

## Monitor de rede

`python3 monitor.py` abre um navegador que registra toda requisição que os
sites fazem (método, URL, corpo enviado com senhas mascaradas, resposta) em
`monitor/<data-hora>/requisicoes.jsonl`, com resumo dos endpoints ao fechar.
Foi assim que o fluxo do SAN2 foi mapeado.

## Testes

`teste_mock.py` usa o frontend real do site com a API simulada (nada é enviado
de verdade); `teste_servidor.py` testa a interface web com a automação
simulada; `teste_san2.py` cobre as regras de dedução; `teste_monitor.py` o
monitor:

```bash
.venv/bin/python -m unittest discover -s testes -p "teste_*.py" -v
```
