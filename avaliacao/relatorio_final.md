# Relatório Final — Grafo de Conhecimento de Discurso Científico

**Projeto:** Construção de um Grafo de Conhecimento de Discurso Científico  
**Repositório:** Pantheon/UFRJ  
**Gerado em:** 19/05/2026 02:18

---

## 1. Visão Geral do Corpus

| Métrica | Valor |
|---|---|
| Documentos indexados no grafo | 2,316 |
| Teses de doutorado | 671 |
| Dissertações de mestrado | 1,645 |
| Seções estruturadas (DoCO) | 93,545 |
| Parágrafos | 405,854 |
| Claims extraídos pelo LLM | 0 |
| Limitações extraídas | 0 |
| Trabalhos futuros extraídos | 0 |

### Distribuição temporal

| Ano | Documentos |
|---|---|
| 2017 | 232 |
| 2018 | 318 |
| 2019 | 417 |
| 2020 | 514 |
| 2021 | 297 |
| 2022 | 30 |
| 2023 | 101 |
| 2024 | 91 |
| 2025 | 263 |

> As datas refletem o campo `datestamp` de indexação no Pantheon, não necessariamente
> o ano de defesa. O campo pode apresentar anos atípicos como 2025/2026 para
> documentos indexados recentemente.

---

## 2. Qualidade Estrutural do Grafo

O projeto utiliza duas abordagens complementares de validação. Cada uma examina
um aspecto diferente da qualidade: uma verifica se o grafo respeita as
**regras formais** das ontologias adotadas; a outra verifica se as
**relações semânticas** estão consistentes.

### 2.1 Validação SHACL — conformidade formal

**O que o SHACL verifica:** cada nó do grafo é testado contra um conjunto de
shapes (formas) que descrevem o que é obrigatório, o que é permitido e o
que é proibido segundo as ontologias DoCO, DEO, FaBiO e a ontologia
customizada de discurso. Um nó pode falhar de duas formas distintas:

- **Violação** — quebra uma restrição crítica (ex: documento sem título).
  Indica problema real no dado.
- **Aviso** — quebra uma restrição informativa (ex: abstract curto).
  Pode ser limitação esperada da ferramenta de extração.

**Como interpretar a taxa de conformidade:** um documento é contado como
"em conformidade" apenas se não tem nenhuma violação **nem** aviso. Por isso,
a taxa de conformidade total costuma ser baixa mesmo quando o grafo está
estruturalmente correto — especialmente em corpora extraídos de PDFs históricos,
onde avisos de seções vazias são esperados do GROBID.

**O indicador mais relevante é a taxa de violações críticas.**

| Métrica SHACL | Valor |
|---|---|
| Documentos validados | 2,316 |
| Sem nenhum problema (conformidade total) | 2,156 (93.1%) |
| Com violações críticas | 1 (0.0%) |
| Com avisos (sem violações críticas) | 159 |

**Avisos mais frequentes** (limitações esperadas do processo de extração):
- `Abstract vazio ou muito curto (menos de 30 caracteres).` — 207x

### 2.2 Validação de integridade semântica

**O que as queries de integridade verificam:** enquanto o SHACL testa a
conformidade de cada nó individualmente, as queries de integridade testam
a **consistência das relações** no grafo como um todo — se existem nós
sem conexão com outros, duplicatas, referências quebradas.

**Verificações críticas** (valor esperado: zero):

| Verificação | Resultado |
|---|---|
| Documentos sem dcterms:title | ✓ zero |
| Documentos sem tipo específico (não são nem Tese nem Dissertação) | ✓ zero |
| Parágrafos sem c4o:hasContent | ✓ zero |
| Claims LLM sem c4o:hasContent | ✓ zero |
| Claims não ligados a nenhum documento | ✓ zero |
| Handles duplicados (mesmo documento indexado mais de uma vez) | ✓ zero |
| Documentos com títulos suspeitos (Lista de Figuras, Agradecimentos, etc.) | ✗ 8 |


**Contagens do corpus** (informativas):

| Métrica | Valor |
|---|---|
| Seções sem documento pai (nenhum nível da hierarquia) | 710 |
| Lista dos títulos suspeitos encontrados | 1 |
| Total de documentos no grafo | 2,316 |
| Total de seções estruturadas | 94,255 |
| Total de parágrafos | 405,854 |
| Total de claims extraídos pelo LLM | 41,620 |
| Total de limitações extraídas | 6,962 |
| Seções com tipo retórico DEO atribuído | 14,601 |
| Documentos sem nenhuma seção extraída pelo GROBID | 0 |
| Documentos com pelo menos 1 elemento de discurso (claim/limitação/futuro) | 1,998 |


### 2.3 Como as duas abordagens se complementam

O SHACL e a validação de integridade respondem perguntas diferentes e se
complementam mutuamente:

| Aspecto | SHACL | Integridade semântica |
|---|---|---|
| O que testa | Forma de cada nó | Relações entre nós |
| Padrão | W3C SHACL 1.0 | SPARQL 1.1 |
| Detecta | Metadados ausentes, tipos incorretos | Órfãos, duplicatas, relações quebradas |
| Limitação | Não testa consistência entre grafos | Não testa conformidade com ontologia |

---

## 3. Plano de Avaliação — Hipóteses e Critérios

Os critérios abaixo foram definidos na proposta do projeto considerando
as características de modelos de linguagem locais sem ajuste fino.
Os valores medidos são apresentados para cada critério — a interpretação
final cabe ao leitor.

### H1 — Viabilidade de extração

> *Um modelo de linguagem de pequeno porte, executado localmente sem ajuste fino,
> conseguirá extrair elementos de discurso científico de seções de conclusão e
> resultados de teses escritas em português.*

| Pergunta | Critério | Valor medido | |
|---|---|---|---|
| Qual proporção dos documentos elegíveis foi processada com sucesso? | ≥ 50% | 99.9% | ✓ |
| Qual a taxa de falhas do modelo (saída inválida, timeout)? | ≤ 10% | 0.1% | ✓ |
| Qual proporção dos documentos processados tem ao menos 1 afirmação? | ≥ 70% | 98.9% | ✓ |

Universo de análise: 7641 documentos totais | 3926 analisados com sucesso | 3712 sem seções-alvo | 3 falhas.

### H2 — Qualidade da extração

> *A proporção de itens extraídos classificados como genéricos será inferior a 20%
> do total, e a estrutura formal do grafo satisfará as restrições das ontologias.*

| Pergunta | Critério | Valor medido | |
|---|---|---|---|
| Qual proporção das afirmações extraídas é genérica (sem conteúdo específico)? | ≤ 35% | 2.0% | ✓ |
| Qual proporção das seções foi classificada com tipo retórico correto? | ≥ 60% | 96.7% | ✓ |
| Quantos dos 4 campos de discurso são preenchidos por documento (em média)? | ≥ 2,0 | 3.21 de 4 (2016 docs) | ✓ |
| Qual proporção dos documentos está em conformidade formal (SHACL)? | ≥ 80% | 93.1% | ✓ |
| Qual a taxa de violações críticas no grafo (SHACL)? | ≤ 5% | 0.0% | ✓ |

> **Nota sobre conformidade SHACL:** a taxa de conformidade total reflete
> documentos sem nenhum aviso ou violação. Avisos de seções sem parágrafo são
> esperados do GROBID em PDFs históricos e não indicam erro de dados.
> O critério de 5% de violações críticas é o indicador central desta hipótese.

### H3 — Valor analítico do grafo

> *As consultas sobre o grafo enriquecido revelarão padrões não triviais no corpus.*

**Pergunta 1:** É possível identificar variação temporal no uso de técnicas metodológicas via consulta SPARQL?

Critério: variação observável ao longo do período coberto.

| Ano | Machine Learning | Elementos Finitos |
|---|---|---|
| 2017 | 0 | 27 |
| 2018 | 0 | 11 |
| 2019 | 6 | 7 |
| 2020 | 14 | 2 |
| 2021 | 9 | 7 |
| 2022 | 0 | 3 |
| 2023 | 5 | 3 |
| 2024 | 3 | 1 |
| 2025 | 22 | 6 |

**Pergunta 2:** Há diferença de densidade de afirmações entre teses de doutorado e dissertações de mestrado?

Critério: teses de doutorado com densidade observavelmente maior.

| Tipo | Documentos | Claims totais | Claims por documento |
|---|---|---|---|
| Doutorado | 671 | 9,505 | 14.17 |
| Mestrado  | 1,645 | 11,305 | 6.87 |

**Pergunta 3:** As limitações declaradas diferem sistematicamente entre áreas do corpus?

Critério: ao menos 2 áreas com perfis de limitação distintos identificáveis.

| Área | Limitações declaradas |
|---|---|
| ENGENHARIAS | 419 |
| ENGENHARIAS::ENGENHARIA CIVIL | 306 |
| ENGENHARIAS::ENGENHARIA QUIMICA | 269 |
| ENGENHARIAS::ENGENHARIA ELETRICA | 264 |
| ENGENHARIAS::ENGENHARIA DE PRODUCAO | 163 |

---

## 4. Comparação de modelos LLM

A escolha do modelo de extração foi validada experimentalmente em uma amostra
do corpus. Os valores abaixo refletem o modelo adotado para o processamento
completo.

| Dimensão | Métrica | Valor |
|---|---|---|
| Confiabilidade | Taxa de saída genérica | 2.0% |
| Qualidade | Tipo retórico correto | 96.7% |
| Completude | Campos preenchidos por documento | 3.21/4 |

---

_Relatório gerado automaticamente por `generate_report.py` em 19/05/2026 02:18_
