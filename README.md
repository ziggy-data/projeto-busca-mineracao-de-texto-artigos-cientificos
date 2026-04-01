# Grafo de Conhecimento de Discurso Científico — Pantheon/UFRJ

> Projeto desenvolvido para a disciplina **Busca e Mineração de Texto**  
> Programa de Pós-Graduação em Engenharia de Sistemas e Computação — COPPE/UFRJ

> Participantes: Reinaldo A. Simoes e Luciana O. Dias
---

## Índice

1. [Motivação e Contexto](#1-motivação-e-contexto)
2. [O que foi feito](#2-o-que-foi-feito)
3. [Arquitetura geral](#3-arquitetura-geral)
4. [Tecnologias e ferramentas](#4-tecnologias-e-ferramentas)
5. [Estrutura de arquivos](#5-estrutura-de-arquivos)
6. [Pipeline detalhada](#6-pipeline-detalhada)
7. [Resultados obtidos](#7-resultados-obtidos)
8. [Dificuldades e soluções](#8-dificuldades-e-soluções)
9. [Como executar](#9-como-executar)
10. [Requisitos](#10-requisitos)

---

## 1. Motivação e Contexto

O **Pantheon** é o repositório institucional da UFRJ, construído sobre DSpace 5.3, e abriga milhares de teses e dissertações de todos os programas de pós-graduação da universidade. Embora esses documentos estejam acessíveis publicamente, eles existem como PDFs isolados — sem estrutura semântica, sem conexões entre si, e sem nenhuma forma de busca que vá além de palavras-chave no título ou no abstract.

A pergunta que motivou este projeto foi: **é possível extrair automaticamente o conhecimento científico contido nessas teses e organizá-lo em um grafo semântico navegável?**

Mais especificamente, queríamos ir além da indexação tradicional e capturar o **discurso científico**: o que cada tese afirma como resultado, quais limitações os autores reconhecem, quais contribuições declaram, e quais direções de pesquisa futura propõem. Isso é diferente de buscar um termo em um PDF — é entender a estrutura argumentativa do texto.

O projeto nasceu da combinação de três áreas:

- **Mineração de texto estrutural** — usando ontologias de documentos científicos (DoCO, DEO) para mapear a estrutura retórica de teses
- **Web Semântica** — representando o conhecimento extraído como grafos RDF consultáveis via SPARQL
- **LLMs locais** — usando modelos de linguagem rodando localmente (sem dependência de APIs pagas) para extrair afirmações científicas das seções de conclusão e resultados

---

## 2. O que foi feito

O projeto construiu uma pipeline completa de ponta a ponta:

1. **Coleta automatizada** de 2.441 PDFs do repositório Pantheon via protocolo OAI-PMH, cobrindo 13 conjuntos temáticos da COPPE (Engenharia Civil, Elétrica, Química, Nuclear, Naval, Biomédica, entre outras)

2. **Extração estrutural** dos PDFs usando GROBID, gerando XML no formato TEI com seções, parágrafos, referências e metadados identificados automaticamente

3. **Mapeamento ontológico** do TEI para RDF usando as ontologias SPAR (DoCO, DEO, C4O, FaBiO), resultando em 2,2 milhões de triplas que representam a estrutura de cada documento

4. **Armazenamento** dessas triplas no Apache Jena Fuseki, um triplestore que permite consultas SPARQL sobre o corpus inteiro

5. **Análise de discurso científico** com LLM local (llama3.1:8b via ollama), extraindo automaticamente claims, contribuições, limitações e direções de trabalho futuro de 1.366 documentos

6. **Enriquecimento do grafo** com as 165.312 triplas de discurso extraídas pelo LLM, usando uma ontologia customizada

7. **Análise do corpus** via 20+ queries SPARQL, revelando padrões como a transição do uso de Elementos Finitos para Machine Learning entre 2017 e 2020

8. **Comparação de modelos LLM** (llama3.1:8b vs qwen2.5:14b-instruct) com métricas objetivas de qualidade de extração

9. **Geração automática de relatório** em Markdown com todas as estatísticas do corpus

---

## 3. Arquitetura geral

```
┌─────────────────────────────────────────────────────────────────┐
│                      Pantheon/UFRJ                               │
│              Repositório DSpace 5.3 (OAI-PMH)                   │
└──────────────────────────┬──────────────────────────────────────┘
                           │ OAI-PMH (XML Dublin Core)
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                        FASE 1 — Coleta                          │
│   collect_all_sets.py → manifest.jsonl + 2.441 PDFs             │
└──────────────────────────┬──────────────────────────────────────┘
                           │ PDFs + metadados
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                   FASE 2 — Extração Estrutural                  │
│                                                                  │
│   PDFs → [GROBID 0.8.1] → 1.970 TEI XMLs                       │
│        → [tei_to_doco.py] → 1.970 TTLs RDF                     │
│        → [quality_gate.py] → validação e correção               │
│                                                                  │
│   Ontologias: DoCO · DEO · C4O · FaBiO · PO · BiBO             │
└──────────────────────────┬──────────────────────────────────────┘
                           │ ~2,2M triplas RDF
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                   FASE 3 — Análise e Consulta                   │
│                                                                  │
│   TTLs → [Apache Jena Fuseki] ← SPARQL queries                 │
│                ↑                                                  │
│   [discourse_analysis.py]  ← llama3.1:8b (ollama)             │
│   TEIs → extrai claims/limitações/contribuições                 │
│        → [enrich_graph.py] → +165.312 triplas                  │
│                                                                  │
│   Ontologia customizada: discourse#ScientificClaim, etc.        │
└──────────────────────────┬──────────────────────────────────────┘
                           │ Resultados SPARQL + JSONs
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                      AVALIAÇÃO                                   │
│   generate_report.py → relatorio_final.md                       │
│   compare_models.py  → comparação llama3.1 vs qwen2.5           │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. Tecnologias e ferramentas

| Categoria | Tecnologia | Uso no projeto |
|---|---|---|
| **Repositório fonte** | Pantheon/UFRJ (DSpace 5.3) | Fonte dos PDFs e metadados |
| **Protocolo de coleta** | OAI-PMH | Harvesting automatizado de metadados |
| **Extração de estrutura** | GROBID 0.8.1 (Docker) | PDF → XML TEI com seções e referências |
| **Formato intermediário** | XML TEI P5 | Representação estruturada dos documentos |
| **Ontologia de documentos** | DoCO (Document Components Ontology) | Estrutura física: Seção, Parágrafo, Lista |
| **Ontologia de discurso** | DEO (Discourse Elements Ontology) | Retórica: Introdução, Conclusão, Métodos |
| **Ontologia bibliográfica** | FaBiO, BiBO, C4O | Metadados e referências bibliográficas |
| **Mapeamento RDF** | rdflib 7.0.0 (Python) | Conversão TEI → Turtle RDF |
| **Triplestore** | Apache Jena Fuseki (Docker, TDB2) | Armazenamento e consulta SPARQL |
| **Linguagem de consulta** | SPARQL 1.1 | Análise do corpus |
| **LLM local** | llama3.1:8b via ollama | Extração de discurso científico |
| **Embeddings** | nomic-embed-text via ollama | Busca semântica (IR) |
| **Linguagem** | Python 3.14 | Toda a pipeline |
| **Sistema operacional** | Windows 11 | Ambiente de desenvolvimento |
| **Hardware** | Ryzen 9 7900 · 16GB RAM · RTX 4070 Super 12GB | Processamento local |

### Por que essas escolhas?

**GROBID** foi escolhido por ser o estado da arte em extração de estrutura de PDFs científicos, especialmente para referências bibliográficas e identificação de seções. A alternativa seria regras heurísticas, mas GROBID usa modelos de ML treinados em milhares de artigos científicos.

**Ontologias SPAR** (DoCO, DEO, FaBiO) foram escolhidas por serem um conjunto coerente e amplamente adotado para representar documentos científicos em RDF. Elas permitem expressar não apenas "aqui está um parágrafo" mas "este parágrafo é parte de uma seção de Conclusão de uma Tese de Doutorado".

**Fuseki** foi escolhido por ser a implementação de referência do Apache Jena, robusta para corpora dessa escala e com suporte nativo a TDB2 para persistência eficiente.

**llama3.1:8b** foi escolhido após comparação experimental com qwen2.5:14b-instruct, onde o modelo menor venceu em qualidade de extração (96% vs 13% de tipo retórico correto), velocidade e ausência de falhas.

**ollama** foi escolhido para rodar os modelos localmente, sem custo de API e sem enviar dados de pesquisa para servidores externos — importante para um corpus acadêmico de uma instituição pública.

---

## 5. Estrutura de arquivos

```
projeto-artigos-buscas/
│
├── setup_env.py               ← Prepara o ambiente (instala deps, verifica Docker/ollama)
├── run_pipeline.py            ← Executa o pipeline completo ou por fases
│
├── fase_1/                    ← COLETA OAI-PMH
│   ├── collect.py             ← Coleta de um único conjunto (set)
│   ├── collect_all_sets.py    ← Coleta de todos os conjuntos COPPE em sequência
│   ├── config.py              ← Configurações: URL OAI, sets, filtros de ano/tipo
│   └── src/
│       ├── oai_harvester.py   ← Cliente OAI-PMH com checkpoint e deduplicação
│       ├── dspace_client.py   ← Scraping HTML para obter URLs dos PDFs
│       ├── pdf_downloader.py  ← Download paralelo com validação de PDF
│       ├── http_client.py     ← Sessão HTTP com retry automático
│       └── logger_setup.py    ← Logging colorido
│   └── data/
│       ├── manifest.jsonl     ← Metadados de todos os documentos coletados
│       └── pdfs/              ← 2.441 PDFs baixados
│
├── fase_2/                    ← EXTRAÇÃO ESTRUTURAL + RDF
│   ├── grobid_setup.py        ← Sobe container Docker com GROBID 0.8.1
│   ├── process_pdfs.py        ← Envia PDFs ao GROBID (14 workers paralelos)
│   ├── tei_to_doco.py         ← Converte TEI XML → RDF Turtle com DoCO/DEO
│   ├── quality_gate.py        ← Valida PDFs, TEIs e TTLs em 3 estágios
│   ├── validate_rdf.py        ← Validação de integridade dos TTLs
│   └── data/
│       ├── tei/               ← 1.970 XMLs TEI gerados pelo GROBID
│       ├── rdf/               ← 1.970 TTLs RDF com ontologias SPAR
│       ├── tei_rejected/      ← TEIs rejeitados pelo quality gate
│       └── quality_reports/   ← Relatórios de qualidade por estágio
│
├── fase_3/                    ← FUSEKI + DISCURSO + SPARQL
│   ├── fuseki_setup.py        ← Sobe Fuseki e carrega TTLs no triplestore
│   ├── discourse_analysis.py  ← Extrai discurso via LLM (claims, limitações, etc.)
│   ├── enrich_graph.py        ← Insere triplas de discurso no Fuseki
│   ├── sparql_queries.py      ← 20 queries de análise do corpus
│   ├── sparql_advanced.py     ← 10 queries de análise aprofundada
│   ├── fix_titles.py          ← Corrige títulos errados no Fuseki via SPARQL UPDATE
│   ├── check_discourse.py     ← Relatório de qualidade da análise LLM
│   ├── diagnose_discourse.py  ← Diagnóstico de documentos sem seções-alvo
│   ├── diagnose_llm.py        ← Diagnóstico de conectividade e saúde do ollama
│   ├── ir_search.py           ← Sistema de IR estrutural (BM25 + embeddings)
│   └── data/
│       ├── discourse/         ← 1.970 JSONs com análise de discurso por documento
│       ├── enriched/          ← TTLs com triplas de discurso
│       ├── ir_index/          ← Índice BM25 + embeddings para busca semântica
│       └── model_comparison/  ← Relatórios de comparação entre modelos LLM
│
└── avaliacao/                 ← RELATÓRIOS E AVALIAÇÃO
    ├── generate_report.py     ← Gera relatório final em Markdown (coleta dados do Fuseki)
    ├── compare_models.py      ← Compara qualidade de extração entre dois modelos LLM
    ├── relatorio_final.md     ← Relatório gerado automaticamente
    └── run_logs/              ← Logs de execução da pipeline em JSON
```

---

## 6. Pipeline detalhada

### Fase 1 — Coleta

O ponto de entrada é o protocolo **OAI-PMH** (Open Archives Initiative Protocol for Metadata Harvesting), que o DSpace expõe em `https://pantheon.ufrj.br/oai/request`. O protocolo permite listar registros por conjuntos temáticos (sets) e baixar os metadados em Dublin Core.

O desafio imediato foi descobrir o endpoint correto: o endereço `/oai` retorna HTTP 400, sendo o correto `/oai/request`. O segundo desafio foi descobrir o padrão de URL dos PDFs: o DSpace não expõe os links diretamente no OAI-PMH, então o código faz scraping HTML de cada página de item para extrair a URL do bitstream.

Os conjuntos coletados cobrem o PESC (Engenharia de Sistemas e Computação) e todas as subáreas da COPPE: Civil, Elétrica, Química, Naval, Mecânica, Nuclear, Biomédica, Transportes, Produção, Materiais e Metalúrgica.

O filtro aplicado: documentos do tipo "Tese" ou "Dissertação" publicados a partir do ano 2000.

### Fase 2 — Extração Estrutural

**GROBID** processa cada PDF e extrai um XML no formato TEI (Text Encoding Initiative) com:
- Metadados do documento (título, autores, data, afiliações)
- Estrutura de seções (com títulos identificados)
- Conteúdo de cada parágrafo
- Lista de referências bibliográficas com autores, título, ano e venue

O script `tei_to_doco.py` percorre cada TEI e produz um arquivo Turtle RDF mapeando cada elemento para a ontologia correspondente:

```turtle
base:11422_5432 a fabio:DoctoralThesis, fabio:Work ;
    dcterms:title "Otimização de Redes Neurais para Previsão de Séries Temporais" ;
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

O `quality_gate.py` opera em três estágios: valida PDFs (magic bytes, tamanho), valida TEIs (corpo não vazio, proporção de ruído OCR, número mínimo de seções), e valida TTLs (triplas mínimas, metadados do manifest).

### Fase 3 — Análise e Consulta

**Fuseki** recebe todos os TTLs via upload HTTP e os indexa no formato TDB2. As triplas são carregadas no *default graph* (sem named graphs) para que queries SPARQL simples funcionem sem `GRAPH ?g { }`.

**discourse_analysis.py** percorre os TEIs identificando seções retoricamente relevantes (conclusões, resultados, discussões, considerações finais) pelo título da seção. Para cada seção encontrada, envia um prompt ao llama3.1:8b pedindo extração estruturada em JSON.

O prompt instrui o modelo a rejeitar afirmações genéricas ("este capítulo apresenta...") e extrair apenas conteúdo substantivo. O resultado é validado e reparado se o JSON vier truncado.

**enrich_graph.py** converte os JSONs de discurso em triplas RDF usando a ontologia customizada `discourse#`, mantendo a ligação com o documento original e a seção de origem.

---

## 7. Resultados obtidos

### Corpus

| Métrica | Valor |
|---|---|
| Documentos coletados | 2.441 |
| PDFs processados pelo GROBID | 1.970 (81%) |
| TTLs RDF gerados | 1.970 |
| Triplas totais no grafo | ~2.365.312 |
| Teses de Doutorado | 515 |
| Dissertações de Mestrado | 1.455 |
| Seções estruturadas | 76.239 |
| Parágrafos | 353.031 |

### Análise de Discurso

| Métrica | Valor |
|---|---|
| Documentos analisados com sucesso | 1.366 (69,3%) |
| Documentos sem seções-alvo | 597 (30,3%) |
| Falhas LLM | 7 (0,4%) |
| Claims extraídos | 12.344 |
| Contribuições extraídas | 7.222 |
| Limitações extraídas | 3.031 |
| Trabalhos futuros extraídos | 5.430 |
| Triplas de discurso inseridas | 165.312 |

### Achado principal

A query que cruza subjects CNPq com ano de publicação revelou uma **inversão de paradigma** no corpus entre 2017 e 2020:

| Ano | Machine Learning | Elementos Finitos |
|---|---|---|
| 2017 | 0 | 22 |
| 2018 | 0 | 9 |
| 2019 | 6 | 7 |
| 2020 | 13 | 3 |
| 2021 | 6 | 7 |

Essa transição foi detectada **automaticamente por mineração de texto**, sem nenhuma intervenção manual.

### Comparação de modelos LLM

| Métrica | llama3.1:8b | qwen2.5:14b-instruct |
|---|---|---|
| Tipo retórico correto | **96%** | 13% |
| Itens específicos/doc | **1,9** | 0,9 |
| Campos preenchidos/doc | **0,7/4** | 0,4/4 |
| Tempo médio/request | **7,0s** | 10,2s |
| JSON inválido | **0%** | 0% |

Conclusão: modelos maiores não necessariamente produzem melhor qualidade em tarefas especializadas de extração de discurso científico.

---

## 8. Dificuldades e soluções

### Endpoint OAI-PMH incorreto

O endpoint documentado do Pantheon (`/oai`) retornava HTTP 400. Descobrimos via inspeção manual que o correto é `/oai/request`. O código tem o URL hardcoded com comentário explicativo.

### URLs de PDFs não expostas via OAI-PMH

O DSpace não inclui os links diretos para os PDFs nos registros OAI-PMH. A solução foi scraping HTML de cada página de item para extrair a URL do bitstream, com fallback para a API REST do DSpace.

### Formato de data ISO no Fuseki

As datas armazenadas no formato `2020-03-15T18:34:16Z` causavam falha nas queries que tentavam extrair o ano com `SUBSTR`. A solução foi usar `BIND(SUBSTR(STR(?date), 1, 4) AS ?ano)` com filtro de comprimento em vez de expressões regulares.

### SPARQL GROUP BY com expressões

O Apache Jena não aceita expressões diretamente no `GROUP BY` (ex: `GROUP BY (SUBSTR(...) AS ?ano)`). A solução foi usar `BIND` dentro do `WHERE` para criar a variável antes do agrupamento.

### Regex no Fuseki

O parser de regex do Jena é muito restritivo com caracteres de escape. Expressões como `\s*` ou `[0-9]+` dentro de strings SPARQL causavam erros de parse. A solução foi substituir por `CONTAINS()` e filtros combinados.

### TEI title extraindo seção de agradecimentos como título

O GROBID frequentemente capturava a seção de agradecimentos ou a lista de figuras como título do documento em teses antigas. O `tei_to_doco.py` implementa `is_bad_title()` com padrões de detecção, usando o título do manifest como fallback autoritativo. O `fix_titles.py` corrigiu 681 títulos diretamente no Fuseki via SPARQL UPDATE.

### Metadados ausentes no grafo

O `tei_to_doco.py` original usava `MANIFEST = "../data/manifest.jsonl"` com caminho relativo ao diretório de execução, não ao script. Isso fazia com que o manifest não fosse encontrado quando o script era executado de outro diretório, resultando em documentos sem tipo (todos `MastersThesis`), sem data e sem subjects. A solução foi usar `os.path.abspath(__file__)` para resolver o caminho relativo ao script.

### LLM respondendo com JSON truncado

Com `num_predict` baixo, o modelo cortava a resposta no meio do JSON. A função `extract_json()` implementa reparo de JSON truncado: conta `{` e `[` abertos e injeta os fechamentos faltantes.

### ollama com dois workers simultâneos retornando vazios

O ollama processa um request por vez. Com `workers=2`, o segundo request ficava na fila e às vezes retornava vazio ao dar timeout. A solução foi eliminar o ThreadPoolExecutor e processar sequencialmente (workers=1).

### GPU não sendo utilizada

O ollama rodava o modelo na CPU por padrão, causando 17 horas de processamento para 1.970 documentos. A solução foi adicionar `"num_gpu": 99` nas opções do request, forçando todas as camadas do modelo para a VRAM da RTX 4070 Super.

### Triplas carregadas em named graphs

O `fuseki_setup.py` original enviava os TTLs com `params={"graph": uri}`, colocando cada arquivo em um named graph separado. As queries SPARQL sem `GRAPH ?g { }` consultavam apenas o default graph (vazio). A solução foi remover o parâmetro `graph` do upload, enviando tudo para o default graph.

### Comparação de modelos com configuração hardcoded no relatório

O script `compare_models.py` gerava um relatório Markdown com `num_predict=700` e `TEXT_LIMIT=3000` escritos como strings fixas no template, enquanto o código real usava valores diferentes. O template foi corrigido para referenciar as variáveis reais `QUALITY_OPTIONS` e `TEXT_LIMIT`.

---

## 9. Como executar

### Pré-requisitos

```bash
# 1. Clone o repositório
git clone <url>
cd projeto-artigos-buscas

# 2. Verifique e instale o ambiente
python setup_env.py

# 3. Instale modelos LLM (se ainda não instalados)
ollama pull llama3.1:8b
ollama pull nomic-embed-text
```

### Execução completa (do zero)

```bash
python run_pipeline.py
```

> ⚠️ Tempo estimado: 20+ horas (coleta + GROBID + análise de discurso)

### Execução com dados já existentes

```bash
# Pula coleta e GROBID — só reconstrói o grafo e a análise
python run_pipeline.py --skip-collect --skip-grobid

# Retoma a partir do Fuseki (TTLs já existem)
python run_pipeline.py --from-step fase_3_fuseki

# Só regenera o relatório
python run_pipeline.py --only avaliacao_report
```

### Execução manual por fase

```bash
# Fase 1 — Coleta
cd fase_1
python collect_all_sets.py

# Fase 2 — Extração
cd ../fase_2
python grobid_setup.py
python process_pdfs.py
python quality_gate.py stage2
python tei_to_doco.py

# Fase 3 — Análise
cd ../fase_3
python fuseki_setup.py --reload
python discourse_analysis.py --model llama3.1:8b
python enrich_graph.py
python fix_titles.py --manifest ../fase_1/data/manifest.jsonl
python sparql_queries.py
python sparql_advanced.py

# Relatório
cd ../avaliacao
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

### Sistema de Recuperação de Informação

```bash
cd fase_3

# Constrói o índice (1x, ~20-30 min)
python ir_search.py --build

# Busca híbrida (BM25 + embeddings)
python ir_search.py --query "redes neurais para previsão"

# Só em seções de conclusão, só teses de doutorado
python ir_search.py --query "limitações de dados" --section conclusion --type thesis
```

---

## 10. Requisitos

### Software

| Software | Versão | Uso |
|---|---|---|
| Python | ≥ 3.10 | Toda a pipeline |
| Docker Desktop | Recente | GROBID e Fuseki |
| ollama | Recente | LLM local |

### Pacotes Python

```
requests==2.31.0
sickle==0.7.0        # OAI-PMH (fase 1)
beautifulsoup4==4.12.3
colorlog
rdflib==7.0.0
tqdm
tabulate==0.9.0
numpy                 # IR semântico
```

### Modelos e imagens

```bash
# Docker
docker pull secoresearch/fuseki
docker pull lfoppiano/grobid:0.8.1

# ollama
ollama pull llama3.1:8b          # ~4.7GB — análise de discurso
ollama pull nomic-embed-text      # ~274MB — embeddings para IR
```

### Hardware mínimo recomendado

| Componente | Mínimo | Usado no projeto |
|---|---|---|
| CPU | 6 cores | Ryzen 9 7900 (12 cores) |
| RAM | 16 GB | 16 GB |
| GPU VRAM | 8 GB (para llama3.1:8b) | RTX 4070 Super (12 GB) |
| Armazenamento | 50 GB livres | — |

> Sem GPU: o pipeline funciona, mas a análise de discurso levará ~17h em CPU (vs ~3-4h com GPU).

---

## Ontologia de discurso customizada

Namespace: `http://pantheon.ufrj.br/ontology/discourse#`

| Elemento | Tipo | Descrição |
|---|---|---|
| `discourse:ScientificClaim` | Classe | Afirmação factual extraída de seções de resultados/conclusão |
| `discourse:Contribution` | Classe | Contribuição específica declarada pelos autores |
| `discourse:Limitation` | Classe | Limitação explicitamente reconhecida no texto |
| `discourse:FutureWork` | Classe | Direção de pesquisa futura mencionada |
| `discourse:AnalyzedDocument` | Classe | Documento que passou pela análise LLM |
| `discourse:hasClaim` | Propriedade | Documento → ScientificClaim |
| `discourse:hasContribution` | Propriedade | Documento → Contribution |
| `discourse:hasLimitation` | Propriedade | Documento → Limitation |
| `discourse:hasFutureWork` | Propriedade | Documento → FutureWork |
| `discourse:inferredKeyword` | Propriedade | Documento → Literal (keyword técnica) |
| `discourse:inSection` | Propriedade | Claim/Limitation → Seção de origem (DEO) |

---

## Exemplo de query SPARQL

Dissertações de mestrado sobre ML a partir de 2018, com seus claims mais específicos:

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
  ?doc dcterms:subject ?subj .
  FILTER(CONTAINS(LCASE(?subj), "computacao"))
  ?doc discourse:hasClaim ?c .
  ?c c4o:hasContent ?claim .
  FILTER(CONTAINS(LCASE(?claim), "aprendizado") ||
         CONTAINS(LCASE(?claim), "machine learning"))
  FILTER(STRLEN(STR(?titulo)) > 20)
}
ORDER BY DESC(?ano)
LIMIT 10
```

---

*Projeto desenvolvido para a disciplina Busca e Mineração de Texto — PESC/COPPE/UFRJ*
