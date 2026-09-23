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

## Pré-requisitos

- [uv](https://docs.astral.sh/uv/): baixa e executa o servidor. Se a máquina não tiver Python 3.10 ou mais novo, o `uv` baixa um sozinho.
- [git](https://git-scm.com/): o `uvx` usa o git para baixar o código deste repositório.

**macOS**, com [Homebrew](https://brew.sh/):

```bash
brew install uv git
```

Sem Homebrew, instale o uv com `curl -LsSf https://astral.sh/uv/install.sh | sh` e o git com `xcode-select --install`.

**Windows**, no PowerShell:

```powershell
winget install --id=astral-sh.uv -e
winget install --id=Git.Git -e
```

Depois de instalar, feche e abra o PowerShell de novo. Sem isso, o terminal não encontra os comandos `uv` e `git`.

## Configuração

### 1. Crie uma chave da App Store Connect API

Em [App Store Connect → Users and Access → Integrations → App Store Connect API](https://appstoreconnect.apple.com/access/integrations/api), gere uma chave e baixe o arquivo `AuthKey_XXXXXXXXXX.p8` (só é possível baixar uma vez). Anote o **Key ID** e o **Issuer ID**.

Guarde o `.p8` num local fixo e anote o caminho completo. Exemplos: `/Users/voce/.appstoreconnect/private_keys/AuthKey_2X9R4HXF34.p8` no macOS e `C:\Users\voce\.appstoreconnect\private_keys\AuthKey_2X9R4HXF34.p8` no Windows.

O papel da chave define o que dá para ler:

| Dado | Papel mínimo |
|---|---|
| Analytics Reports | Admin, App Manager, Developer ou Marketing |
| Sales and Trends | Sales ou Finance |
| Finance Reports | Finance |
| Customer Reviews | Admin, App Manager, Developer ou Marketing |

### 2. Credenciais

O servidor lê as credenciais destas variáveis de ambiente:

| Variável | Valor |
|---|---|
| `APP_STORE_CONNECT_KEY_ID` | Key ID da chave, ex. `2X9R4HXF34` |
| `APP_STORE_CONNECT_ISSUER_ID` | Issuer ID, ex. `57246542-96fe-1a63-e053-0824d011072a` |
| `APP_STORE_CONNECT_PRIVATE_KEY_PATH` | Caminho completo do `.p8` |
| `APP_STORE_CONNECT_VENDOR_NUMBER` | Vendor number; só é necessário para sales e finance |

Os valores vão no `--env` do Claude Code ou no bloco `env` do Claude Desktop quando você registrar o servidor no cliente MCP (seção [Instalação e uso](#instalação-e-uso)).

- Chaves **individuais** (sem Issuer ID) funcionam: deixe `APP_STORE_CONNECT_ISSUER_ID` sem definir e o servidor assina o token com `sub: user`.
- Em vez do caminho, dá para passar o PEM inline em `APP_STORE_CONNECT_PRIVATE_KEY`.
- O vendor number aparece em App Store Connect → Payments and Financial Reports.

**Arquivo `.env` (opcional):** para não repetir os valores em cada cliente MCP, grave as variáveis num arquivo `.env`. O servidor lê o primeiro arquivo que encontrar:

1. `$APP_STORE_CONNECT_ENV_FILE`, se definido;
2. `~/.config/app-store-connect/.env`;
3. `.env` no diretório de trabalho.

No macOS, no Terminal:

```bash
mkdir -p ~/.config/app-store-connect
cat > ~/.config/app-store-connect/.env <<'ENV'
APP_STORE_CONNECT_KEY_ID=2X9R4HXF34
APP_STORE_CONNECT_ISSUER_ID=57246542-96fe-1a63-e053-0824d011072a
APP_STORE_CONNECT_PRIVATE_KEY_PATH=~/.appstoreconnect/private_keys/AuthKey_2X9R4HXF34.p8
APP_STORE_CONNECT_VENDOR_NUMBER=12345678
ENV
chmod 600 ~/.config/app-store-connect/.env
```

No Windows, no PowerShell:

```powershell
New-Item -ItemType Directory -Force "$HOME\.config\app-store-connect" | Out-Null
@"
APP_STORE_CONNECT_KEY_ID=2X9R4HXF34
APP_STORE_CONNECT_ISSUER_ID=57246542-96fe-1a63-e053-0824d011072a
APP_STORE_CONNECT_PRIVATE_KEY_PATH=~/.appstoreconnect/private_keys/AuthKey_2X9R4HXF34.p8
APP_STORE_CONNECT_VENDOR_NUMBER=12345678
"@ | Set-Content -Encoding utf8 "$HOME\.config\app-store-connect\.env"
```

Variáveis já definidas no ambiente, inclusive pelo `--env` ou pelo `env` do cliente MCP, têm prioridade sobre o arquivo. O servidor lê o arquivo uma vez por processo, e a ausência do arquivo não é erro. O arquivo aceita `export ` no começo da linha, comentários com `#` e valores entre aspas. O servidor expande o `~` no caminho do `.p8`.

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

Com os [pré-requisitos](#pré-requisitos) instalados, não é preciso clonar nada: o `uvx` baixa, instala e executa o servidor a partir deste repositório. Para testar, rode o comando abaixo, que é igual no macOS e no Windows:

```bash
uvx --from git+https://github.com/brunosemfio/mcp-app-store-connect.git app-store-connect-mcp
```

Se o servidor subir sem erro, ele fica aguardando um cliente MCP. Encerre com Ctrl+C.

#### Claude Code

1. Registre o servidor. O `--scope user` deixa o servidor disponível em qualquer pasta. Sem o `--scope user`, o servidor só aparece na pasta onde você rodou o comando.

   **macOS**, no Terminal:

   ```bash
   claude mcp add --scope user app-store-connect \
     --env APP_STORE_CONNECT_KEY_ID=2X9R4HXF34 \
     --env APP_STORE_CONNECT_ISSUER_ID=57246542-96fe-1a63-e053-0824d011072a \
     --env APP_STORE_CONNECT_PRIVATE_KEY_PATH=/Users/voce/.appstoreconnect/private_keys/AuthKey_2X9R4HXF34.p8 \
     --env APP_STORE_CONNECT_VENDOR_NUMBER=12345678 \
     -- uvx --from git+https://github.com/brunosemfio/mcp-app-store-connect.git app-store-connect-mcp
   ```

   **Windows**, no PowerShell:

   ```powershell
   claude mcp add --scope user app-store-connect `
     --env "APP_STORE_CONNECT_KEY_ID=2X9R4HXF34" `
     --env "APP_STORE_CONNECT_ISSUER_ID=57246542-96fe-1a63-e053-0824d011072a" `
     --env "APP_STORE_CONNECT_PRIVATE_KEY_PATH=C:\Users\voce\.appstoreconnect\private_keys\AuthKey_2X9R4HXF34.p8" `
     --env "APP_STORE_CONNECT_VENDOR_NUMBER=12345678" `
     -- uvx --from git+https://github.com/brunosemfio/mcp-app-store-connect.git app-store-connect-mcp
   ```

   - Troque os valores de `--env` pelos da sua chave.
   - Com chave individual, remova a linha do `APP_STORE_CONNECT_ISSUER_ID`.
   - Sem sales e finance, remova a linha do `APP_STORE_CONNECT_VENDOR_NUMBER`.
   - Com o arquivo `.env` da seção 2, remova todas as linhas `--env`.

2. Rode `claude mcp list`. O `app-store-connect` deve aparecer como conectado.

3. Numa conversa nova do Claude Code, peça "liste os apps que você enxerga no App Store Connect". Se o servidor estiver funcionando, o Claude chama a ferramenta `list_apps` e mostra os apps. Se der erro, digite `/mcp` dentro do Claude Code para ver o status do servidor.

Para trocar algum valor, remova o servidor com `claude mcp remove --scope user app-store-connect` e registre de novo pelo passo 1.

#### Claude Desktop

1. Descubra o caminho completo do `uvx`. O Claude Desktop aberto pelo Dock ou pelo menu Iniciar pode não enxergar o PATH do terminal e falhar com `spawn uvx ENOENT`. Com o caminho completo, o app não depende do PATH.
   - macOS: rode `which uvx`. Em Macs com Apple Silicon e Homebrew, o resultado costuma ser `/opt/homebrew/bin/uvx`.
   - Windows: rode `where.exe uvx` no PowerShell.

2. Abra o arquivo de configuração do Claude Desktop. Pelo app, o caminho é **Settings → Developer → Edit Config**. Pelo terminal, os comandos abaixo criam o arquivo se ele ainda não existir e não apagam um arquivo existente.

   **macOS**, no Terminal (abre no TextEdit):

   ```bash
   mkdir -p ~/Library/Application\ Support/Claude
   touch ~/Library/Application\ Support/Claude/claude_desktop_config.json
   open -e ~/Library/Application\ Support/Claude/claude_desktop_config.json
   ```

   **Windows**, no PowerShell (abre no Bloco de Notas):

   ```powershell
   $config = "$env:APPDATA\Claude\claude_desktop_config.json"
   if (-not (Test-Path $config)) { New-Item -ItemType File -Force $config | Out-Null }
   notepad $config
   ```

3. Adicione o servidor ao arquivo e salve. Se o arquivo estiver vazio, cole o bloco inteiro abaixo. Se o arquivo já tiver `mcpServers`, inclua só a entrada `app-store-connect` dentro dele. Se o arquivo tiver outras chaves mas não tiver `mcpServers`, acrescente a chave `mcpServers` ao objeto principal.

   ```json
   {
     "mcpServers": {
       "app-store-connect": {
         "command": "/opt/homebrew/bin/uvx",
         "args": [
           "--from",
           "git+https://github.com/brunosemfio/mcp-app-store-connect.git",
           "app-store-connect-mcp"
         ],
         "env": {
           "APP_STORE_CONNECT_KEY_ID": "2X9R4HXF34",
           "APP_STORE_CONNECT_ISSUER_ID": "57246542-96fe-1a63-e053-0824d011072a",
           "APP_STORE_CONNECT_PRIVATE_KEY_PATH": "/Users/voce/.appstoreconnect/private_keys/AuthKey_2X9R4HXF34.p8",
           "APP_STORE_CONNECT_VENDOR_NUMBER": "12345678"
         }
       }
     }
   }
   ```

   - Troque `/opt/homebrew/bin/uvx` pelo caminho do passo 1 e os valores de `env` pelos da sua chave.
   - No Windows, dobre as barras invertidas nos dois caminhos, como o JSON exige. Exemplo: `"C:\\Users\\voce\\.appstoreconnect\\private_keys\\AuthKey_2X9R4HXF34.p8"`.
   - Com chave individual, remova a linha do `APP_STORE_CONNECT_ISSUER_ID`.
   - Sem sales e finance, remova a linha do `APP_STORE_CONNECT_VENDOR_NUMBER` e apague a vírgula que sobrar no fim da linha de cima.
   - Com o arquivo `.env` da seção 2, remova o bloco `env` inteiro e apague a vírgula que sobrar depois do `]` de `args`.

4. Encerre o Claude Desktop e abra de novo. Fechar a janela não basta, porque o app continua rodando com a configuração antiga. No macOS, use Cmd+Q. No Windows, clique com o botão direito no ícone do Claude na bandeja do sistema e escolha Sair.

5. Numa conversa nova, peça "liste os apps que você enxerga no App Store Connect". Se o servidor estiver funcionando, o Claude chama a ferramenta `list_apps` e mostra os apps. Se der erro, veja o log do servidor:
   - macOS: `~/Library/Logs/Claude/mcp-server-app-store-connect.log`
   - Windows: `%APPDATA%\Claude\logs\mcp-server-app-store-connect.log`

Outros clientes MCP aceitam o mesmo bloco `mcpServers` do passo 3 no arquivo de configuração deles.

O `uvx` faz cache do build: para atualizar após novos commits, rode o comando uma vez com `--refresh`. Para fixar uma versão, aponte para uma tag ou commit: `git+https://...@<tag-ou-sha>`.

### A partir de um clone local (desenvolvimento)

Os comandos são iguais no macOS e no Windows:

```bash
git clone https://github.com/brunosemfio/mcp-app-store-connect.git
cd mcp-app-store-connect
uv sync
uv run app-store-connect-mcp            # stdio (padrão)
uv run app-store-connect-mcp --transport streamable-http --port 8000
```

Para registrar no cliente MCP, use como comando o executável que o `uv sync` cria dentro do clone:

- macOS: `/caminho/do/clone/.venv/bin/app-store-connect-mcp`
- Windows: `C:\caminho\do\clone\.venv\Scripts\app-store-connect-mcp.exe`

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

No PowerShell, defina as variáveis antes do comando:

```powershell
$env:APP_STORE_CONNECT_KEY_ID = "..."
$env:APP_STORE_CONNECT_ISSUER_ID = "..."
$env:APP_STORE_CONNECT_PRIVATE_KEY_PATH = "C:\caminho\AuthKey.p8"
uv run pytest -m integration
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
