# App Store Connect MCP Server

Servidor MCP (Model Context Protocol) para puxar dados de analytics e relatórios do App Store Connect, espelhando a arquitetura do [mcp-google-play-console](https://github.com/brunosemfio/mcp-google-play-console) (Python + FastMCP + credenciais por variável de ambiente).

## Fontes de dados

| Fonte | O que cobre |
|---|---|
| [Analytics Reports API](https://developer.apple.com/documentation/appstoreconnectapi/analytics) | Sessões, dispositivos ativos, instalações e exclusões, crashes, impressões e páginas de produto, compras e assinaturas, uso de frameworks, métricas de performance — em TSV diário, semanal e mensal |
| [Sales and Trends](https://developer.apple.com/documentation/appstoreconnectapi/download-sales-and-trends-reports) | Unidades vendidas, proceeds, instalações, assinaturas, assinantes, resgates de offer code |
| Finance Reports | Pagamentos e proceeds por mês fiscal e região |
| Customer Reviews / perfPowerMetrics | Avaliações da App Store e métricas de launch, hangs, memória, disco e bateria do Xcode |

## Ferramentas expostas

**Descoberta**
- `list_apps` — lista os apps que a chave enxerga (use primeiro, para descobrir os app IDs)
- `list_report_categories` — descreve as categorias de relatório e o fluxo da Analytics Reports API

**Analytics Reports**
- `fetch_analytics_report` — caminho completo em uma chamada: app → request → relatório → instância → linhas já parseadas
- `list_report_requests` — requests de relatório existentes do app
- `create_report_request` — **única operação de escrita**; habilita a geração de relatórios (uma vez por app)
- `list_reports` — relatórios disponíveis dentro de um request, com filtro por categoria e nome
- `list_report_instances` — instâncias por granularidade (`DAILY`/`WEEKLY`/`MONTHLY`) e data de processamento
- `list_report_segments` — segmentos de uma instância, com a URL de download (válida por 5 minutos)
- `download_report_instance` — baixa todos os segmentos de uma instância e devolve as linhas em JSON

**Vendas, finanças, avaliações e performance**
- `list_sales_report_types` — combinações válidas de `reportType`/`reportSubType`/`frequency`/`version`
- `download_sales_report` — relatório de Sales and Trends já descompactado e parseado
- `download_finance_report` — relatório financeiro do mês fiscal
- `list_customer_reviews` — avaliações da App Store, com filtro por nota e território
- `get_perf_power_metrics` — métricas de energia e performance das versões recentes

Todas as ferramentas são somente-leitura (`readOnlyHint`), exceto `create_report_request`.

## Configuração

### 1. Crie uma chave da App Store Connect API

Em [App Store Connect → Users and Access → Integrations → App Store Connect API](https://appstoreconnect.apple.com/access/integrations/api), gere uma chave e baixe o arquivo `AuthKey_XXXXXXXXXX.p8` (só é possível baixar uma vez). Anote o **Key ID** e o **Issuer ID**.

O papel da chave define o que dá para ler:

| Dado | Papel mínimo |
|---|---|
| Analytics Reports | Admin, App Manager, Developer ou Marketing |
| Sales and Trends | Sales ou Finance |
| Finance Reports | Finance |
| Customer Reviews | Admin, App Manager, Developer ou Marketing |

### 2. Variáveis de ambiente

```bash
export APP_STORE_CONNECT_KEY_ID=2X9R4HXF34
export APP_STORE_CONNECT_ISSUER_ID=57246542-96fe-1a63-e053-0824d011072a
export APP_STORE_CONNECT_PRIVATE_KEY_PATH=~/.appstoreconnect/private_keys/AuthKey_2X9R4HXF34.p8
export APP_STORE_CONNECT_VENDOR_NUMBER=12345678   # só para sales/finance
```

Em vez de exportar (ou de repetir `--env` no registro do MCP), dá para deixar
tudo num arquivo `.env` — o servidor lê o primeiro que encontrar:

1. `$APP_STORE_CONNECT_ENV_FILE`, se definido;
2. `~/.config/app-store-connect/.env`;
3. `.env` no diretório de trabalho.

```bash
mkdir -p ~/.config/app-store-connect
cat > ~/.config/app-store-connect/.env <<'ENV'
APP_STORE_CONNECT_KEY_ID=2X9R4HXF34
APP_STORE_CONNECT_ISSUER_ID=57246542-96fe-1a63-e053-0824d011072a
APP_STORE_CONNECT_PRIVATE_KEY_PATH=/Users/voce/.appstoreconnect/private_keys/AuthKey_2X9R4HXF34.p8
APP_STORE_CONNECT_VENDOR_NUMBER=12345678
ENV
chmod 600 ~/.config/app-store-connect/.env
```

Variáveis já presentes no ambiente têm prioridade sobre o arquivo, o arquivo é
lido uma vez por processo e a ausência dele não é erro. Aceita `export ` no
começo da linha, comentários com `#` e valores entre aspas. Use caminho
absoluto no `.p8`: o `~` não é expandido dentro do arquivo.

- Chaves **individuais** (sem Issuer ID) funcionam: deixe `APP_STORE_CONNECT_ISSUER_ID` sem definir e o token é assinado com `sub: user`.
- Em vez do caminho, dá para passar o PEM inline em `APP_STORE_CONNECT_PRIVATE_KEY`.
- O vendor number aparece em App Store Connect → Payments and Financial Reports.

### 3. Habilite os relatórios de analytics do app

A Apple só gera relatórios depois que existe um *report request*. Uma vez por app:

```
create_report_request(app_id="1234567890", access_type="ONGOING")
```

`ONGOING` passa a gerar dados **a partir do dia seguinte**; `ONE_TIME_SNAPSHOT` devolve o histórico disponível de uma vez. As instâncias expiram depois de um tempo — baixe logo após listar.

## Relatórios mais usados

`list_report_categories` devolve esta lista; use `list_reports` para o conjunto completo do app (são ~156, a maioria de `FRAMEWORK_USAGE`).

| Categoria | Relatórios |
|---|---|
| `APP_USAGE` | App Sessions Standard/Detailed, App Store Installation and Deletion Standard/Detailed, App Crashes, Platform App Installs |
| `APP_STORE_ENGAGEMENT` | App Store Discovery and Engagement Standard/Detailed, App Store Web Preview Engagement, Retention Messaging |
| `COMMERCE` | App Downloads Standard/Detailed, App Store Purchases, App Store Subscription Event/State Report |
| `PERFORMANCE` | App Install Performance, Networking Connection Activity, CAMetalLayer Performance, Bluetooth System Wakes |

`Standard` é pré-agregado; `Detailed` quebra o mesmo dado por mais dimensões e é bem maior.

## Instalação e uso

### Direto do GitHub (recomendado)

Com [uv](https://docs.astral.sh/uv/) instalado:

```bash
uvx --from git+https://github.com/brunosemfio/mcp-app-store-connect.git app-store-connect-mcp
```

Registrando no Claude Code:

```bash
claude mcp add app-store-connect \
  -- uvx --from git+https://github.com/brunosemfio/mcp-app-store-connect.git app-store-connect-mcp
```

(com o `.env` acima; sem ele, passe cada valor com `--env APP_STORE_CONNECT_KEY_ID=...`)

Ou em um `mcp.json` genérico:

```json
{
  "mcpServers": {
    "app-store-connect": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/brunosemfio/mcp-app-store-connect.git",
        "app-store-connect-mcp"
      ],
      "env": {
        "APP_STORE_CONNECT_ENV_FILE": "/Users/voce/.config/app-store-connect/.env"
      }
    }
  }
}
```

O `uvx` faz cache do build: para atualizar após novos commits, rode uma vez com `--refresh`. Para fixar uma versão, aponte para uma tag ou commit: `git+https://...@<tag-ou-sha>`.

### A partir de um clone local (desenvolvimento)

```bash
git clone https://github.com/brunosemfio/mcp-app-store-connect.git
cd appstoreconnect-mcp
python -m venv .venv && source .venv/bin/activate
pip install -e .
app-store-connect-mcp            # stdio (padrão)
app-store-connect-mcp --transport streamable-http --port 8000
```

## Desenvolvimento

```bash
uv sync --extra dev          # ou: pip install -e '.[dev]'
uv run pytest                # testes unitários (offline, com fakes)
uv run ruff check app_store_connect_mcp tests
uv run mypy app_store_connect_mcp

# Testes de integração (batem na API real; precisam de credenciais):
APP_STORE_CONNECT_KEY_ID=... APP_STORE_CONNECT_ISSUER_ID=... \
APP_STORE_CONNECT_PRIVATE_KEY_PATH=... uv run pytest -m integration
```

O CI (GitHub Actions, branch `main`) roda ruff, mypy e a suíte unitária com cobertura mínima de 65% em Python 3.10 e 3.12.

## Exemplos de perguntas

- "Quantas sessões o app teve por dia no último relatório diário?"
- "Baixe o relatório de instalações e exclusões e compare com o mês passado."
- "Quantas unidades vendemos em 2026-08 e quanto entrou de proceeds?"
- "Quais as avaliações 1 estrela mais recentes no Brasil?"

## Notas

- O token JWT é ES256, vive 15 minutos e é reaproveitado entre chamadas — bem abaixo do limite de 20 minutos da Apple.
- Os relatórios de analytics vêm como TSV comprimido em gzip; sales e finance também. O servidor descompacta, detecta o separador (tab ou vírgula) e devolve as linhas em JSON, com `truncated` quando `max_rows` é atingido.
- `max_bytes` é aplicado no download e de novo após a descompressão, então um gzip pequeno que explode em disco não passa.
- Relatórios grandes vêm partidos em vários segmentos; `download_report_instance` e `fetch_analytics_report` juntam todos até o limite de linhas.
- As URLs de segmento expiram em 5 minutos: liste e baixe na mesma conversa.
- Um request `ONGOING` recém-criado não tem dados no mesmo dia, e a Apple para de gerar relatórios de requests inativos — `stoppedDueToInactivity` sinaliza isso em `list_report_requests`.
- Datas de Sales and Trends seguem a frequência: `YYYY-MM-DD` (diário/semanal), `YYYY-MM` (mensal), `YYYY` (anual); o servidor valida o formato antes de chamar a API.
- Fora `create_report_request`, nada aqui escreve no App Store Connect.
