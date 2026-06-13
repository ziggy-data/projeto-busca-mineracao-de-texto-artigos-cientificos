# Grafo de Conhecimento de Discurso Científico — Pantheon/UFRJ

> **Disciplina:** Busca e Mineração de Texto  
> **Programa:** Engenharia de Sistemas e Computação — PESC/COPPE/UFRJ  
> **Participantes:** Reinaldo A. Simões · Luciana O. Dias

---

## Índice

1. [Motivação e contexto](#1-motivação-e-contexto)
2. [Proposta e hipóteses](#2-proposta-e-hipóteses)
3. [Arquitetura geral](#3-arquitetura-geral)
4. [Estrutura de arquivos](#4-estrutura-de-arquivos)
5. [Pipeline detalhada](#5-pipeline-detalhada)
6. [Avaliação](#6-avaliação)
7. [Resultados obtidos](#7-resultados-obtidos)
8. [Tecnologias e ferramentas](#8-tecnologias-e-ferramentas)
9. [Dificuldades e soluções](#9-dificuldades-e-soluções)
10. [Como executar](#10-como-executar)
11. [Requisitos](#11-requisitos)

---

## 1. Motivação e contexto

O **Pantheon** é o repositório institucional da UFRJ, construído sobre DSpace 5.3, e abriga milhares de teses e dissertações de todos os programas de pós-graduação da universidade. Embora esses documentos sejam publicamente acessíveis, existem como PDFs isolados — sem estrutura semântica, sem conexão entre si, e sem nenhuma forma de busca que vá além de palavras-chave no título ou no abstract.

A pergunta que motivou este projeto foi: **é possível extrair automaticamente o conhecimento científico contido nessas teses e organizá-lo em um grafo semântico navegável?**

Mais especificamente, queríamos capturar o **discurso científico**: o que cada tese afirma como resultado, quais limitações os autores reconhecem, quais contribuições declaram e quais direções de pesquisa futura propõem. Isso vai além da indexação tradicional — é entender a estrutura argumentativa do texto.

O projeto articula três áreas:

- **Mineração de texto estrutural** — ontologias de documentos científicos (DoCO, DEO) para mapear a estrutura retórica de teses
- **Web Semântica** — representação do conhecimento extraído como grafos RDF consultáveis via SPARQL
- **LLMs locais** — modelos de linguagem rodando sem dependência de APIs externas para extrair afirmações científicas

---

## 2. Proposta e critérios de avaliação

### Hipótese principal

> É possível extrair automaticamente elementos de discurso científico — afirmações, contribuições, limitações e direções de pesquisa futura — de teses e dissertações de engenharia com qualidade suficiente para revelar padrões temáticos e temporais no corpus, utilizando exclusivamente modelos de linguagem locais e ontologias abertas.

### Critérios verificáveis

**H1 — Viabilidade de extração:** um modelo de linguagem de pequeno porte, executado localmente sem ajuste fino, extrai elementos de discurso de seções de conclusão e resultados com taxa de sucesso ≥ 50% dos documentos elegíveis.

**H2 — Qualidade da extração:** a proporção de itens genéricos é ≤ 35% do total; o grafo RDF satisfaz as restrições formais das ontologias adotadas (SHACL); os campos de discurso são preenchidos em ≥ 2,0 de 4 possíveis por documento.

**H3 — Valor analítico do grafo:** consultas SPARQL revelam padrões não triviais — variação temporal no uso de técnicas, diferença de densidade de afirmações entre doutorado e mestrado, e perfis de limitação distintos entre áreas.

### Baseline

Busca direta nos metadados OAI-PMH (`dc:subject` CNPq), sem extração de conteúdo das seções. Representa o que o Pantheon oferece hoje, sem o projeto.

---

## 3. Arquitetura geral

```
┌──────────────────────────────────────────────────────────────┐
│                     Pantheon/UFRJ                             │
│             Repositório DSpace 5.3 (OAI-PMH)                 │
└─────────────────────┬────────────────────────────────────────┘
                      │ Dublin Core + PDFs organizados por área/ano
                      ▼
┌──────────────────────────────────────────────────────────────┐
│                  FASE 1 — Coleta                              │
│  collect_all_sets.py → manifest.jsonl                         │
│  PDFs em data/pdfs/{AREA}/{ANO}/                              │
└─────────────────────┬────────────────────────────────────────┘
                      │ ~2.441 PDFs + metadados
                      ▼
┌──────────────────────────────────────────────────────────────┐
│               FASE 2 — Extração Estrutural                    │
│  PDFs → [GROBID 0.8.1] → TEI XML                             │
│       → [tei_to_doco.py] → TTL RDF                           │
│       → [quality_gate.py] → validação 3 estágios             │
│  Ontologias: DoCO · DEO · C4O · FaBiO · PO · BiBO            │
└─────────────────────┬────────────────────────────────────────┘
                      │ ~2,2M triplas RDF
                      ▼
┌──────────────────────────────────────────────────────────────┐
│               FASE 3 — Análise e Consulta                     │
│  TTLs → [Apache Jena Fuseki TDB2]                            │
│  TEIs → [discourse_analysis.py / llama3.1:8b]                │
│       → claims · contribuições · limitações · futuro         │
│       → [enrich_graph.py] → +165k triplas de discurso        │
│  [fix_titles.py] → corrige títulos via SPARQL UPDATE         │
│  [sparql_queries.py + sparql_advanced.py] → 30 queries        │
└─────────────────────┬────────────────────────────────────────┘
                      │
                      ▼
┌──────────────────────────────────────────────────────────────┐
│                    AVALIAÇÃO                                   │
│  shacl_validate.py   → conformidade formal do grafo (W3C)    │
│  validate_graph.py   → integridade semântica via SPARQL      │
│  compare_models.py   → llama3.1:8b vs qwen2.5:14b            │
│  evaluate_project.py → veredicto H1 / H2 / H3                │
│  generate_report.py  → relatório final em Markdown            │
└──────────────────────────────────────────────────────────────┘
```

---

## 4. Estrutura de arquivos

```
projeto-artigos-buscas/
│
├── .gitignore
├── README.md                     ← Este arquivo
├── run_pipeline.py               ← Executa os 20 passos da pipeline
├── setup_env.py                  ← Verifica e instala dependências, Docker, ollama
├── setup_docker_env.py           ← Gera ambiente Docker completo e executa a pipeline
│
├── fase_1/                       ── COLETA OAI-PMH
│   ├── collect.py                ← Coleta de um único set OAI-PMH
│   ├── collect_all_sets.py       ← Coleta todos os sets COPPE em sequência
│   ├── config.py                 ← Endpoints, filtros, mapeamento set → área/ano
│   ├── README.md                 ← Documentação da fase 1
│   ├── requirements.txt
│   ├── diagnose_find_thesis_sets.py   ← Varre sets do Pantheon procurando teses
│   ├── diagnose_set.py                ← Inspeciona tipos e datas de um set
│   ├── diagnose-paths-url-pantheon.py ← Testa endpoints OAI-PMH
│   ├── diagnose-site-patheon-download-pdf.py ← Testa scraping de bistreams
│   └── src/
│       ├── oai_harvester.py      ← Cliente OAI-PMH com checkpoint e deduplicação
│       ├── dspace_client.py      ← Scraping HTML para URL do bitstream PDF
│       ├── pdf_downloader.py     ← Download paralelo; salva em {ÁREA}/{ANO}/
│       ├── http_client.py        ← Sessão HTTP com retry exponencial
│       └── logger_setup.py       ← Logging colorido + arquivo rotativo
│   (data/ gerado na execução)
│       ├── manifest.jsonl        ← Metadados de todos os documentos coletados
│       ├── metadata/             ← JSON individual por documento
│       └── pdfs/
│           ├── Engenharia_de_Sistemas/
│           │   ├── 2019/  └── *.pdf
│           │   └── 2020/  └── *.pdf
│           ├── Engenharia_Eletrica/
│           └── ...               ← Organizado por área CNPq e ano de publicação
│
├── fase_2/                       ── EXTRAÇÃO ESTRUTURAL + RDF
│   ├── grobid_setup.py           ← Sobe container GROBID 0.8.1 (Docker)
│   ├── process_pdfs.py           ← Envia PDFs ao GROBID; rglob recursivo
│   ├── tei_to_doco.py            ← TEI XML → Turtle RDF com ontologias SPAR
│   ├── quality_gate.py           ← Valida PDFs / TEIs / TTLs em 3 estágios
│   ├── validate_rdf.py           ← Integridade dos TTLs gerados
│   ├── README.md
│   └── requirements.txt
│   (data/ gerado na execução)
│       ├── tei/                  ← ~1.970 XMLs TEI
│       ├── rdf/                  ← ~1.970 TTLs RDF
│       ├── tei_rejected/         ← Rejeitados pelo quality gate
│       └── quality_reports/      ← Relatórios por estágio
│
├── fase_3/                       ── FUSEKI + DISCURSO + SPARQL
│   ├── fuseki_setup.py           ← Sobe Fuseki e carrega TTLs no grafo default
│   ├── discourse_analysis.py     ← Extrai claims/limitações/contribuições (llama3.1:8b)
│   ├── enrich_graph.py           ← Insere triplas de discurso no Fuseki
│   ├── sparql_queries.py         ← 20 queries de análise do corpus
│   ├── sparql_advanced.py        ← 10 queries aprofundadas
│   ├── fix_titles.py             ← Corrige títulos via SPARQL UPDATE usando manifest
│   ├── check_discourse.py        ← Relatório de qualidade da extração LLM
│   ├── diagnose_discourse.py     ← Diagnóstico de documentos sem seções-alvo
│   ├── diagnose_llm.py           ← Diagnóstico de conectividade e saúde do ollama
│   ├── README.md
│   └── requirements.txt
│   (data/ gerado na execução)
│       ├── discourse/            ← JSONs de análise por documento
│       └── discourse_report.jsonl ← Sumário de status (ok / no_target / failed)
│
└── avaliacao/                    ── AVALIAÇÃO E RELATÓRIO
    ├── shacl_validate.py         ← Conformidade formal dos TTLs (shapes SHACL W3C)
    ├── validate_graph.py         ← Integridade semântica do grafo via SPARQL
    ├── compare_models.py         ← Compara llama3.1:8b vs qwen2.5:14b em 30 docs
    ├── evaluate_project.py       ← Veredicto H1/H2/H3 com critérios da proposta
    ├── generate_report.py        ← Relatório final consolidado em Markdown
    ├── corpus_statistics.py      ← Estatísticas descritivas e gráficos do corpus
    └── data/
        ├── shacl_report.json          ← Resultado da validação SHACL
        ├── graph_integrity.json       ← Resultado da validação semântica
        ├── evaluation_results.json    ← Veredicto H1/H2/H3 (gerado pelo evaluate_project)
        ├── model_comparison/          ← Relatórios Markdown por par de modelos
        │   └── comparison_llama3.1_8b_vs_qwen2.5_7b.md
        └── run_logs/                  ← Logs de execução JSON por run
            └── run_YYYYMMDD_HHMMSS.json
```

---

## 5. Pipeline detalhada

A pipeline completa é orquestrada pelo `run_pipeline.py` em 20 passos:

| # | Passo | Script | Descrição |
|---|---|---|---|
| 1 | Coleta OAI-PMH | `fase_1/collect_all_sets.py` | Harvesting de metadados e PDFs do Pantheon |
| 2 | Subir GROBID | `fase_2/grobid_setup.py` | Container Docker GROBID 0.8.1 |
| 3 | Processar PDFs | `fase_2/process_pdfs.py` | PDFs → TEI XML (14 workers, recursivo) |
| 4 | Quality Gate TEI | `fase_2/quality_gate.py stage2` | Valida TEIs gerados |
| 5 | TEI → RDF | `fase_2/tei_to_doco.py` | TEI → Turtle com DoCO/DEO/FaBiO |
| 6 | Patch metadados | `fase_2/quality_gate.py stage3` | Corrige tipos/datas via manifest |
| 7 | Validar RDF | `fase_2/validate_rdf.py` | Integridade dos TTLs |
| 8 | SHACL | `avaliacao/shacl_validate.py` | Conformidade formal W3C |
| 9 | Subir Fuseki | `fase_3/fuseki_setup.py --reload` | Carrega TTLs no triplestore |
| 10 | Análise de discurso | `fase_3/discourse_analysis.py` | LLM extrai claims/limitações |
| 11 | Checar discurso | `fase_3/check_discourse.py` | Relatório de qualidade LLM |
| 12 | Comparar modelos | `avaliacao/compare_models.py` | llama3.1 vs qwen2.5 (30 docs) |
| 13 | Enriquecer grafo | `fase_3/enrich_graph.py` | Insere triplas de discurso |
| 14 | Corrigir títulos | `fase_3/fix_titles.py` | SPARQL UPDATE com manifest |
| 15 | SPARQL básico | `fase_3/sparql_queries.py` | 20 queries de análise |
| 16 | SPARQL avançado | `fase_3/sparql_advanced.py` | 10 queries aprofundadas |
| 17 | Integridade do grafo | `avaliacao/validate_graph.py` | Verificações semânticas SPARQL |
| 18 | Avaliar critérios | `avaliacao/evaluate_project.py` | Veredicto H1/H2/H3 |
| 19 | Gerar relatório | `avaliacao/generate_report.py` | Relatório Markdown final |
| 20 | Estatísticas do corpus | `avaliacao/corpus_statistics.py` | Gera estatísticas descritivas, gráficos e relatório consolidado do corpus |

### Fase 1 — Coleta

O protocolo **OAI-PMH** exposto pelo DSpace em `https://pantheon.ufrj.br/oai/request` permite listar registros por conjuntos temáticos e baixar metadados em Dublin Core. O DSpace não expõe links para PDFs no OAI-PMH, então `dspace_client.py` faz scraping HTML de cada página de item para encontrar a URL do bitstream, com fallback para a API REST.

Os PDFs são salvos organizados por área CNPq e ano de publicação em `data/pdfs/{AREA}/{ANO}/`. A área é determinada pelo set OAI-PMH coletado (mapeado em `config.SET_AREA_SLUG`); o ano vem do campo `dc:date`. O `process_pdfs.py` na fase seguinte usa `rglob("*.pdf")` para varrer recursivamente.

Os conjuntos coletados cobrem 13 programas da COPPE. Filtros: tipo "Tese" ou "Dissertação", publicados a partir de 2000.

### Fase 2 — Extração Estrutural

**GROBID 0.8.1** processa cada PDF e extrai XML TEI com seções, parágrafos, referências e metadados. O `tei_to_doco.py` mapeia cada elemento para as ontologias SPAR:

```turtle
base:11422_5432 a fabio:DoctoralThesis, fabio:Work ;
    dcterms:title "Otimização de Redes Neurais..." ;
    dcterms:creator "João Silva" ;
    dcterms:date "2020-03-15" ;
    dcterms:subject "CNPQ::ENGENHARIAS::ENGENHARIA ELETRICA" ;
    po:contains base:11422_5432_sec_3 .

base:11422_5432_sec_3 a deo:Conclusion, doco:Section ;
    dcterms:title "Conclusões" ;
    po:contains base:11422_5432_sec_3_para_0 .

base:11422_5432_sec_3_para_0 a doco:Paragraph ;
    c4o:hasContent "Os resultados demonstram que a arquitetura proposta..." .
```

O `quality_gate.py` opera em três estágios: valida PDFs (magic bytes, tamanho), TEIs (corpo não vazio, proporção de ruído OCR, número mínimo de seções), e TTLs (triplas mínimas, metadados do manifest).

### Fase 3 — Análise e Consulta

**Fuseki** recebe todos os TTLs via upload HTTP e indexa no TDB2. As triplas são carregadas no *default graph* para que queries SPARQL funcionem sem `GRAPH ?g { }`.

**discourse_analysis.py** identifica seções retoricamente relevantes pelo título (conclusões, resultados, discussões) e envia cada seção ao llama3.1:8b via ollama, solicitando extração JSON. O prompt instrui o modelo a rejeitar afirmações genéricas. JSONs truncados são reparados automaticamente.

**enrich_graph.py** converte os JSONs em triplas RDF usando a ontologia `discourse#` e as insere no Fuseki.

**fix_titles.py** usa o manifest como fonte autoritativa para corrigir títulos problemáticos diretamente no Fuseki via SPARQL UPDATE.

### Ontologia de discurso customizada

Namespace: `http://pantheon.ufrj.br/ontology/discourse#`

| Elemento | Tipo | Descrição |
|---|---|---|
| `discourse:ScientificClaim` | Classe | Afirmação factual de resultados/conclusão |
| `discourse:Contribution` | Classe | Contribuição declarada pelos autores |
| `discourse:Limitation` | Classe | Limitação reconhecida no texto |
| `discourse:FutureWork` | Classe | Direção de pesquisa futura mencionada |
| `discourse:hasClaim` | Propriedade | Documento → ScientificClaim |
| `discourse:hasContribution` | Propriedade | Documento → Contribution |
| `discourse:hasLimitation` | Propriedade | Documento → Limitation |
| `discourse:hasFutureWork` | Propriedade | Documento → FutureWork |
| `discourse:inferredKeyword` | Propriedade | Documento → keyword técnica |
| `discourse:inSection` | Propriedade | Claim/Limitation → seção de origem (DEO) |

---

## 6. Avaliação

A avaliação combina três instrumentos complementares.

### 6.1 Validação SHACL — conformidade formal

`avaliacao/shacl_validate.py` valida cada nó do grafo contra shapes SHACL W3C. Dois tipos de problemas são distinguidos:

- **Violação** — quebra uma restrição crítica (ex: documento sem título). Indica problema real.
- **Aviso** — quebra uma restrição informativa (ex: abstract curto). Pode ser limitação do GROBID em PDFs históricos.

O indicador central é a **taxa de violações críticas** — não a conformidade total, que inclui avisos esperados e tende a ser baixa mesmo com o grafo correto.

### 6.2 Validação de integridade semântica

`avaliacao/validate_graph.py` executa queries SPARQL verificando a consistência das relações: seções sem documento pai, claims sem conteúdo, handles duplicados, títulos suspeitos.

| Aspecto | SHACL | Integridade semântica |
|---|---|---|
| O que testa | Forma de cada nó | Relações entre nós |
| Padrão | W3C SHACL 1.0 | SPARQL 1.1 |
| Detecta | Metadados ausentes, tipos incorretos | Órfãos, duplicatas, relações quebradas |

### 6.3 Avaliação dos critérios de aceitação

`avaliacao/evaluate_project.py` lê os artefatos da pipeline e verifica cada critério da proposta, exibindo para cada hipótese a pergunta, o critério, o valor medido e um veredicto — sem narrativa conclusiva.

### 6.4 Comparação de modelos LLM

`avaliacao/compare_models.py` avalia llama3.1:8b e qwen2.5:7b em 30 documentos nas dimensões de confiabilidade, qualidade e eficiência.

---

## 7. Resultados obtidos

### Corpus (COPPE completo)

Resultados atualizados da última rodada: `avaliacao/data/corpus_analysis.md`.

### Análise de discurso

Resultados atualizados da última rodada: `avaliacao/relatorio_final.md`.

### Transição paradigmática detectada automaticamente

Resultados atualizados da última rodada: `avaliacao/relatorio_final.md`.

### Comparação de modelos LLM

Resultados atualizados da última rodada: `avaliacao/relatorio_final.md`.

---

## 8. Tecnologias e ferramentas

| Categoria | Tecnologia | Uso |
|---|---|---|
| **Repositório fonte** | Pantheon/UFRJ (DSpace 5.3) | PDFs e metadados |
| **Protocolo de coleta** | OAI-PMH | Harvesting automatizado |
| **Extração de estrutura** | GROBID 0.8.1 (Docker) | PDF → XML TEI |
| **Formato intermediário** | XML TEI P5 | Representação estruturada |
| **Ontologia de documentos** | DoCO (Document Components Ontology) | Seção, Parágrafo, Lista |
| **Ontologia de discurso** | DEO (Discourse Elements Ontology) | Introdução, Conclusão, Métodos |
| **Ontologia bibliográfica** | FaBiO, BiBO, C4O | Metadados e referências |
| **Validação formal** | SHACL W3C (pyshacl) | Conformidade das ontologias |
| **Mapeamento RDF** | rdflib 7.0.0 (Python) | TEI → Turtle |
| **Triplestore** | Apache Jena Fuseki (Docker, TDB2) | Armazenamento e consulta SPARQL |
| **Linguagem de consulta** | SPARQL 1.1 | Análise do corpus |
| **LLM local** | llama3.1:8b via ollama | Extração de discurso científico |
| **Linguagem** | Python 3.14 | Toda a pipeline |
| **Hardware** | Ryzen 9 7900 · 16GB RAM · RTX 4070 Super 12GB | Processamento local |

### Por que essas escolhas?

**GROBID** foi escolhido por ser o estado da arte em extração de estrutura de PDFs científicos, especialmente para referências bibliográficas e identificação de seções. A alternativa seria regras heurísticas, mas GROBID usa modelos de ML treinados em milhares de artigos científicos.

**Ontologias SPAR** (DoCO, DEO, FaBiO) foram escolhidas por serem um conjunto coerente e amplamente adotado para representar documentos científicos em RDF. Elas permitem expressar não apenas "aqui está um parágrafo" mas "este parágrafo é parte de uma seção de Conclusão de uma Tese de Doutorado".

**Fuseki** foi escolhido por ser a implementação de referência do Apache Jena, robusta para corpora dessa escala e com suporte nativo a TDB2 para persistência eficiente.

**llama3.1:8b** foi escolhido após comparação experimental com qwen2.5:7b, com melhor qualidade de extração (83% vs 0% de tipo retórico correto) e maior robustez de saída JSON no teste mais recente.

**ollama** foi escolhido para rodar os modelos localmente, sem custo de API e sem enviar dados de pesquisa para servidores externos — importante para um corpus acadêmico de uma instituição pública.

---

## 9. Dificuldades e soluções

**Endpoint OAI-PMH incorreto** — `/oai` retornava HTTP 400. O correto é `/oai/request`, descoberto por inspeção manual.

**URLs de PDFs não expostas no OAI-PMH** — o DSpace não inclui links para bistreams. Solução: scraping HTML com fallback para REST API do DSpace.

**Organização por tópico/ano** — o OAI-PMH não informa a pasta de destino. Solução: `config.SET_AREA_SLUG` mapeia cada set para um slug de área; injetado como `_area_slug` em cada record antes do download. O `pdf_downloader.py` chama `config.get_pdf_dir(record)` para calcular o caminho organizado.

**Formato de data ISO no Fuseki** — datas `2020-03-15T18:34:16Z` causavam falha nas queries. Solução: `BIND(SUBSTR(STR(?date), 1, 4) AS ?ano)` com `FILTER(STRLEN(?ano)=4)`.

**SPARQL GROUP BY com expressões** — o Jena não aceita expressões diretamente no `GROUP BY`. Solução: `BIND` dentro do `WHERE`.

**Regex no Fuseki** — o parser rejeita `\s*` e `[0-9]+`. Solução: `CONTAINS()` e filtros combinados.

**GROBID capturando agradecimentos como título** — teses antigas onde o GROBID capturava o primeiro texto disponível. Solução: `is_bad_title()` em `tei_to_doco.py`; `fix_titles.py` corrige 681 títulos diretamente no Fuseki via SPARQL UPDATE.

**Títulos irrecuperáveis (7 docs)** — o manifest OAI-PMH também tinha título incorreto (OCR garbage de PDFs dos anos 70-80). Limitação do repositório de origem — não há fonte melhor disponível.

**Metadados ausentes no grafo** — caminho relativo no `tei_to_doco.py` causava falha ao executar de outro diretório. Solução: `os.path.abspath(__file__)`.

**JSON truncado pelo LLM** — `num_predict` baixo cortava o JSON. Solução: função `extract_json()` que conta `{` e `[` abertos e injeta fechamentos faltantes.

**Triplas em named graphs** — queries sem `GRAPH ?g {}` retornavam vazio. Solução: remoção do parâmetro `graph` do upload, enviando tudo para o default graph.

**SHACL com sintaxe Turtle conflitando com Python** — o prefixo vazio (`:`) dentro de uma string `"""` causava `BadSyntax`. Solução: declarar `@base` e `@prefix :` explicitamente.

**Seções órfãs no validate_graph** — 148 seções detectadas como sem documento pai. Investigação revelou artefatos de OCR de PDFs históricos (`??ir~`, `-viii`). Rebaixado para check informativo.

---

## 10. Como executar

### Pré-requisitos

```bash
# 1. Clone o repositório
git clone https://github.com/ziggy-data/projeto-busca-mineracao-de-texto-artigos-cientificos
cd projeto-busca-mineracao-de-texto-artigos-cientificos

# 2. Verifique e instale o ambiente
python setup_env.py

# 3. Modelos LLM
ollama pull llama3.1:8b
ollama pull nomic-embed-text

# 4. Imagens Docker
docker pull lfoppiano/grobid:0.8.1
docker pull secoresearch/fuseki
```

### Pipeline completa

```bash
python run_pipeline.py
```

> Tempo estimado: 15–20 horas (coleta + GROBID + análise de discurso com GPU)

### Opção alternativa: executar com Docker (setup_docker_env.py)

Use esta opção para rodar a pipeline em containers, sem depender do setup local com `setup_env.py`.

Pré-requisitos Docker:

- Python 3.10+ no host (necessário para executar `setup_docker_env.py`).
- Docker instalado e em execução no host.
- Docker Compose (`docker compose`) disponível.
- Para execução com GPU (`--gpu`/`--gpulabel`): NVIDIA Container Toolkit instalado no host.

Documentação oficial de instalação:

- Docker Engine: https://docs.docker.com/engine/install/
- Docker Desktop: https://docs.docker.com/desktop/
- Docker Compose: https://docs.docker.com/compose/install/
- NVIDIA Container Toolkit: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html

```bash
# 1. Gera Dockerfile/compose auxiliares
python setup_docker_env.py --generate

# 2. Build da imagem da aplicação e subida dos serviços
python setup_docker_env.py --build --up

# 3. Baixa modelos no ollama (primeira execução)
python setup_docker_env.py --pull-models

# 4. Executa a pipeline dentro do container app
python setup_docker_env.py --run-pipeline

# 5. Fluxo integrado (build + serviços + modelos + pipeline)
python setup_docker_env.py --build --up --pull-models --run-pipeline

# 6. Fluxo integrado com GPU (quando disponível)
python setup_docker_env.py --gpu --build --up --pull-models --run-pipeline

# 7. Fluxo integrado com GPU específica (ex.: GPU 0)
python setup_docker_env.py --gpulabel 0 --build --up --pull-models --run-pipeline
```

Exemplos adicionais:

```bash
# Rodar a pipeline a partir de um passo
python setup_docker_env.py --run-pipeline --pipeline-args --from-step fase_3_fuseki

# Derrubar os serviços
python setup_docker_env.py --down

# Roda todo processo do início ao fim e depois derrubar os serviços
python setup_docker_env.py --gpu --gpulabel 0 --build --up --pull-models --run-pipeline --down
```

Notas sobre GPU no setup Docker:

- `--gpu`: habilita uso de GPU nos serviços `app` e `ollama` (quando disponível no host).
- `--gpulabel <id>`: seleciona explicitamente qual GPU usar (por exemplo `0`, `1` ou UUID NVIDIA).
- `--gpulabel` também ativa modo GPU automaticamente, mesmo sem `--gpu`.

### Retomada parcial

```bash
# Pula coleta e GROBID (dados já existem)
python run_pipeline.py --skip-collect --skip-grobid

# Retoma a partir de um passo específico
python run_pipeline.py --from-step fase_3_fuseki

# Só avaliação e relatório
python run_pipeline.py --from-step avaliacao_shacl

# Executa apenas um passo
python run_pipeline.py --only avaliacao_report
```

### Execução manual por fase

```bash
# Fase 1 — Coleta
cd fase_1 && python collect_all_sets.py

# Fase 2 — Extração
cd ../fase_2
python grobid_setup.py && python process_pdfs.py
python quality_gate.py stage2 && python tei_to_doco.py
python quality_gate.py stage3 --patch && python validate_rdf.py

# SHACL (roda antes do Fuseki)
cd ../avaliacao
python shacl_validate.py --export data/shacl_report.json

# Fase 3 — Análise
cd ../fase_3
python fuseki_setup.py --reload
python discourse_analysis.py --model llama3.1:8b
python check_discourse.py && python enrich_graph.py
python fix_titles.py --manifest ../fase_1/data/manifest.jsonl
python sparql_queries.py && python sparql_advanced.py

# Avaliação completa
cd ../avaliacao
python validate_graph.py --export data/graph_integrity.json
python compare_models.py --limit 30
python evaluate_project.py --export data/evaluation_results.json
python generate_report.py
```

### Queries SPARQL interativas

Com o Fuseki rodando, acesse `http://localhost:3030` (admin / pantheon123) para o console web de SPARQL, ou use os scripts:

```bash
# Query específica
python fase_3/sparql_queries.py --query 8

# Busca livre em claims
python fase_3/sparql_queries.py --query 8
# (edite a query 8 no arquivo para mudar o termo de busca)
```

### Exemplo de query SPARQL

```sparql
PREFIX fabio:     <http://purl.org/spar/fabio/>
PREFIX dcterms:   <http://purl.org/dc/terms/>
PREFIX discourse: <http://pantheon.ufrj.br/ontology/discourse#>
PREFIX c4o:       <http://purl.org/spar/c4o/>

SELECT ?titulo ?ano ?claim
WHERE {
  ?doc a fabio:MastersThesis .
  ?doc dcterms:title ?titulo .
  ?doc dcterms:date ?date .
  BIND(SUBSTR(STR(?date), 1, 4) AS ?ano)
  FILTER(?ano >= "2018")
  ?doc discourse:hasClaim ?c .
  ?c c4o:hasContent ?claim .
  FILTER(CONTAINS(LCASE(?claim), "machine learning"))
}
ORDER BY DESC(?ano) LIMIT 10
```

---

## 11. Requisitos

### Software

| Software | Versão | Uso |
|---|---|---|
| Python | ≥ 3.10 | Toda a pipeline |
| Docker Desktop | Recente | GROBID e Fuseki |
| ollama | Recente | LLM |

### Pacotes Python

```
requests==2.31.0
sickle==0.7.0
beautifulsoup4==4.12.3
colorlog
rdflib==7.0.0
pyshacl
tqdm
tabulate==0.9.0
numpy
```

### Hardware mínimo recomendado

| Componente | Mínimo | Usado no projeto |
|---|---|---|
| CPU | 6 cores | Ryzen 9 7900 (12 cores) |
| RAM | 16 GB | 16 GB |
| GPU VRAM | 8 GB | RTX 4070 Super (12 GB) |
| Armazenamento | 50 GB livres | — |

> Sem GPU: a análise de discurso leva ~17h em CPU (vs ~3-4h com GPU).

---

*Projeto desenvolvido para a disciplina Busca e Mineração de Texto — PESC/COPPE/UFRJ*
