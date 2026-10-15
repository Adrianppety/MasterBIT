# MasterBIT

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/API-FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Frontend](https://img.shields.io/badge/Frontend-Vanilla%20JS-F7DF1E?logo=javascript&logoColor=black)](https://developer.mozilla.org/docs/Web/JavaScript)
[![Deploy](https://img.shields.io/badge/Deploy-Vercel%20(planeado)-black?logo=vercel)](https://vercel.com/)

Catálogo web de cartas Pokémon TCG para explorar coleções, pesquisar cartas e consultar preços de referência em USD e BRL.

## Visão geral

O MasterBIT TCG combina uma interface web responsiva, com estética retro/pixel art, a uma API em Python. O utilizador pode navegar por coleções, pesquisar cartas e consultar dados como imagem, raridade e preço. Quando existe uma cotação em USD e a taxa de câmbio está disponível, o backend calcula um valor estimado em BRL e identifica-o como estimativa — não como cotação de mercado brasileiro.

O backend obtém dados principalmente da Pokémon TCG API e pode recorrer à TCGdex como fonte alternativa. Os dados e caches das coleções também são guardados em ficheiros JSON na pasta `API/packs/`. O projeto não utiliza uma base de dados relacional.

## Funcionalidades

- Listagem e navegação por coleções e expansões de cartas.
- Pesquisa de cartas e de coleções.
- Filtragem por idioma e ordenação por preço ou nome.
- Apresentação de imagens, número, raridade e coleção da carta.
- Visualização ampliada e painel com detalhes e origem da cotação.
- Exibição de preços de referência em USD e conversão estimada para BRL.
- Cache em memória e cache em ficheiros JSON, com tempos de validade configuráveis.
- Endpoints de API e endpoint de healthcheck.
- Testes automatizados do backend.

## Tecnologias

### Backend

- Python
- FastAPI e Pydantic
- Uvicorn para executar o servidor ASGI
- HTTPX para chamadas HTTP assíncronas às APIs externas

### Frontend

- HTML5
- CSS3 próprio
- JavaScript puro (Vanilla JS), sem framework de interface
- Tailwind CSS carregado por CDN
- Google Fonts: Press Start 2P e VT323

### APIs e dados externos

- **Pokémon TCG API:** fonte principal de coleções e cartas; pode fornecer dados de preços do TCGplayer.
- **TCGdex:** fonte alternativa para dados de coleções e cartas.
- **Frankfurter API:** taxa de câmbio USD/BRL usada para calcular valores estimados.
- **TCGplayer:** fonte dos preços de referência em USD incluídos nos dados disponibilizados pela Pokémon TCG API.

As APIs externas dependem de disponibilidade e conectividade. O preço convertido para BRL é uma estimativa calculada a partir do câmbio, não uma cotação de venda local.

### Deploy

O modelo de deploy pretendido é Vercel, com o frontend servido como conteúdo estático e o backend executado como função serverless Python. Consulte a secção [Deploy na Vercel](#deploy-na-vercel) para o estado atual da configuração.

## Estrutura do repositório

```text
.
├── API/
│   └── packs/             # Ficheiros JSON de coleções e cartas em cache
├── imagem/                # Imagens e recursos gráficos do projeto
├── src/
│   ├── app.js             # Lógica do frontend e chamadas à API
│   └── index.html         # Página e estilos da interface
├── tests/
│   └── test_backend.py    # Testes automatizados do backend
├── main.py               # Aplicação FastAPI e integração com as APIs
├── requirements.txt      # Dependências Python
└── README.md
```

## Executar localmente

### Requisitos

- Python 3.10 ou superior.
- `pip`.
- Acesso à internet para consultar as APIs externas.

### 1. Criar e ativar um ambiente virtual

Na raiz do repositório, execute:

**Windows (PowerShell):**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**macOS/Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Instalar dependências

```bash
python -m pip install -r requirements.txt
```

### 3. Iniciar a API

Na raiz do repositório:

```bash
python -m uvicorn main:app --reload
```

Por omissão, a API fica disponível em `http://127.0.0.1:8000`.

- Healthcheck: `http://127.0.0.1:8000/health`
- Documentação interativa: `http://127.0.0.1:8000/docs`
- Esquema OpenAPI: `http://127.0.0.1:8000/openapi.json`

### Endpoints principais

| Método | Rota | Descrição |
| --- | --- | --- |
| `GET` | `/api/packs` | Lista as coleções disponíveis |
| `GET` | `/api/cards` | Consulta cartas; aceita `pack_id`, `search`, `lang` e `sort` |
| `GET` | `/health` | Verifica se a API está ativa |

Para `/api/cards`, `lang` aceita `br`, `us` ou `jp`; `sort` aceita `price_asc`, `price_desc` ou `name`. A documentação interativa em `/docs` apresenta os parâmetros e os modelos de resposta publicados pela aplicação.

### 4. Abrir o frontend

O frontend usa `http://127.0.0.1:8000` como URL predefinido da API. Com o servidor da API em execução, abra um segundo terminal, mude para a pasta `src/` e sirva os ficheiros estáticos:

```bash
cd src
python -m http.server 5500
```

Abra `http://127.0.0.1:5500` no navegador. Também é possível abrir `src/index.html` diretamente, mas servir os ficheiros por HTTP é recomendado para uma execução local mais consistente.

Para apontar o frontend para outra instância da API, defina `window.MASTERBIT_API_URL` antes de carregar `app.js`.

## Configuração

O backend funciona sem chave da Pokémon TCG API, mas pode receber uma chave através da variável de ambiente `POKEMON_TCG_API_KEY`:

**Windows (PowerShell):**

```powershell
$env:POKEMON_TCG_API_KEY = "a-sua-chave"
python -m uvicorn main:app --reload
```

**macOS/Linux:**

```bash
export POKEMON_TCG_API_KEY="a-sua-chave"
python -m uvicorn main:app --reload
```

Não inclua chaves ou outros segredos no código nem em ficheiros versionados.

O backend também permite configurar os tempos de cache e a localização dos ficheiros JSON através destas variáveis:

| Variável | Valor predefinido | Descrição |
| --- | --- | --- |
| `POKEMON_TCG_API` | `https://api.pokemontcg.io/v2` | URL base da Pokémon TCG API |
| `POKEMON_TCG_API_KEY` | Não definido | Chave opcional para a Pokémon TCG API |
| `MASTERBIT_PACKS_DIR` | `API/packs/` | Diretório dos ficheiros JSON de coleções/cartas |
| `SETS_CACHE_TTL_SECONDS` | `43200` | Validade do cache de coleções em memória |
| `CARDS_CACHE_TTL_SECONDS` | `3600` | Validade do cache de cartas em memória |
| `PACKS_FILE_TTL_SECONDS` | `43200` | Validade dos ficheiros JSON de coleções |
| `PACK_CARDS_FILE_TTL_SECONDS` | `86400` | Validade dos ficheiros JSON de cartas |
| `EXCHANGE_RATE_CACHE_TTL_SECONDS` | `3600` | Validade do cache da taxa USD/BRL |
| `MAX_CARD_RESULTS` | `5000` | Limite de resultados de cartas |

## Testes automatizados

Com o ambiente virtual ativo e as dependências instaladas, execute a partir da raiz:

```bash
python -m unittest discover -s tests -v
```

Os testes usam `unittest` e o `TestClient` do FastAPI, com HTTPX e respostas simuladas para testar o backend sem depender diretamente dos serviços externos.

## Deploy na Vercel

### Arquitetura pretendida

Na arquitetura prevista para a Vercel:

1. Os ficheiros do frontend (`src/index.html`, `src/app.js` e recursos gráficos) são publicados como conteúdo estático.
2. O backend Python é disponibilizado como uma função serverless.
3. O `vercel.json` deve declarar as regras de build e encaminhamento necessárias, direcionando as rotas da API para a função Python e as restantes rotas para o frontend estático.
4. As variáveis de ambiente, como `POKEMON_TCG_API_KEY`, devem ser configuradas nas definições do projeto na Vercel, e não guardadas no repositório.

### Estado da configuração neste repositório

**Não foi encontrado um ficheiro `vercel.json` na versão atual do repositório.** Assim, o modelo acima descreve a arquitetura pretendida, mas o encaminhamento e a configuração efetiva da Vercel ainda precisam de ser definidos e validados antes de considerar o deploy configurado. Este README não assume regras ou comandos de build que não estejam presentes no projeto.

Além disso, o cache em memória de uma função serverless não é persistente entre execuções, e o sistema de ficheiros pode não ser adequado para escrita persistente em produção. Para um deploy fiável, trate os ficheiros em `API/packs/` como dados incluídos no deploy ou cache descartável; não dependa de alterações escritas pela função para persistência duradoura.
