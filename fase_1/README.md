# Fase 1 — Coleta OAI-PMH

Pipeline de coleta de teses e dissertações do repositório institucional Pantheon/UFRJ.
Responsável por baixar metadados e PDFs que alimentam todas as fases seguintes.

---

## Índice

1. [Visão geral](#1-visão-geral)
2. [Estrutura de arquivos](#2-estrutura-de-arquivos)
3. [Dados produzidos](#3-dados-produzidos)
4. [Como executar](#4-como-executar)
5. [Fluxo interno detalhado](#5-fluxo-interno-detalhado)
6. [Scripts de diagnóstico](#6-scripts-de-diagnóstico)
7. [Configurações](#7-configurações)
8. [Decisões de design](#8-decisões-de-design)

---

## 1. Visão geral

O Pantheon expõe seus metadados via protocolo **OAI-PMH** (Open Archives Initiative Protocol
for Metadata Harvesting), padrão amplamente adotado por repositórios acadêmicos. A fase 1
consome esse protocolo para coletar, filtrar e persistir os registros de interesse.

```
Pantheon/UFRJ (OAI-PMH)
        │
        │  Dublin Core XML
        ▼
  oai_harvester.py          ← itera registros, filtra, grava manifest
        │
        │  lista de records (dicts Python)
        ▼
  pdf_downloader.py         ← resolve URL do PDF, baixa, valida
        │
        ▼
  data/
  ├── manifest.jsonl        ← um JSON por linha, todos os metadados
  ├── metadata/             ← JSON individual por documento
  └── pdfs/
      └── {AREA}/{ANO}/     ← PDFs organizados por área e ano
```

O resultado desta fase — `manifest.jsonl` + PDFs — é consumido diretamente pela
**Fase 2** (`process_pdfs.py` varre a pasta de PDFs; `tei_to_doco.py` usa o manifest
para enriquecer os metadados dos TTLs).

---

## 2. Estrutura de arquivos

```
fase_1/
│
├── collect.py                   ← ponto de entrada para coleta de um único set
├── collect_all_sets.py          ← coleta todos os sets COPPE em sequência
├── config.py                    ← todas as configurações centralizadas
├── requirements.txt
├── README.md                    ← este arquivo
│
├── src/                         ← módulos internos (não são scripts diretos)
│   ├── oai_harvester.py         ← cliente OAI-PMH + checkpoint + deduplicação
│   ├── dspace_client.py         ← resolve URL de PDF via scraping + REST API
│   ├── pdf_downloader.py        ← download paralelo com validação
│   ├── http_client.py           ← sessão HTTP robusta com retry exponencial
│   └── logger_setup.py          ← logging colorido no terminal + arquivo rotativo
│
├── diagnose_find_thesis_sets.py ← descobre quais sets têm Tese/Dissertação
├── diagnose_set.py              ← inspeciona os primeiros N registros de um set
├── diagnose-paths-url-pantheon.py  ← testa quais URLs/verbos OAI-PMH funcionam
└── diagnose-site-patheon-download-pdf.py ← inspeciona padrão de URL de PDF
```

---

## 3. Dados produzidos

### 3.1 `data/manifest.jsonl`

Arquivo principal desta fase. Uma linha por documento, cada linha é um JSON
completo com todos os metadados coletados do OAI-PMH:

```json
{
  "oai_identifier": "oai:pantheon.ufrj.br:11422/12345",
  "handle":         "11422/12345",
  "handle_url":     "https://pantheon.ufrj.br/handle/11422/12345",
  "title":          "Título da tese",
  "creators":       ["Sobrenome, Nome"],
  "subjects":       ["CNPQ::ENGENHARIAS::ENGENHARIA ELETRICA", "Redes neurais"],
  "description":    "Texto do abstract...",
  "publisher":      "UFRJ",
  "date":           "2021-03-15",
  "types":          ["Tese"],
  "language":       "pt",
  "rights":         "Acesso Aberto",
  "relations":      [],
  "pdf_url_oai":    "https://pantheon.ufrj.br/bitstream/11422/12345/1/arquivo.pdf",
  "datestamp":      "2021-03-16T00:00:00Z",
  "sets":           ["col_11422_90"],
  "collected_at":   "2024-01-10T14:23:00"
}
```

**Usado por:**
- `fase_2/tei_to_doco.py` — lê o manifest para enriquecer os TTLs com metadados
  corretos (título, tipo Tese/Dissertação, data, subjects CNPq)
- `fase_3/fix_titles.py` — usa o manifest como fonte autoritativa para corrigir
  títulos errados no Fuseki
- `run_pipeline.py` — referenciado em vários passos como fonte de verdade

**Modo de escrita:** `append` — cada execução do `harvest()` acrescenta linhas novas.
Documentos já presentes são detectados pelo `handle` e pulados (deduplicação).

### 3.2 `data/metadata/{handle}.json`

JSON individual por documento, com o mesmo conteúdo da linha do manifest.
Gerado tanto pelo `collect.py` quanto pelo `collect_all_sets.py`.
Útil para inspeção manual de um documento específico sem parsear o manifest inteiro.

```bash
# Inspecionar metadados de um documento específico
cat data/metadata/11422_12345.json
```

### 3.3 `data/pdfs/{AREA}/{ANO}/{handle}.pdf`

PDFs organizados em hierarquia de dois níveis: área CNPq e ano de publicação.

```
data/pdfs/
├── Engenharia_de_Sistemas/
│   ├── 2019/
│   │   ├── 11422_1234.pdf
│   │   └── 11422_5678.pdf
│   └── 2020/
│       └── 11422_9999.pdf
├── Engenharia_Eletrica/
│   └── 2021/
│       └── 11422_2222.pdf
└── Sem_Area/          ← documentos sem dc:subject CNPq
    └── Desconhecido/  ← documentos sem dc:date válida
        └── ...
```

A área é determinada pelo **set OAI-PMH** coletado (mapeado em `config.SET_AREA_SLUG`).
O ano vem do campo `dc:date` do registro. Documentos sem mapeamento de área usam
o fallback para subjects CNPq ou `Sem_Area` se nenhum for encontrado.

**Usado por:**
- `fase_2/process_pdfs.py` — usa `rglob("*.pdf")` para varrer recursivamente
  toda a hierarquia de pastas e enviar cada PDF ao GROBID

### 3.4 `data/checkpoint_{set_slug}.json`

Arquivo de checkpoint por set. Armazena o `resumption_token` do OAI-PMH para
permitir retomada da coleta após interrupção. Criado e atualizado automaticamente
a cada 100 registros pelo `oai_harvester.py`.

```json
{
  "resumption_token": "MTY...",
  "total_seen":       847,
  "total_saved":      521,
  "updated_at":       "2024-01-10T15:30:00"
}
```

### 3.5 `data/download_report.jsonl`

Relatório gerado ao final do download de cada batch. Uma linha por PDF, com
status de cada download:

```json
{
  "handle":     "11422/12345",
  "title":      "Título",
  "filename":   "11422_12345.pdf",
  "pdf_path":   "data/pdfs/Engenharia_Eletrica/2021/11422_12345.pdf",
  "status":     "ok",
  "size_bytes": 4521389,
  "md5":        "a1b2c3d4...",
  "error":      null
}
```

Valores possíveis de `status`:

| Status | Significado |
|---|---|
| `ok` | PDF baixado e validado com sucesso |
| `already_exists` | PDF já estava em disco (idempotência) |
| `no_pdf_url` | Não foi possível resolver a URL do PDF |
| `skipped_too_large` | PDF excede `MAX_PDF_SIZE_MB` |
| `download_failed` | Falha de rede no download |
| `not_pdf` | Content-Type não é PDF (possível página de login) |
| `invalid_pdf` | Arquivo baixado não começa com `%PDF-` |
| `write_error` | Erro ao gravar em disco |

---

## 4. Como executar

### Coleta completa (todos os sets COPPE)

```bash
cd fase_1
python collect_all_sets.py
```

Executa os 13 sets em sequência. Para cada set: coleta metadados e baixa PDFs.
A deduplicação é automática — se um documento já está no manifest, é pulado mesmo
que apareça em outro set.

### Coleta de um único set

```bash
# Só o PESC (Engenharia de Sistemas)
python collect.py --set col_11422_96

# Só metadados, sem baixar PDFs
python collect.py --set col_11422_96 --only-metadata

# Teste rápido com 50 registros
python collect.py --set col_11422_96 --limit 50

# A partir de uma data específica
python collect.py --set col_11422_96 --from 2020-01-01
```

### Retomar uma coleta interrompida

```bash
# Basta rodar novamente — o checkpoint é retomado automaticamente
python collect_all_sets.py
```

### Começar do zero

```bash
# Remove checkpoints (o manifest acumula, então não precisa apagar)
del data\checkpoint_*.json

# Ou apaga tudo incluindo manifest e PDFs
python collect.py --reset
```

### Listar sets disponíveis no Pantheon

```bash
python collect.py --list-sets
```

---

## 5. Fluxo interno detalhado

### 5.1 `collect_all_sets.py` → ponto de entrada principal

Itera sobre `SETS_TO_COLLECT` (lista de tuplas `(set_spec, set_name)`), e para cada set:

1. Define `config.OAI_SET_FILTER = set_spec`
2. Determina o slug de área via `config.SET_AREA_SLUG.get(set_spec, fallback)`
3. Injeta `record["_area_slug"] = area_slug` em cada record do `harvest()`
4. Salva cada record em `data/metadata/{handle}.json`
5. Chama `download_batch(records)` para baixar os PDFs

O `_area_slug` é injetado aqui porque o `harvest()` não sabe de qual set veio
o registro — ele só vê o registro em si. O downloader usa esse campo para
calcular o diretório de destino.

### 5.2 `oai_harvester.py` → coleta e filtragem

**`harvest()`** é um gerador Python que:

1. Carrega o checkpoint do set atual (se existir)
2. Instancia o cliente Sickle apontando para `config.PANTHEON_OAI_URL`
3. Carrega os handles já no manifest (`already_collected`) para deduplicação
4. Itera sobre os registros OAI-PMH com `sickle.ListRecords()`
5. Para cada registro:
   - Chama `_parse_record()` para converter em dict Python
   - Pula se o handle já está no manifest
   - Grava no `manifest.jsonl` (modo `append`, com `flush()` a cada registro)
   - Faz `yield record` para o chamador
6. Salva checkpoint a cada 100 registros e no `finally`

**`_parse_record()`** aplica os filtros configurados:

- **Tipo:** se `ACCEPTED_TYPES` está definido, descarta registros cujo `dc:type`
  não contenha nenhum dos tipos aceitos (`Tese`, `Dissertação`)
- **Ano:** descarta registros cujo `dc:date` resulte em ano < `MIN_YEAR` ou > `MAX_YEAR`
- Extrai campos: `title`, `creators`, `subjects`, `date`, `language`, `rights`,
  `pdf_url_oai` (URL direta do PDF se vier no OAI), `handle`, `sets`

**Checkpoint por set:** o arquivo é nomeado como
`data/checkpoint_{set_slug}.json` (ex: `checkpoint_col_11422_96.json`),
evitando que uma retomada use o token errado de outro set.

### 5.3 `dspace_client.py` → resolução da URL do PDF

O OAI-PMH do DSpace não inclui links diretos para os bistreams na maioria dos
registros. O `dspace_client.py` resolve essa URL em cascata:

**Nível 1 — URL do OAI-PMH (mais rápido)**
Se o campo `pdf_url_oai` do registro já tem uma URL `.pdf`, usa direto.
Isso acontece quando o registro tem um `dc:identifier` que termina em `.pdf`.

**Nível 2 — Scraping da página HTML (principal)**
Faz GET em `https://pantheon.ufrj.br/handle/{handle}` e raspa o HTML com
BeautifulSoup procurando links com `/bitstream/` que terminem em `.pdf`
ou contenham `sequence=`. No DSpace 5.x esse padrão é estável.

**Nível 3 — REST API do DSpace (fallback)**
Se o scraping falhar, tenta a API REST: GET em
`/rest/handle/{handle}` para obter o `item_id`, depois
`/rest/items/{item_id}/bitstreams` para listar os bistreams e filtrar
os do bundle `ORIGINAL` com mimeType `application/pdf`.

Resultados são cacheados em memória (`_bitstream_cache`) para evitar
requisições repetidas ao mesmo handle na mesma execução.

### 5.4 `pdf_downloader.py` → download com validação

**`download_batch()`** usa `ThreadPoolExecutor` com `PDF_DOWNLOAD_WORKERS`
threads (padrão: 3) para download paralelo.

**`_download_one()`** para cada registro:

1. Calcula o diretório de destino via `config.get_pdf_dir(record, base_dir=pdf_dir)`
2. Cria o diretório com `os.makedirs(..., exist_ok=True)`
3. Verifica se o PDF já existe em disco (idempotência por tamanho > 1KB)
4. Resolve a URL via `dspace_client.resolve_pdf_url()`
5. Faz HEAD para checar o tamanho antes de baixar
6. Baixa com streaming em chunks de 8KB, verificando tamanho durante o download
7. Valida magic bytes: primeiros 5 bytes devem ser `%PDF-`
8. Calcula MD5 do arquivo final

### 5.5 `config.get_pdf_dir()` → organização por área/ano

Função central para calcular o diretório de destino de um PDF:

```python
get_pdf_dir(record, base_dir="data/pdfs")
# → "data/pdfs/Engenharia_Eletrica/2021"
```

Lógica em ordem de prioridade:

1. **`record["_area_slug"]`** — injetado pelo `collect_all_sets.py` com base no set
2. **`record["subjects"]`** — fallback: extrai do primeiro subject com prefixo `CNPQ::`,
   converte para slug (uppercase, sem acentos, espaços → underscores)
3. **`"Sem_Area"`** — se nenhuma área for encontrada

Para o ano:

1. **`record["date"]`** — busca padrão `(19|20)\d{2}` no valor
2. **`"Desconhecido"`** — se nenhum ano válido for encontrado

### 5.6 `http_client.py` → resiliência HTTP

Cria uma `requests.Session` com:
- Retry automático em `[429, 500, 502, 503, 504]` com backoff exponencial
  (`RETRY_BACKOFF = 3.0` segundos, `MAX_RETRIES = 5`)
- Headers de identificação como crawler acadêmico (boa prática)
- `safe_get()` que captura `Timeout`, `ConnectionError` e retorna `None`
  em vez de lançar exceção

---

## 6. Scripts de diagnóstico

Esses scripts foram usados durante o desenvolvimento para entender o comportamento
do Pantheon antes de escrever o código de produção. Não fazem parte da pipeline
principal mas são úteis para depuração.

### `diagnose-paths-url-pantheon.py`

Testa sistematicamente 3 base URLs × 6 verbos OAI-PMH para descobrir qual
combinação funciona. Foi assim que descobrimos que o endpoint correto é
`/oai/request` e não `/oai` (que retorna HTTP 400).

```bash
python diagnose-paths-url-pantheon.py
```

### `diagnose_find_thesis_sets.py`

Varre todos os sets do Pantheon e amostra 20 registros de cada um para verificar
quais contêm documentos do tipo `Tese` ou `Dissertação`. Gera `data/thesis_sets.json`
com os sets confirmados. Pode levar ~2 minutos.

```bash
python diagnose_find_thesis_sets.py
```

### `diagnose_set.py`

Inspeciona os primeiros N registros de um set específico e mostra a distribuição
de `dc:type` e `dc:date`. Útil para verificar se um set novo tem o formato esperado.

```bash
python diagnose_set.py col_11422_96 50
# → mostra tipos e anos dos primeiros 50 registros
```

### `diagnose-site-patheon-download-pdf.py`

Inspeciona a página HTML de um item específico e lista todos os links com
`bitstream`, `.pdf` ou `sequence`. Foi usado para confirmar o padrão de URL
antes de implementar o scraping em `dspace_client.py`.

```bash
python diagnose-site-patheon-download-pdf.py 11422/3693
```

---

## 7. Configurações

Todas as configurações ficam em `config.py`. As principais:

### Endpoints

| Variável | Valor | Descrição |
|---|---|---|
| `PANTHEON_OAI_URL` | `https://pantheon.ufrj.br/oai/request` | Endpoint OAI-PMH |
| `PANTHEON_REST_URL` | `https://pantheon.ufrj.br/rest` | REST API do DSpace |
| `PANTHEON_BASE_URL` | `https://pantheon.ufrj.br` | Base para URLs relativas |

### Filtros de coleta

| Variável | Padrão | Descrição |
|---|---|---|
| `ACCEPTED_TYPES` | `["Tese", "Dissertação"]` | Tipos de documento aceitos |
| `MIN_YEAR` | `2000` | Ano mínimo de publicação |
| `MAX_YEAR` | `None` | Ano máximo (None = sem limite) |
| `MAX_RECORDS` | `None` | Limite de registros por execução |
| `OAI_SET_FILTER` | `"col_11422_5819"` | Set padrão (sobrescrito pelo collect_all_sets) |

### Download de PDFs

| Variável | Padrão | Descrição |
|---|---|---|
| `DOWNLOAD_PDFS` | `True` | Baixar PDFs? |
| `MAX_PDF_SIZE_MB` | `80` | PDFs maiores são descartados |
| `PDF_DOWNLOAD_WORKERS` | `3` | Downloads em paralelo |

### Organização por tópico/ano

| Variável | Padrão | Descrição |
|---|---|---|
| `ORGANIZE_BY_TOPIC` | `True` | Organiza PDFs em `{área}/{ano}/` |
| `SET_AREA_SLUG` | dict com 13 sets | Mapeamento set → nome de pasta |

### Resiliência

| Variável | Padrão | Descrição |
|---|---|---|
| `REQUEST_TIMEOUT` | `60` | Timeout em segundos por requisição |
| `MAX_RETRIES` | `5` | Tentativas máximas por requisição |
| `RETRY_BACKOFF` | `3.0` | Fator de backoff exponencial |

---

## 8. Decisões de design

**Por que OAI-PMH e não scraping direto do site?**
O OAI-PMH é o protocolo padrão para harvesting de repositórios acadêmicos. É mais
estável que scraping, respeita a infraestrutura do servidor e retorna dados
estruturados. O DSpace o expõe nativamente.

**Por que o endpoint é `/oai/request` e não `/oai`?**
O endereço `/oai` retorna HTTP 400 no Pantheon. Descoberto experimentalmente com
`diagnose-paths-url-pantheon.py`. O `/oai/request` é o padrão do DSpace 5.x.

**Por que as URLs de PDF não vêm no OAI-PMH?**
O DSpace inclui apenas metadados Dublin Core no OAI-PMH. Os links para os bistreams
(arquivos) ficam fora do protocolo. A solução em cascata (URL direta → scraping HTML
→ REST API) cobre os três casos encontrados no corpus.

**Por que scraping HTML como método principal em vez de REST API?**
O scraping é ~5x mais rápido que a REST API (1 requisição vs 2 requisições por
documento). Para um corpus de 2.400+ documentos isso representa ~40 minutos de
diferença. A REST API é mantida como fallback confiável.

**Por que deduplicação por handle e não por título?**
O handle é o identificador único do DSpace — dois documentos com o mesmo título
(resubmissões, por exemplo) terão handles diferentes. A deduplicação por handle
é mais precisa e mais simples.

**Por que checkpoint por set e não um único checkpoint?**
Cada set tem seu próprio `resumption_token` OAI-PMH. Usar um único arquivo de
checkpoint causaria a retomada com o token errado ao trocar de set, resultando
em registros pulados ou duplicados.

**Por que organizar PDFs por área/ano?**
Facilita análise exploratória (examinar só um ano ou área específica sem processamento),
reprocessamento parcial (reenviar ao GROBID só os PDFs de 2020, por exemplo) e
navegação manual pelo corpus.

**Por que `_area_slug` é injetado no record e não calculado pelo downloader?**
O `collect_all_sets.py` sabe exatamente de qual set OAI-PMH veio cada record.
O downloader não tem essa informação — só vê o record já parseado. Injetar o slug
no record mantém a separação de responsabilidades: coleta define a área, download
apenas usa.