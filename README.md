# auto-san-pesquisas

Automação que entra em <https://pesquisas.navedoconhecimento.rio/>, faz login e
responde as pesquisas de satisfação pendentes.

- As 5 perguntas de perfil (**Sexo**, **aluno da rede municipal**, **período**,
  **faixa etária** e **atividade**) são respondidas por você antes de rodar e
  ficam guardadas no `config.json`.
- Todas as outras perguntas recebem **Muito Satisfeito** (ou o que você escolher).
- Se houver mais de uma pesquisa pendente, todas são respondidas em sequência.
- Dá para cadastrar **várias contas** e responder todas de uma vez.

Há três jeitos de usar: o executável para Windows (atalho na área de trabalho),
a interface web pelo Python, ou a linha de comando.

## Windows 11: executável + atalho na área de trabalho

Requisito: Python 3.10+ instalado (<https://www.python.org/downloads/>, marque
"Add python.exe to PATH"). Depois, na pasta do projeto, dê **dois cliques em
`construir_windows.bat`**. Ele:

1. cria o ambiente Python (`.venv`) e instala `playwright` + `pyinstaller`;
2. baixa o Chromium para **dentro** do pacote (fica embutido no programa);
3. gera `dist\PesquisasNave\PesquisasNave.exe` (~550 MB por causa do Chromium);
4. cria o atalho **Pesquisas Nave** na área de trabalho, com ícone.

O atalho abre uma janela de console (o registro aparece nela) e a interface no
navegador. Fechar a janela encerra o programa. `config.json`, `contas.json` e
as capturas ficam na mesma pasta do `.exe`.

Observações:

- O `.exe` não é assinado, então o SmartScreen pode perguntar na primeira vez
  ("Mais informações" → "Executar assim mesmo").
- Se preferir não compilar, `iniciar.bat` faz o mesmo rodando direto pelo Python
  (prepara o ambiente na primeira vez). Um atalho para ele também funciona.
- A receita do PyInstaller está em `pesquisas.spec`; ela foi validada gerando o
  mesmo pacote no Linux.

## Interface web (Linux/macOS/Windows)

```bash
python3 servidor.py
```

Abre <http://127.0.0.1:8765/> no navegador. Na página:

- **Acesso** — usuário e senha (com opção de guardar a senha no `config.json`).
- **Respostas de perfil** — as 5 perguntas; valem para a conta acima e como
  padrão para a lista de contas.
- **Demais perguntas** — o que todas as outras perguntas recebem.
- **Várias contas** — cole uma conta por linha (`usuário;senha`) e clique em
  **Adicionar em massa**. Na mesma linha você pode informar as respostas de
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

## Instalação manual (Linux/macOS)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
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

## Testes

`teste_mock.py` usa o frontend real do site com a API simulada (nada é enviado
de verdade); `teste_servidor.py` testa a interface web com a automação simulada:

```bash
.venv/bin/python -m unittest discover -s testes -p "teste_*.py" -v
```
