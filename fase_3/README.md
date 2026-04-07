# Fase 3 — Fuseki + Análise de Discurso + SPARQL

Pipeline de carregamento do grafo no triplestore, análise semântica via LLM local,
enriquecimento do grafo com discurso científico e consultas SPARQL sobre o corpus.

---

## Índice

1. [Visão geral](#1-visão-geral)
2. [Estrutura de arquivos](#2-estrutura-de-arquivos)
3. [Dados produzidos e consumidos](#3-dados-produzidos-e-consumidos)
4. [Como executar](#4-como-executar)
5. [Fluxo interno detalhado](#5-fluxo-interno-detalhado)
6. [Ontologia de discurso customizada](#6-ontologia-de-discurso-customizada)
7. [Queries SPARQL](#7-queries-sparql)
8. [Scripts de diagnóstico](#8-scripts-de-diagnóstico)
9. [Configurações críticas](#9-configurações-críticas)
10. [Decisões de design](#10-decisões-de-design)

---

## 1. Visão geral

```
fase_2/data/rdf/*.ttl
        │
        │  HTTP upload (~2,2M triplas)
        ▼
  fuseki_setup.py → Apache Jena Fuseki (TDB2)
        │
        │  SPARQL endpoint: http://localhost:3030/pantheon
        │
        ├── sparql_queries.py    ← 20 queries sobre estrutura + discurso
        └── sparql_advanced.py  ← 10 queries temáticas aprofundadas

fase_2/data/tei/*.tei.xml          (fonte primária)
fase_2/data/rdf/*.ttl              (fallback)
        │
        │  extração de seções + chamada LLM
        ▼
  discourse_analysis.py → data/discourse/*.json
        │
        ▼
  enrich_graph.py → Fuseki (+165k triplas de discurso)

Fuseki
  ├── fix_titles.py       ← corrige títulos via SPARQL UPDATE
  └── check_discourse.py ← relatório de qualidade da extração
```

**Filosofia desta fase:** o grafo base (Fase 2) representa a estrutura física
dos documentos. Esta fase adiciona duas camadas: (1) a camada de discurso —
o que cada tese afirma, que limitações reconhece, que contribuições declara —
extraída pelo LLM sem supervisão; e (2) a capacidade de consulta semântica
via SPARQL sobre o corpus inteiro.

---

## 2. Estrutura de arquivos

```
fase_3/
│
├── fuseki_setup.py        ← sobe Fuseki, cria dataset, carrega TTLs
├── discourse_analysis.py  ← extrai discurso dos TEIs via LLM (llama3.1:8b)
├── enrich_graph.py        ← converte JSONs de discurso em RDF e envia ao Fuseki
├── fix_titles.py          ← corrige títulos ruins no Fuseki via SPARQL UPDATE
├── check_discourse.py     ← relatório de qualidade da análise de discurso
├── sparql_queries.py      ← 20 queries de análise do corpus
├── sparql_advanced.py     ← 10 queries temáticas aprofundadas
├── diagnose_discourse.py  ← diagnostica por que docs ficam como no_target_sections
├── diagnose_llm.py        ← diagnóstico completo do ollama e GPU
├── diagnose_llm-1.py      ← versão alternativa do diagnóstico LLM
├── requirements.txt
└── data/
    ├── discourse/             ← JSON por documento (output do discourse_analysis)
    │   └── 11422_XXXX.json
    ├── discourse_report.jsonl ← sumário de status por documento
    └── enriched/              ← TTLs locais com triplas de discurso
        └── 11422_XXXX_discourse.ttl
```

---

## 3. Dados produzidos e consumidos

### 3.1 `data/discourse/{handle}.json`

Arquivo principal desta fase. Um JSON por documento processado pelo LLM:

```json
{
  "handle":    "11422/5432",
  "status":    "ok",
  "doc_title": "Otimização de Redes Neurais para Previsão de Séries Temporais",
  "sections": [
    {
      "section_index":  5,
      "section_head":   "Conclusões e Trabalhos Futuros",
      "text_length":    3842,
      "source":         "tei",
      "claims": [
        "A arquitetura proposta reduziu o RMSE em 23% em relação ao modelo baseline LSTM.",
        "O modelo manteve desempenho estável mesmo com redução de 40% nos dados de treinamento."
      ],
      "contributions": [
        "Implementação de camada de atenção adaptativa para séries temporais multivariadas"
      ],
      "limitations": [
        "O modelo foi avaliado apenas em dados de energia elétrica — generalização não verificada."
      ],
      "future_work": [
        "Extensão para séries temporais com missing data usando mecanismos de imputação."
      ],
      "keywords_inferred": ["LSTM", "série temporal multivariada", "camada de atenção"],
      "rhetorical_type":   "conclusion"
    }
  ]
}
```

Valores de `status`:

| Status | Significado |
|---|---|
| `ok` | Pelo menos uma seção analisada com sucesso |
| `no_target_sections` | Nenhuma seção de conclusão/resultados encontrada |
| `llm_failed` | LLM não retornou JSON válido em nenhuma tentativa |

**Campo `source`** por seção:
- `tei` — seção encontrada pelo título no TEI XML (nível 1/2)
- `tei_content_search` — seção encontrada pelo conteúdo (nível 3, OCR fallback)
- `ttl_fallback` — seção extraída do TTL quando o TEI falhou totalmente

**Consumido por:** `enrich_graph.py`, `check_discourse.py`, `avaliacao/evaluate_project.py`

### 3.2 `data/discourse_report.jsonl`

Sumário de uma linha por documento. Usado pelo `discourse_analysis.py` para
saber quais handles já foram processados (idempotência):

```json
{"handle":"11422/5432","status":"ok","sections":1}
{"handle":"11422/9999","status":"no_target_sections","sections":0}
```

### 3.3 `data/enriched/{handle}_discourse.ttl`

TTL local com as triplas de discurso geradas pelo `enrich_graph.py`.
As mesmas triplas são enviadas ao Fuseki — o arquivo local serve como backup
e permite reenvio sem reprocessar o LLM.

### 3.4 Fuseki — grafo enriquecido

Após `fuseki_setup.py` + `enrich_graph.py`, o grafo default do dataset `pantheon`
contém dois tipos de triplas:

**Triplas estruturais** (geradas na Fase 2):
- Hierarquia documento → seções → parágrafos → referências
- Metadados bibliográficos (título, autores, data, subjects)
- Tipos retóricos DEO das seções

**Triplas de discurso** (geradas nesta fase):
- Claims, contribuições, limitações, trabalhos futuros por documento
- Keywords técnicas inferidas pelo LLM
- Seções de origem de cada elemento de discurso

---

## 4. Como executar

### Sequência completa

```bash
cd fase_3

# 1. Sobe Fuseki e carrega o corpus
python fuseki_setup.py

# 2. Verifica se os títulos estão corretos
python fix_titles.py --dry-run   # vê o que seria corrigido
python fix_titles.py             # aplica as correções

# 3. Análise de discurso (requer ollama com llama3.1:8b)
python discourse_analysis.py --limit 20   # teste rápido
python discourse_analysis.py              # corpus completo (~3-4h com GPU)

# 4. Verifica qualidade da análise
python check_discourse.py

# 5. Enriquece o grafo com os resultados
python enrich_graph.py --dry-run  # vê o que seria enviado
python enrich_graph.py            # envia ao Fuseki

# 6. Queries SPARQL
python sparql_queries.py --list   # lista disponíveis
python sparql_queries.py          # roda todas
python sparql_queries.py --query 5 --export resultados.json
```

### Opções do `fuseki_setup.py`

```bash
python fuseki_setup.py           # sobe Fuseki e carrega corpus
python fuseki_setup.py --reload  # recarrega TTLs (útil após atualizar Fase 2)
python fuseki_setup.py --stop    # para o container
```

### Opções do `discourse_analysis.py`

```bash
python discourse_analysis.py --limit 50          # teste com 50 docs
python discourse_analysis.py --model qwen2.5:7b  # modelo alternativo
python discourse_analysis.py --workers 1          # sequencial (debug)
python discourse_analysis.py --reprocess          # ignora histórico
python discourse_analysis.py --manifest /caminho/manifest.jsonl
```

### Opções do `fix_titles.py`

```bash
python fix_titles.py --dry-run    # simula sem alterar Fuseki
python fix_titles.py              # corrige títulos ruins
python fix_titles.py --manifest /caminho/manifest.jsonl
```

---

## 5. Fluxo interno detalhado

### 5.1 `fuseki_setup.py` — triplestore

Sobe o container Docker `fuseki_pantheon` baseado em `secoresearch/fuseki`
na porta 3030. Cria o dataset `pantheon` com TDB2 (armazenamento em disco,
suporta corpus de milhões de triplas).

**Carregamento dos TTLs:** envia cada arquivo via HTTP POST para
`{FUSEKI_URL}/{DATASET}/data` com `Content-Type: text/turtle`. Os arquivos
são enviados **sem o parâmetro `graph`** — isso os carrega no *default graph*,
garantindo que queries SPARQL sem `GRAPH ?g {}` funcionem normalmente.

Se o dataset já contém triplas, `--reload` esvazia e recarrega. Sem `--reload`,
detecta que há dados e encerra sem reenviar, preservando o estado atual.

### 5.2 `discourse_analysis.py` — extração via LLM

#### Estratégia de busca de seções (3 níveis)

Para cada TEI, busca seções relevantes para análise de discurso com três
estratégias em cascata:

**Nível 1 — título reconhecido diretamente** (`matches_target()`):
Aplica 14 padrões regex sobre o título da seção. Cobre casos diretos como
"Conclusões", "Results", "7. Conclusão", "III — RESULTADOS", "Capítulo 5 Conclusão".

```
TARGET_PATTERNS = [
    r"\bconclu[sz]",       r"\bresult[ao]",      r"\bdiscus[sz]",
    r"\bcontribu",         r"\bconsider[ao]",     r"\bfinal\s*(remarks?)?",
    r"\bsummar[yi]",       r"\brecomend",         r"\bencerr",
    r"^[IVX\d]+[\.\-\s]+.*\bconclu[sz]",   # "VII - CONCLUSÕES"
    ...
]
```

**Nível 2 — incluído no nível 1** (prefixos numéricos/romanos são cobertos pelos
padrões `r"^[IVX\d]+[\.\-\s]+.*"` no mesmo conjunto).

**Nível 3 — busca por conteúdo** (`has_conclusion_content()`):
Quando o título não é reconhecido (OCR garbage, títulos genéricos como "Capítulo Final"),
vasculha o texto dos parágrafos procurando 16 frases indicativas de conclusão:

```python
CONCLUSION_CONTENT_PHRASES = [
    r"\bconclui-se\s+que\b",
    r"\bpode-se\s+concluir\b",
    r"\bos\s+resultados\s+(obtidos|mostram|indicam|demonstram)\b",
    r"\bin\s+this\s+(work|thesis)[^.]{0,40}(proposed|presented)\b",
    r"\bfuture\s+work\s+(includes|will|should)\b",
    ...
]
```

O nível 3 só é ativado se os níveis 1+2 não encontraram nada. Melhorou a taxa
de sucesso em documentos com OCR garbage de ~29% para ~62%.

**Fallback TTL:** se o TEI inteiro não produziu seções (incluindo nível 3),
tenta ler o TTL do mesmo documento e extrai parágrafos das seções
`deo:Conclusion`, `deo:Results` e `deo:Discussion` já identificadas pelo
`tei_to_doco.py`. Exclui `deo:Methods` e `deo:Background` — essas seções
não contêm claims/limitações relevantes.

#### Título do documento

O título do documento enviado no prompt ao LLM segue hierarquia:

1. Manifest OAI-PMH (`manifest["title"]`) — se presente e não fake
2. TEI XML (`<titleStmt>/<title>`) — fallback
3. String vazia — se nenhum disponível

`is_fake_title()` detecta quando o GROBID extraiu agradecimentos/dedicatórias
como título (ex: "Ao Prof. João da Silva, meu orientador...").

#### Prompt e saída esperada

O prompt instrui o modelo a retornar **exclusivamente** um JSON com 6 campos.
Inclui exemplos explícitos de claim bom vs ruim para guiar a extração:

```
GOOD claim: "The proposed method reduced error by 23% compared to baseline."
BAD claim:  "Results were obtained."
```

Para keywords, uma lista de 20+ palavras proibidas (`KEYWORD_STOPWORDS`) é
especificada no prompt para evitar termos genéricos como "resultados", "pesquisa",
"dados".

#### Parâmetros LLM

```python
OLLAMA_OPTIONS = {
    "temperature": 0.1,    # baixo = mais determinístico
    "top_p":       0.9,
    "num_predict": 1000,   # JSON rico usa ~360 tokens — margem segura
    "num_ctx":     2048,   # suficiente para o prompt (~1000 tokens)
    "num_gpu":     99,     # TODOS os layers na GPU RTX 4070 Super
    "keep_alive":  "10m",  # mantém modelo na VRAM entre requests
}
```

`num_gpu=99` é crítico: sem ele, o ollama distribui layers entre CPU e GPU,
reduzindo o throughput de ~10 docs/min para ~1 doc/min.

`keep_alive=10m` evita que o modelo seja descarregado da VRAM entre requests
paralelos, eliminando ~30s de overhead de carregamento por documento.

#### Reparo de JSON truncado

Se o modelo truncar a resposta antes de fechar o JSON (ex: `num_predict` muito
baixo ou texto muito longo), `call_ollama()` aplica reparo:

```python
# Conta { e [ abertos e injeta os fechamentos faltantes
text += "]" * max(text.count("[") - text.count("]"), 0)
text += "}" * max(text.count("{") - text.count("}"), 0)
```

Com `num_predict=1000` e texto limitado a 6000 chars, a ocorrência de truncamento
é rara mas o reparo garante que mesmo outputs parciais sejam aproveitados.

#### Idempotência

Lê o `discourse_report.jsonl` no início e pula handles com `status=ok`. Pode ser
interrompido e retomado sem reprocessar. `--reprocess` ignora o relatório e
reprocessa tudo.

### 5.3 `enrich_graph.py` — conversão JSON → RDF

Para cada `data/discourse/*.json` com `status=ok`, constrói um grafo RDF usando
a ontologia customizada `discourse#`.

Hierarquia de URIs gerada para o handle `11422/5432`:

```
base:11422_5432                              ← documento (já existe da Fase 2)
  discourse:AnalyzedDocument               ← marca como processado pelo LLM
  discourse:hasClaim       → base:11422_5432_disc_sec_0_claim_0
  discourse:hasLimitation  → base:11422_5432_disc_sec_0_limit_0
  discourse:hasFutureWork  → base:11422_5432_disc_sec_0_fw_0
  discourse:inferredKeyword → "LSTM"

base:11422_5432_disc_sec_0               ← seção analisada
  a deo:Conclusion
  dcterms:title "Conclusões e Trabalhos Futuros"
  discourse:hasClaim → base:11422_5432_disc_sec_0_claim_0

base:11422_5432_disc_sec_0_claim_0       ← claim individual
  a discourse:ScientificClaim
  c4o:hasContent "A arquitetura proposta reduziu o RMSE em 23%..."
  discourse:inSection → base:11422_5432_disc_sec_0
```

Cada elemento de discurso (claim, contribuição, limitação, trabalho futuro)
tem comprimento mínimo de 10 chars — itens mais curtos são descartados.

O `upload_to_fuseki()` envia o grafo de cada documento via HTTP POST para o
*default graph* do dataset (sem parâmetro `graph`).

### 5.4 `fix_titles.py` — correção via SPARQL UPDATE

Para cada handle no manifest, busca o título atual no Fuseki com SPARQL SELECT.
Se o título é "ruim" segundo `is_bad_title()`, aplica SPARQL UPDATE:

```sparql
DELETE { base:11422_5432 dcterms:title ?old }
INSERT { base:11422_5432 dcterms:title "Título Correto do Manifest" }
WHERE  { OPTIONAL { base:11422_5432 dcterms:title ?old } }
```

**`is_bad_title()`** detecta títulos problemáticos com 12+ padrões:
- Listas de figuras/tabelas (`lista de figuras`, `list of figures`)
- Agradecimentos e dedicatórias (`à minha família`, `orientador desta`)
- Seções genéricas (`introdução`, `conclusão` isoladas)
- Fragmentos muito curtos (< 5 chars)
- Fragmentos muito longos (> 250 chars — provavelmente TOC)
- Razão de caracteres alfabéticos < 40% (OCR garbage)

O manifest é a fonte autoritativa: se o título do manifest também é ruim
(casos como `??ir~` de PDFs dos anos 70-80), o documento é pulado — não há
fonte melhor disponível.

---

## 6. Ontologia de discurso customizada

Namespace: `http://pantheon.ufrj.br/ontology/discourse#`

### Classes

| Classe | Descrição |
|---|---|
| `discourse:ScientificClaim` | Afirmação factual com resultado concreto extraída de seções de conclusão/resultados |
| `discourse:Contribution` | Artefato técnico específico produzido: algoritmo nomeado, implementação, dataset, framework |
| `discourse:Limitation` | Restrição ou limitação explicitamente reconhecida pelos autores no texto |
| `discourse:FutureWork` | Direção de pesquisa futura mencionada explicitamente pelos autores |
| `discourse:AnalyzedDocument` | Marca que o documento foi processado pelo LLM |

### Propriedades

| Propriedade | Domínio → Faixa | Descrição |
|---|---|---|
| `discourse:hasClaim` | `fabio:Work` → `discourse:ScientificClaim` | Ligação documento ↔ claim |
| `discourse:hasContribution` | `fabio:Work` → `discourse:Contribution` | Ligação documento ↔ contribuição |
| `discourse:hasLimitation` | `fabio:Work` → `discourse:Limitation` | Ligação documento ↔ limitação |
| `discourse:hasFutureWork` | `fabio:Work` → `discourse:FutureWork` | Ligação documento ↔ trabalho futuro |
| `discourse:inferredKeyword` | `fabio:Work` → `xsd:string` | Keyword técnica inferida pelo LLM |
| `discourse:inSection` | `discourse:ScientificClaim` → `doco:Section` | Seção de origem de cada elemento |
| `discourse:hasAnalyzedSection` | `fabio:Work` → `doco:Section` | Seção processada pelo LLM |

### Exemplo de consulta cruzando discurso e estrutura

```sparql
PREFIX fabio:     <http://purl.org/spar/fabio/>
PREFIX dcterms:   <http://purl.org/dc/terms/>
PREFIX discourse: <http://pantheon.ufrj.br/ontology/discourse#>
PREFIX c4o:       <http://purl.org/spar/c4o/>

# Dissertações de mestrado sobre redes neurais a partir de 2018
# com limitações que mencionam "dados"
SELECT ?titulo ?ano ?claim ?limitacao
WHERE {
  ?doc a fabio:MastersThesis .
  ?doc dcterms:title ?titulo .
  ?doc dcterms:date ?date .
  BIND(SUBSTR(STR(?date), 1, 4) AS ?ano)
  FILTER(?ano >= "2018")
  ?doc dcterms:subject ?kw .
  FILTER(CONTAINS(LCASE(?kw), "rede"))
  ?doc discourse:hasClaim ?c .
  ?c c4o:hasContent ?claim .
  ?doc discourse:hasLimitation ?l .
  ?l c4o:hasContent ?limitacao .
  FILTER(CONTAINS(LCASE(?limitacao), "dados"))
}
LIMIT 20
```

---

## 7. Queries SPARQL

### `sparql_queries.py` — 20 queries de análise

| ID | Nome | Tipo |
|---|---|---|
| 1 | Visão geral do corpus | Contagem global |
| 2 | Distribuição por tipo de documento | Tese vs Dissertação |
| 3 | Distribuição de tipos retóricos (DEO) | Estrutura |
| 4 | Top 20 keywords por frequência | Metadados |
| 5 | Busca em conclusões — termo livre | Texto livre |
| 6 | Documentos por ano | Temporal |
| 7 | Claims por documento | Discurso |
| 8 | Busca em claims — termo livre | Discurso + texto |
| 9 | Documentos sem conclusão estruturada | Qualidade |
| 10 | Referências mais citadas | Bibliometria |
| 11 | Limitações por keyword inferida | Discurso |
| 12 | Trabalhos futuros — visão agregada | Discurso |
| 13 | Top keywords inferidas pelo LLM | Discurso |
| 14 | Teses com mais limitações | Discurso |
| 15 | Claims cruzados com ano e tipo | Cruzamento |
| 16 | Evolução temporal: ML vs Elementos Finitos | Temporal + metadados |
| 17 | Limitações por área CNPq | Área + discurso |
| 18 | Teses de doutorado com mais trabalhos futuros | Doutorado + discurso |
| 19 | Claims por tipo de seção retórica | DEO + discurso |
| 20 | Teses em inglês | Idioma |

### `sparql_advanced.py` — 10 queries temáticas

| ID | Nome | Tipo |
|---|---|---|
| 1 | Evolução temporal: ML/IA nos claims | Temporal + discurso |
| 2 | Trabalhos futuros por área CNPq | Área + discurso |
| 3 | Teses vs Dissertações: densidade de claims | Comparativo |
| 4 | Top limitações em Engenharia Civil | Área específica |
| 5 | Documentos com maior densidade estrutural | DoCO |
| 6 | Referências canônicas por subárea | Bibliometria |
| 7 | Contribuições únicas por documento | Discurso |
| 8 | Evolução de sustentabilidade como tema | Temporal |
| 9 | Seções retóricas por tipo por ano | Estrutura temporal |
| 10 | Claims com números/métricas | Discurso quantitativo |

**Nota sobre normalização de case:** as queries 4 e 13 usam `BIND(LCASE(?x) AS ?x_norm)`
antes do `GROUP BY` para consolidar variações como `Simulação`/`simulação`/`SIMULAÇÃO`
em uma única linha. Isso é necessário porque o Apache Jena não aceita expressões
diretamente no `GROUP BY` — o padrão `GROUP BY (LCASE(?x))` retorna HTTP 400.

---

## 8. Scripts de diagnóstico

### `diagnose_llm.py` — diagnóstico completo

Executa 3 testes em sequência para identificar problemas com o ollama:

**Teste 1 — GPU:** verifica `nvidia-smi` e exibe `ollama ps` para confirmar
se o modelo está carregado e em qual dispositivo.

**Teste 2 — Request mínimo:** envia `"Say the word OK"` com `num_predict=5`.
Mede o tempo de resposta. Se demorar > 30s ou retornar vazio, indica problema
de carregamento ou VRAM insuficiente.

**Teste 3 — JSON com texto científico curto:** envia um parágrafo em inglês
e pede extração JSON. Mostra a resposta bruta e tenta parsear. Identifica se
o modelo responde em texto livre (não seguiu a instrução JSON).

**Teste 4 — Seção real do corpus:** pega a primeira seção de conclusão
encontrada nos TEIs e envia como prompt real. Mostra o JSON bruto antes do
parse para depuração.

```bash
python diagnose_llm.py                    # usa llama3.1:8b
python diagnose_llm.py --model qwen2.5:7b # testa outro modelo
```

### `diagnose_discourse.py` — diagnóstico de no_target_sections

Replica exatamente a lógica do `discourse_analysis.py` para um subconjunto
dos TEIs e explica por que cada um seria classificado como `no_target_sections`.

Dois testes por documento:
- **TEI test:** aplica os `TARGET_PATTERNS` sobre os títulos das `<div>`.
  Mostra os cabeçalhos encontrados e quais matcharam.
- **TTL test:** verifica se o TTL tem `deo:Conclusion`/`Results`/`Discussion`
  com parágrafos ligados via `po:contains` e com conteúdo em `c4o:hasContent`.

```bash
python diagnose_discourse.py              # testa os primeiros 50 TEIs
python diagnose_discourse.py --skip 1397  # testa os 50 que discourse processaria agora
python diagnose_discourse.py --same-as-discourse --limit 100
```

Útil para ajustar `TARGET_PATTERNS` quando um lote específico de documentos
produz muitos `no_target_sections`.

---

## 9. Configurações críticas

### Fuseki

| Parâmetro | Valor | Descrição |
|---|---|---|
| `FUSEKI_PORT` | 3030 | Porta exposta pelo container |
| `DATASET` | `pantheon` | Nome do dataset TDB2 |
| `FUSEKI_USER` | `admin` | Usuário de autenticação |
| `FUSEKI_PASS` | `pantheon123` | Senha (alterar em produção) |
| RAM do container | 6GB | Suficiente para corpus com 2,5M+ triplas |

### Ollama / LLM

| Parâmetro | Valor | Impacto |
|---|---|---|
| `DEFAULT_MODEL` | `llama3.1:8b` | Modelo adotado após comparação experimental |
| `num_gpu` | 99 | Força TODOS os layers na GPU — crítico para performance |
| `keep_alive` | `10m` | Mantém modelo na VRAM entre requests |
| `num_predict` | 1000 | JSON típico usa ~360 tokens — margem segura |
| `num_ctx` | 2048 | Janela de contexto — suficiente para o prompt |
| `temperature` | 0.1 | Baixo = mais consistente, menos criativo |
| Workers padrão | 3 | Testado empiricamente para RTX 4070 Super 12GB |
| Texto por seção | 6000 chars | Cobre 100% das seções do corpus |

### Por que `num_gpu=99` é obrigatório

Sem essa configuração, o ollama distribui layers entre CPU e GPU de acordo
com a VRAM disponível. Com o llama3.1:8b (4.7GB), a distribuição padrão
pode deixar até 30% dos layers na CPU, reduzindo o throughput de ~12 docs/min
para ~2 docs/min — diferença de 3-4h para ~17h no corpus completo.

---

## 10. Decisões de design

**Por que llama3.1:8b e não um modelo maior?**
Comparação experimental com qwen2.5:14b-instruct em 30 documentos: o 8b obteve
96% de tipo retórico correto vs 13% do 14b, e foi 30% mais rápido (7s vs 10s/doc).
Modelos maiores tenderam a ser prolixos e ignorar a instrução de JSON puro.

**Por que `/api/generate` (stateless) e não `/api/chat`?**
O `/api/generate` do ollama é completamente stateless — cada chamada é independente
sem contexto compartilhado. Com `/api/chat`, o histórico de conversas acumularia
entre documentos, causando contaminação cruzada (o modelo "lembraria" de teses
anteriores). O design stateless garante que cada documento é analisado de forma
isolada.

**Por que 3 workers com LLM e não mais?**
Com 2 workers havia timeouts frequentes — o ollama enfileirava o segundo request
enquanto processava o primeiro, e o timeout de 120s expirava na espera. Com 3
workers na RTX 4070 Super (12GB VRAM), o modelo fica na VRAM (llama3.1:8b ocupa
~5GB) e o overhead de enfileiramento é absorvido pelo `keep_alive`. Mais de 3
workers causava degradação de qualidade por disputa de recursos de memória.

**Por que carregar TTLs no default graph e não em named graphs?**
Carregar com `params={"graph": uri}` (named graph) resultaria em queries SPARQL
sem `GRAPH ?g {}` consultando apenas o default graph vazio. Para o projeto,
todas as queries usam o padrão simples `WHERE { ?s ?p ?o }` sem especificar
grafo — o default graph é a escolha correta.

**Por que o fallback vai ao TTL e não diretamente à análise LLM sem seção?**
O TTL já tem as seções tipadas com DEO pelo `tei_to_doco.py`. Usar o TTL como
fallback aproveita o trabalho já feito na Fase 2 sem replicar a lógica de
identificação de seções. Documentos onde nem o TEI nem o TTL têm seções de
conclusão/resultados ficam como `no_target_sections` — são genuinamente sem
essas seções (documentos históricos, relatórios técnicos formatados como
monografias, PDFs com OCR irrecuperável).

**Por que `fix_titles.py` usa SPARQL UPDATE e não reprocessamento dos TTLs?**
Reprocessar os TTLs implicaria executar novamente o `tei_to_doco.py` e depois
recarregar no Fuseki — processo de horas. O SPARQL UPDATE modifica cirurgicamente
apenas o triple `dcterms:title` de cada documento diretamente no triplestore em
segundos, sem afetar nenhum outro dado.

**Por que `check_discourse.py` é um relatório separado e não parte do `discourse_analysis.py`?**
O `discourse_analysis.py` pode rodar por 3-4 horas. Misturar o relatório de
qualidade com o processamento tornaria difícil inspecionar resultados parciais.
O `check_discourse.py` lê os JSONs já gerados e pode ser rodado a qualquer
momento durante ou após o processamento para monitorar o progresso.