# Fase 2 — Extração Estrutural + Mapeamento DoCO

Pipeline de extração de estrutura científica dos PDFs coletados na Fase 1.
Produz um grafo RDF por documento, anotado com ontologias SPAR, pronto para
ser carregado no triplestore da Fase 3.

---

## Índice

1. [Visão geral](#1-visão-geral)
2. [Estrutura de arquivos](#2-estrutura-de-arquivos)
3. [Dados produzidos](#3-dados-produzidos)
4. [Como executar](#4-como-executar)
5. [Fluxo interno detalhado](#5-fluxo-interno-detalhado)
6. [Ontologias usadas](#6-ontologias-usadas)
7. [Configurações e thresholds](#7-configurações-e-thresholds)
8. [Decisões de design](#8-decisões-de-design)

---

## 1. Visão geral

```
fase_1/data/pdfs/{AREA}/{ANO}/*.pdf
            │
            │  HTTP multipart/form-data
            ▼
       GROBID 0.8.1              ← container Docker, 10 workers, 10GB RAM
       (processo_pdfs.py)
            │
            │  TEI XML estruturado
            ▼
       data/tei/*.tei.xml        ← um arquivo por documento
            │
            ├── [quality_gate stage2]   ← detecta body vazio, OCR-lixo, TOC falso
            │
            │  parse + build_graph
            ▼
       tei_to_doco.py            ← converte TEI → RDF com ontologias SPAR
            │   usa manifest OAI-PMH como autoridade em metadados
            │
            ▼
       data/rdf/*.ttl            ← um Turtle por documento
            │
            ├── [quality_gate stage3 --patch]  ← corrige TTLs via manifest
            ├── [validate_rdf.py]              ← auditoria final
            │
            ▼
       Fase 3 (Fuseki)
```

**Filosofia central da fase 2:** o GROBID é confiável para estrutura (onde estão
as seções, os parágrafos, as referências), mas **não é confiável para metadados**
(título, autores, data, subjects). O manifest OAI-PMH coletado na Fase 1 é a
fonte autoritativa para todos os campos bibliográficos. Essa separação de
responsabilidades permeia todos os scripts desta fase.

---

## 2. Estrutura de arquivos

```
fase_2/
│
├── grobid_setup.py    ← sobe container Docker do GROBID e verifica saúde
├── process_pdfs.py    ← envia PDFs ao GROBID em paralelo, salva TEI XMLs
├── tei_to_doco.py     ← converte TEI → RDF/Turtle com ontologias SPAR
├── quality_gate.py    ← validação em 3 estágios (PDF → TEI → TTL)
├── validate_rdf.py    ← auditoria e correção pontual dos TTLs via manifest
├── requirements.txt
└── data/
    ├── tei/           ← TEI XMLs gerados pelo GROBID (um por PDF)
    ├── rdf/           ← Turtle RDFs gerados pelo tei_to_doco (um por TEI)
    ├── tei_rejected/  ← TEIs rejeitados pelo quality gate stage2
    ├── quality_reports/   ← relatórios JSONL por estágio
    │   ├── stage1_pdfs.jsonl
    │   ├── stage2_teis.jsonl
    │   └── stage3_ttls.jsonl
    ├── grobid_report.jsonl     ← status de cada PDF enviado ao GROBID
    └── tei_to_doco_report.jsonl ← status de cada TEI convertido
```

---

## 3. Dados produzidos

### 3.1 `data/tei/{handle}.tei.xml`

XML no formato TEI P5 gerado pelo GROBID. Contém:

- **`<teiHeader>`** — metadados extraídos do PDF: título, autores, afiliações
- **`<abstract>`** — abstract identificado automaticamente
- **`<body>`** — corpo do documento dividido em `<div>` (seções) com `<head>` e `<p>`
- **`<listBibl>`** — referências bibliográficas estruturadas com `<biblStruct>`

**Confiabilidade:** o GROBID é excelente para estrutura em PDFs digitais modernos.
Em PDFs históricos dos anos 1970-90 (scans), frequentemente captura a página de
sumário como lista de autores ou o índice de capítulos como título. O quality gate
stage2 detecta esses casos.

### 3.2 `data/rdf/{handle}.ttl`

RDF no formato Turtle. Cada arquivo representa um documento completo com todas
as suas partes. Estrutura típica:

```turtle
@prefix doco:     <http://purl.org/spar/doco/> .
@prefix deo:      <http://purl.org/spar/deo/> .
@prefix fabio:    <http://purl.org/spar/fabio/> .
@prefix c4o:      <http://purl.org/spar/c4o/> .
@prefix po:       <http://www.essepuntato.it/2008/12/pattern#> .
@prefix dcterms:  <http://purl.org/dc/terms/> .

# ── Documento ────────────────────────────────────────────────────────────────
base:11422_5432 a fabio:DoctoralThesis, fabio:Work ;
    dcterms:title    "Otimização de Redes Neurais para Previsão de Séries Temporais" ;
    dcterms:creator  "Silva, João Antônio" ;
    dcterms:date     "2020-03-15"^^xsd:date ;
    dcterms:subject  "CNPQ::ENGENHARIAS::ENGENHARIA ELETRICA" ;
    dcterms:language "pt" ;
    bibo:handle      "11422/5432" ;
    schema:url       <https://pantheon.ufrj.br/handle/11422/5432> ;
    po:contains      base:11422_5432_abstract,
                     base:11422_5432_sec_0,
                     base:11422_5432_sec_1,
                     base:11422_5432_sec_2,
                     base:11422_5432_references .

# ── Abstract ─────────────────────────────────────────────────────────────────
base:11422_5432_abstract a doco:Abstract ;
    c4o:hasContent "Esta dissertação propõe uma arquitetura..." .

# ── Seção com tipo retórico inferido ─────────────────────────────────────────
base:11422_5432_sec_0 a deo:Introduction, doco:Section ;
    dcterms:title "Introdução" ;
    po:contains   base:11422_5432_sec_0_para_0,
                  base:11422_5432_sec_0_para_1 .

base:11422_5432_sec_0_para_0 a doco:Paragraph ;
    c4o:hasContent "Nos últimos anos, o volume de dados..." .

# ── Seção de conclusão ────────────────────────────────────────────────────────
base:11422_5432_sec_2 a deo:Conclusion, doco:Section ;
    dcterms:title "Conclusões e Trabalhos Futuros" ;
    po:contains   base:11422_5432_sec_2_para_0 .

# ── Referências ──────────────────────────────────────────────────────────────
base:11422_5432_references a doco:ListOfReferences ;
    po:contains base:11422_5432_ref_0 .

base:11422_5432_ref_0 a bibo:Article ;
    dcterms:title   "Deep Learning" ;
    dcterms:creator "Goodfellow, Ian" ;
    dcterms:date    "2016" .
```

**Usado por:**
- `fase_3/fuseki_setup.py` — carrega todos os TTLs no triplestore via HTTP
- `fase_3/discourse_analysis.py` — acessa os TEIs diretamente para análise LLM
- `avaliacao/shacl_validate.py` — valida os TTLs contra shapes SHACL W3C

### 3.3 `data/grobid_report.jsonl`

Relatório do `process_pdfs.py`. Uma linha por PDF processado:

```json
{
  "handle":     "11422/5432",
  "pdf_path":   "../fase_1/data/pdfs/Engenharia_Eletrica/2020/11422_5432.pdf",
  "tei_path":   "data/tei/11422_5432.tei.xml",
  "status":     "ok",
  "error":      null,
  "size_bytes": 4521389
}
```

Valores de `status`: `ok`, `timeout` (GROBID demorou > 90s), `http_503`
(GROBID sobrecarregado), `http_N` (outros erros HTTP), `error` (exceção Python).

O script lê esse relatório na próxima execução para pular handles já processados
com sucesso — idempotência total.

### 3.4 `data/tei_to_doco_report.jsonl`

Relatório do `tei_to_doco.py`. Uma linha por TEI convertido:

```json
{
  "handle":          "11422/5432",
  "status":          "ok",
  "triples":         1847,
  "sections":        12,
  "refs":            43,
  "has_conclusion":  true,
  "has_abstract":    true,
  "has_subjects":    true,
  "sanity":          []
}
```

`status` pode ser `ok`, `ok_with_warnings` (passou sanity check com avisos),
`no_manifest_meta` (handle não encontrado no manifest), `parse_error` (TEI
XML inválido), `too_few_triples` (menos de 50 triplas geradas).

---

## 4. Como executar

### Passo a passo completo

```bash
cd fase_2

# 1. Sobe o GROBID
python grobid_setup.py

# 2. Processa os PDFs (pode demorar horas no corpus completo)
python process_pdfs.py

# 3. Valida os TEIs gerados
python quality_gate.py stage2

# 3a. (opcional) Move TEIs ruins para tei_rejected/
python quality_gate.py stage2 --apply

# 4. Converte TEI → RDF
python tei_to_doco.py

# 5. Corrige TTLs com dados do manifest
python quality_gate.py stage3 --patch

# 6. Auditoria final
python validate_rdf.py
```

### Opções úteis do `process_pdfs.py`

```bash
# Teste com 20 PDFs (do menor para o maior)
python process_pdfs.py --limit 20

# Pula PDFs > 20MB para processar mais rápido
python process_pdfs.py --fast

# Força reprocessamento de tudo (ignora relatório anterior)
python process_pdfs.py --reprocess

# Ajusta número de workers (padrão: 14)
python process_pdfs.py --workers 8
```

### Opções úteis do `tei_to_doco.py`

```bash
# Teste com 10 documentos
python tei_to_doco.py --limit 10

# Reprocessa mesmo os já convertidos
python tei_to_doco.py --reprocess

# Especifica manifest explicitamente
python tei_to_doco.py --manifest /caminho/manifest.jsonl

# Controla paralelismo (padrão: todos os CPUs)
python tei_to_doco.py --workers 4
```

### Opções do `quality_gate.py`

```bash
# Executa todos os estágios
python quality_gate.py all

# Só PDFs
python quality_gate.py stage1

# TEIs — valida e move os ruins para tei_rejected/
python quality_gate.py stage2 --apply

# TTLs — audita e corrige in-place com dados do manifest
python quality_gate.py stage3 --patch

# Simula as correções sem salvar (útil para testar)
python quality_gate.py stage3 --patch --dry-run

# Audita um documento específico
python quality_gate.py stage3 --handle 11422/2286

# Especifica manifest alternativo
python quality_gate.py stage3 --manifest /caminho/manifest.jsonl
```

### Para o GROBID

```bash
python grobid_setup.py --stop      # para o container
python grobid_setup.py --restart   # recria o container
docker logs -f grobid_pantheon     # acompanha logs em tempo real
```

---

## 5. Fluxo interno detalhado

### 5.1 `grobid_setup.py` — container Docker

Verifica se o Docker está acessível e sobe o container `grobid_pantheon`
baseado na imagem `lfoppiano/grobid:0.8.1` na porta `8070`.

**Configurações aplicadas ao container:**
- `GROBID_NB_WORKERS=10` — threads internas de ML do GROBID
- `--memory=10g` — memória dedicada ao container
- `--cpus=10` — limite de CPUs
- `--restart unless-stopped` — reinicia automaticamente se o host reiniciar

Após subir, faz polling em `GET /api/isalive` a cada 2 segundos por até 3
minutos. Se o GROBID não responder nesse prazo, encerra com erro.

Se o container já existe (de uma execução anterior), para e remove antes de
criar novo — garantindo que as configurações de workers e memória sejam sempre
aplicadas corretamente.

### 5.2 `process_pdfs.py` — envio paralelo ao GROBID

Varre recursivamente `fase_1/data/pdfs/` com `rglob("*.pdf")` para capturar
a hierarquia por área/ano criada na Fase 1. Ordena os PDFs do menor para o
maior antes de distribuir para os workers — PDFs pequenos terminam rápido e
deixam os workers livres para os grandes.

**Para cada PDF (`process_one`):**

1. Envia via POST para `GROBID_URL/api/processFulltextDocument` com:
   - `consolidateHeader=1` — GROBID tenta validar o cabeçalho com metadados externos
   - `consolidateCitations=0` — desativado (muito lento, sem ganho para o projeto)
   - `includeRawCitations=1` — inclui citações no formato bruto
   - `includeRawAffiliations=1` — inclui afiliações no formato bruto

2. Em caso de HTTP 503 (GROBID sobrecarregado), faz backoff de 2 × tentativa segundos
3. Timeout de 90 segundos por PDF, com até 2 retentativas
4. Salva o XML TEI recebido em `data/tei/{handle}.tei.xml`

**Idempotência:** lê o `grobid_report.jsonl` no início e pula handles com
status `ok`. Pode ser interrompido a qualquer momento e retomado sem reprocessar.

**Estimativa de tempo:** usa benchmark empírico de ~8s/PDF com 8 workers do GROBID.
O ETA é recalculado em tempo real durante o processamento com base na velocidade real.

### 5.3 `quality_gate.py` — validação em 3 estágios

#### Stage 1 — PDFs (pré-GROBID)

Para cada PDF, verifica:

| Check | Threshold | Ação se falhar |
|---|---|---|
| Magic bytes `%PDF-` | exato | rejeita |
| Tamanho mínimo | > 10KB | rejeita |
| Tamanho máximo | < 80MB | rejeita |
| Densidade de texto | > 5% (primeiros 50KB) | rejeita (provavelmente scan) |

Com `--apply`, PDFs rejeitados são movidos para `data/pdfs_rejected/`.

#### Stage 2 — TEIs (pós-GROBID)

Para cada TEI, verifica:

| Check | Threshold | Ação se falhar |
|---|---|---|
| XML parseável | — | rejeita |
| Título não é sumário | regex `TOC_TITLE_PATTERNS` | rejeita |
| Body presente | — | rejeita |
| Body mínimo | > 800 chars | rejeita |
| Razão de garbage | < 35% (não-alfanumérico) | rejeita |
| Seções reais | ≥ 2 com `<head>` real | rejeita |
| Autores do GROBID são TOC | > 50% dos autores | **aviso** (não rejeita) |
| Referências com garbage | > 50% com garbage | **aviso** (não rejeita) |

A distinção entre **rejeição** e **aviso** é intencional: problemas de autores
e referências em scans antigos são esperados e serão corrigidos pelo manifest
no stage3. Rejeitar um TEI só faz sentido quando o body em si é inutilizável.

Com `--apply`, TEIs rejeitados são movidos para `data/tei_rejected/`.

#### Stage 3 — TTLs (pós-conversão)

Para cada TTL, audita contra o manifest OAI-PMH e verifica:

| Check | Verificação |
|---|---|
| Tipo correto | `fabio:DoctoralThesis` vs `fabio:MastersThesis` |
| `dcterms:title` presente | obrigatório |
| `dcterms:creator` presente | obrigatório |
| `dcterms:date` presente | obrigatório |
| `dcterms:subject` presente | obrigatório (GROBID não extrai) |
| `dcterms:language` presente | opcional |
| `schema:url` presente | opcional |
| Mínimo de 50 triplas | — |
| Pelo menos 1 seção retórica DEO | Introduction, Conclusion, Methods, etc. |

Com `--patch`, aplica correções diretamente nos TTLs:

- **Substituição total** (creators, date): remove o que o GROBID colocou e
  insere os valores do manifest. Usado porque o GROBID frequentemente coloca
  nomes de capítulos no lugar de autores em scans.
- **Adição apenas** (subjects, title, language, url): não remove o que o GROBID
  extraiu — apenas completa o que está faltando.

O `patch_ttl()` recarrega o grafo, aplica as modificações e serializa de volta
em Turtle, preservando todos os dados estruturais.

### 5.4 `tei_to_doco.py` — conversão TEI → RDF

Usa `ProcessPoolExecutor` (processos, não threads) para converter TEIs em paralelo.
Processos são necessários porque o Python GIL impede paralelismo real em threads
para trabalho CPU-bound como parse XML e construção de grafos RDF.

**`parse_tei()`** extrai do XML TEI:

- **Título:** busca em `<titleStmt>/<title>`. Descarta se > 250 chars ou se
  corresponde a `BAD_TITLE_PATTERNS` (sumário, TOC). Deixa vazio para o manifest
  corrigir.
- **Autores do TEI:** lê `<persName>` com `<forename>` + `<surname>`. Filtra
  nomes com dígitos, muito longos (> 5 palavras), ou que correspondem a
  `BAD_AUTHOR_PATTERNS`. São usados apenas se o manifest não tiver creators.
- **Abstract:** busca em `<profileDesc>/<abstract>`. Prefere parágrafos que
  contêm palavras-chave de abstract ("neste trabalho", "this dissertation").
  Rejeita parágrafos que começam com palavras de agradecimento.
- **Seções:** itera `<div>` no `<body>`. Para cada um, extrai o `<head>` e
  todos os `<p>` com ao menos 30 chars. Aplica `infer_doco_type()` no título.
- **Referências:** itera `<biblStruct>` em `<listBibl>`. Aplica `is_bad_ref_title()`
  para filtrar lixo de OCR antes de incluir no grafo.

**`infer_doco_type()`** determina o tipo retórico de uma seção pelo seu título.
Aplica 30+ padrões regex com suporte a prefixos numéricos e romanos (ex: "VII — Conclusões",
"6. Resultados"), cobrindo português e inglês. Retorna `(namespace, classe_DEO_ou_DoCO)`.

**`build_graph()`** constrói o grafo RDF com hierarquia explícita de confiança:

| Campo | Fonte | Lógica |
|---|---|---|
| Tipo (Tese/Dissertação) | **manifest** | SEMPRE. TEI não tem essa informação confiável |
| `dcterms:date` | **manifest** | SEMPRE. O GROBID extrai a data de publicação do PDF, que pode ser a data de impressão, não de defesa |
| `dcterms:subject` | **manifest** | SEMPRE. GROBID não extrai subjects CNPq |
| `dcterms:creator` | manifest prioritário, TEI como fallback | O manifest tem os nomes corretos dos autores |
| `dcterms:title` | TEI prioritário, manifest como fallback | O TEI pode ter título mais completo; manifest corrige se o TEI falhar |
| Abstract | TEI se ≥ 100 chars, manifest se ≥ 20 chars | TEI tende a ter abstract mais completo |
| Seções, parágrafos, refs | **GROBID/TEI** | Estrutura é o que o GROBID faz bem |

**`sanity_check()`** verifica o grafo construído antes de salvar. Se o tipo
estiver errado ou subjects/date/creators estiverem ausentes mesmo existindo no
manifest, grava `ok_with_warnings` no relatório. O TTL ainda é salvo — os
warnings são corrigidos pelo `quality_gate.py stage3 --patch`.

### 5.5 `validate_rdf.py` — auditoria final

Complementa o quality gate com uma auditoria mais detalhada dos TTLs já em disco.
Calcula estatísticas de cobertura de campos para o corpus inteiro:

- Quantos TTLs têm título / authors / date / subjects (%)
- Distribuição de triplas por documento
- Documentos com zero seções retóricas DEO

Com `--patch`, aplica as mesmas correções do `quality_gate.py stage3 --patch`
mas de forma independente — útil para rodar após adicionar novos documentos ao
corpus sem executar o quality gate completo novamente.

---

## 6. Ontologias usadas

O projeto usa o pacote **SPAR** (Semantic Publishing and Referencing Ontologies),
um conjunto coerente de ontologias para documentos científicos:

| Prefixo | Ontologia | Uso no projeto |
|---|---|---|
| `fabio:` | FRBR-aligned Bibliographic Ontology | Tipo do documento: `DoctoralThesis`, `MastersThesis`, `Work` |
| `doco:` | Document Components Ontology | Estrutura física: `Section`, `Paragraph`, `Abstract`, `ListOfReferences`, `Appendix` |
| `deo:` | Discourse Elements Ontology | Retórica: `Introduction`, `Conclusion`, `Methods`, `Results`, `Discussion`, `RelatedWork`, `Background`, `FutureWork`, `Acknowledgements` |
| `c4o:` | Citation Counting Ontology | Conteúdo textual: `c4o:hasContent` |
| `po:` | Document Structural Patterns | Relações hierárquicas: `po:contains` |
| `bibo:` | Bibliographic Ontology | Referências: `bibo:Article`, `bibo:handle` |
| `dcterms:` | Dublin Core Terms | Metadados: `title`, `creator`, `date`, `subject`, `language` |
| `schema:` | Schema.org | URL do handle: `schema:url` |

### Tipos retóricos inferidos automaticamente

O `infer_doco_type()` cobre 30+ padrões em português e inglês, com suporte a
numeração romana e arábica:

| Padrão no título da seção | Tipo atribuído |
|---|---|
| "introduç", "introduc" | `deo:Introduction` |
| "conclus", "considera", "final remarks" | `deo:Conclusion` |
| "method", "metodolog", "proposta", "arquitetura" | `deo:Methods` |
| "related work", "literatura", "revisão", "review" | `deo:RelatedWork` |
| "experiment", "result", "avalia", "evaluation" | `deo:Results` |
| "discuss", "análise", "analysis" | `deo:Discussion` |
| "background", "fundament", "referencial teórico" | `deo:Background` |
| "referenc", "bibliograf" | `doco:ListOfReferences` |
| "appendix", "apêndice", "anexo" | `doco:Appendix` |
| "sugestões" | `deo:FutureWork` |
| "agradec", "acknowledge" | `deo:Acknowledgements` |
| qualquer outro | `doco:Section` (tipo genérico) |

Padrões com prefixo numérico também são cobertos:
- `"VII — Conclusões"` → `deo:Conclusion`
- `"6.2 Resultados Experimentais"` → `deo:Results`
- `"Capítulo 3 Metodologia"` → `deo:Methods`

---

## 7. Configurações e thresholds

### Thresholds do `quality_gate.py`

| Constante | Valor | Significado |
|---|---|---|
| `PDF_MIN_SIZE_KB` | 10 | PDFs menores são descartados |
| `PDF_MAX_SIZE_MB` | 80 | PDFs maiores são descartados |
| `TEI_MIN_BODY_CHARS` | 800 | Body com menos chars indica falha de extração |
| `TEI_MAX_GARBAGE` | 0.35 | > 35% de chars não-alfanuméricos indica OCR ruim |
| `TEI_MIN_SECTIONS` | 2 | Menos de 2 seções com `<head>` real indica TOC falso |
| `TEI_MAX_TOC_RATIO` | 0.5 | > 50% autores parecem TOC → aviso (não rejeita) |
| `TTL_MIN_TRIPLES` | 50 | TTLs com menos triplas provavelmente não têm conteúdo |

### Thresholds do `tei_to_doco.py`

| Constante | Valor | Significado |
|---|---|---|
| `MIN_BODY_CHARS` | 500 | Body com menos chars — TEI é descartado |
| `MIN_TRIPLES` | 50 | Grafo com menos triplas — TTL não é salvo |
| `MIN_PARA_CHARS` | 30 | Parágrafos menores são descartados |
| `MAX_TITLE_LEN` | 250 | Títulos mais longos são descartados como TOC |

### GROBID (`grobid_setup.py`)

| Constante | Valor | Significado |
|---|---|---|
| `GROBID_WORKERS` | 10 | Threads internas de ML do GROBID |
| `GROBID_RAM_GB` | 10 | RAM dedicada ao container |
| `GROBID_PORT` | 8070 | Porta exposta pelo container |

### `process_pdfs.py`

| Constante | Valor | Significado |
|---|---|---|
| `DEFAULT_WORKERS` | 14 | Workers Python (deve ser > workers GROBID para saturá-lo) |
| `TIMEOUT` | 90 | Segundos de timeout por PDF |
| `MAX_RETRIES` | 2 | Tentativas antes de desistir de um PDF |
| `FAST_SIZE_MB` | 20 | Limite do modo `--fast` |

---

## 8. Decisões de design

**Por que ProcessPoolExecutor no `tei_to_doco.py` e ThreadPoolExecutor no `process_pdfs.py`?**
A conversão TEI→RDF é trabalho CPU-bound (parse XML + construção de grafos). O Python GIL
bloqueia threads para trabalho CPU-bound, então o `ProcessPoolExecutor` é necessário para
paralelismo real. O envio ao GROBID é I/O-bound (espera a rede), então threads são suficientes
e mais leves.

**Por que 14 workers Python para um GROBID com 10 workers?**
O GROBID tem overhead de rede e processamento interno. Com exatamente 10 workers Python
para 10 workers GROBID, em qualquer momento que o GROBID está processando, os workers
Python ficam esperando. Ter 14 workers garante que o GROBID nunca fica ocioso esperando
uma nova requisição.

**Por que desativar `consolidateCitations`?**
O GROBID com `consolidateCitations=1` tenta validar cada referência bibliográfica
contra bases externas (CrossRef, Semantic Scholar). Para um corpus de 2.400 documentos
com ~40 referências cada, isso resulta em ~96.000 requisições externas adicionais,
multiplicando o tempo de processamento por 5-10x sem ganho significativo para o projeto.

**Por que o manifest é fonte autoritativa para metadados e não o TEI?**
O GROBID foi treinado em artigos de periódicos modernos digitais. Teses em português
dos anos 1990-2010, especialmente as scaneadas, frequentemente não têm a estrutura
que o GROBID espera. O resultado é que o GROBID coloca a lista de figuras no campo
de autores, o índice de capítulos no título, e a data de impressão no campo de data.
O manifest OAI-PMH coletado diretamente do Pantheon tem os metadados que os próprios
autores/orientadores submeteram ao repositório — é a fonte mais confiável disponível.

**Por que `is_bad_title()` descarta títulos longos?**
Títulos de teses raramente têm mais de 250 caracteres. Quando o GROBID coloca 250+ chars
no campo de título, invariavelmente é o sumário ou o índice da tese. O threshold de 250
foi calibrado empiricamente no corpus da COPPE.

**Por que separar `quality_gate.py stage3` do `validate_rdf.py`?**
O `quality_gate.py` é parte da pipeline principal (faz parte dos 19 passos do `run_pipeline.py`)
e aplica correções em lote logo após a conversão. O `validate_rdf.py` é uma ferramenta
de auditoria independente, útil para rodar pontualmente ou após reprocessar um subconjunto
do corpus sem executar toda a pipeline.

**Por que `--patch --dry-run`?**
A correção de TTLs em produção é uma operação destrutiva (sobrescreve os arquivos).
O modo `dry-run` mostra exatamente o que seria alterado — quantos TTLs, quais campos,
quantas triplas adicionadas/removidas — sem tocar em nada. Útil para verificar o impacto
antes de aplicar mudanças em um corpus de 1.970 documentos.