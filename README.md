# 📈 Portfolio Tracker B3

Acompanhamento automático de carteira de ações da B3 com bot no Telegram para consultas em tempo real.

---

## 🚀 Funcionalidades

- 📥 Importação da carteira via Excel (.xlsx) exportado da B3
- 💹 Atualização automática de cotações a cada 15 minutos via [brapi.dev](https://brapi.dev)
- 🤖 Bot no Telegram com comandos de consulta
- 📊 Cálculo de preço médio ponderado, lucro/prejuízo e rentabilidade
- 💰 Registro de proventos (dividendos, JCP, rendimentos de FII)
- 🔔 Alertas de compra/venda baseados no preço médio (±5%)
- 📄 Relatório semanal em PDF enviado pelo Telegram
- 📎 Atualização da carteira enviando o `.xlsx` direto no chat do bot
- 🏁 Resultado realizado por ativo (incluindo ativos já vendidos)

---

## 🏗️ Estrutura do Projeto

```
portfolio_tracker/
├── database/                    # Banco de dados SQLite (ignorado pelo git)
├── scripts/
│   ├── criar_banco.py           # Cria o banco do zero
│   ├── importar_carteira.py     # Importa o Excel da B3 pro banco
│   ├── atualizar_cotacoes.py    # Busca cotações na brapi.dev
│   ├── bot_telegram.py          # Bot do Telegram
│   ├── alerta_diario.py         # Envia alertas automáticos
│   └── relatorio.py             # Gera relatório semanal em PDF
├── logs/                        # Logs de execução (ignorado pelo git)
├── .env.example                 # Exemplo de configuração de credenciais
├── .gitignore
└── README.md
```

---

## ⚙️ Requisitos

- Python 3.10+
- SQLite3

### Instalação das dependências

```bash
pip install pandas openpyxl requests fpdf2 feedparser python-dotenv
```

---

## 🛠️ Configuração

### 1. Clone o repositório

```bash
git clone https://github.com/nervos0x1/portfolio_trackerB3.git
cd portfolio-tracker
```

### 2. Configure as credenciais

```bash
cp .env.example .env
nano .env
```

Preencha o arquivo `.env`:

```env
BRAPI_TOKEN=seu_token_aqui
BOT_TOKEN=seu_token_do_botfather_aqui
ALLOWED_CHATID=seu_chat_id_aqui
```

- **BRAPI_TOKEN** → crie uma conta gratuita em [brapi.dev](https://brapi.dev)
- **BOT_TOKEN** → crie um bot no Telegram via [@BotFather](https://t.me/BotFather)
- **ALLOWED_CHATID** → seu chat_id do Telegram (acesse `https://api.telegram.org/botSEU_TOKEN/getUpdates` após mandar uma mensagem ao bot)

### 3. Crie o banco de dados

```bash
mkdir -p database logs
cd database
python3 ../scripts/criar_banco.py
cd ..
```

### 4. Importe sua carteira

Exporte o arquivo de movimentações no site da B3 e importe:

```bash
python3 scripts/importar_carteira.py movimentacao.xlsx
```

### 5. Configure o cron

```bash
crontab -e
```

Adicione:

```
# Cotações a cada 15 minutos
*/15 * * * * python3 /caminho/para/scripts/atualizar_cotacoes.py

# Alerta diário às 9h nos dias úteis
0 9 * * 1-5 python3 /caminho/para/scripts/alerta_diario.py
```

### 6. Inicie o bot

```bash
python3 scripts/bot_telegram.py
```

Ou configure como serviço no systemd para rodar em background automaticamente.

---

## 🤖 Comandos do Bot

| Comando | Descrição |
|---|---|
| `/start` | Apresentação e lista de comandos |
| `/carteira` | Resumo completo com cotação atual e P&L |
| `/cotacao TICKER` | Cotação detalhada de um ativo (ex: `/cotacao ITUB4`) |
| `/resumo` | Patrimônio total agrupado por tipo de ativo |
| `/proventos` | Total de dividendos e rendimentos recebidos |
| `/alerta` | Análise de compra/venda baseada no preço médio |
| `/resultado` | Lucro/prejuízo realizado e proventos por ativo |
| `/relatorio` | Gera e envia PDF com resumo completo da carteira |
| `/ajuda` | Lista de comandos |

> 📎 Envie o arquivo `.xlsx` exportado da B3 diretamente no chat para atualizar a carteira automaticamente.

---

## 📋 Tabelas do Banco

| Tabela | Descrição |
|---|---|
| `acoes` | Posição atual de cada ativo |
| `movimentacoes` | Histórico completo de operações |
| `cotacoes` | Preços atualizados pela API |
| `proventos` | JCP, dividendos e rendimentos |
| `alertas` | Alertas de preço |
| `carteira_resumo` | View com posição + cotação + P&L |
| `cotacao_atual` | View com última cotação por ticker |

---

## 🔄 Como atualizar a carteira

Envie o arquivo `.xlsx` exportado da B3 diretamente no chat do bot no Telegram. O bot importa automaticamente e responde com o resumo atualizado.

Ou via terminal:

```bash
python3 scripts/importar_carteira.py movimentacao.xlsx
```

---

## ⚠️ Aviso

As análises e alertas gerados são **meramente informativos** e não constituem recomendação de investimento.
