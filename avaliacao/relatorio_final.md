# Relatório Final — Grafo de Conhecimento de Discurso Científico

**Projeto:** Construção de um Grafo de Conhecimento de Discurso Científico  
**Repositório:** Pantheon/UFRJ  
**Gerado em:** 13/04/2026 02:48

---

## 1. Visão Geral do Corpus

| Métrica | Valor |
|---|---|
| Documentos indexados no grafo | 1,841 |
| Teses de doutorado | 455 |
| Dissertações de mestrado | 1,386 |
| Seções estruturadas (DoCO) | 68,327 |
| Parágrafos | 294,819 |
| Claims extraídos pelo LLM | 0 |
| Limitações extraídas | 0 |
| Trabalhos futuros extraídos | 0 |

### Distribuição temporal

| Ano | Documentos |
|---|---|
| 2017 | 192 |
| 2018 | 295 |
| 2019 | 340 |
| 2020 | 392 |
| 2021 | 195 |
| 2022 | 28 |
| 2023 | 73 |
| 2024 | 69 |
| 2025 | 220 |

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
| Documentos validados | 1,841 |
| Sem nenhum problema (conformidade total) | 1,725 (93.7%) |
| Com violações críticas | 1 (0.1%) |
| Com avisos (sem violações críticas) | 115 |

**Avisos mais frequentes** (limitações esperadas do processo de extração):
- `Abstract vazio ou muito curto (menos de 30 caracteres).` — 151x

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
| Documentos com títulos suspeitos (Lista de Figuras, Agradecimentos, etc.) | ✗ 7 |


**Contagens do corpus** (informativas):

| Métrica | Valor |
|---|---|
| Seções sem documento pai (nenhum nível da hierarquia) | 502 |
| Lista dos títulos suspeitos encontrados | 1 |
| Total de documentos no grafo | 1,841 |
| Total de seções estruturadas | 68,829 |
| Total de parágrafos | 294,819 |
| Total de claims extraídos pelo LLM | 30,320 |
| Total de limitações extraídas | 5,118 |
| Seções com tipo retórico DEO atribuído | 10,693 |
| Documentos sem nenhuma seção extraída pelo GROBID | 0 |
| Documentos com pelo menos 1 elemento de discurso (claim/limitação/futuro) | 1,555 |


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

Universo de análise: 1845 documentos totais | 1569 analisados com sucesso | 275 sem seções-alvo | 1 falhas.

### H2 — Qualidade da extração

> *A proporção de itens extraídos classificados como genéricos será inferior a 20%
> do total, e a estrutura formal do grafo satisfará as restrições das ontologias.*

| Pergunta | Critério | Valor medido | |
|---|---|---|---|
| Qual proporção das afirmações extraídas é genérica (sem conteúdo específico)? | ≤ 35% | 2.0% | ✓ |
| Qual proporção das seções foi classificada com tipo retórico correto? | ≥ 60% | 83.3% | ✓ |
| Quantos dos 4 campos de discurso são preenchidos por documento (em média)? | ≥ 2,0 | 3.19 de 4 (1569 docs) | ✓ |
| Qual proporção dos documentos está em conformidade formal (SHACL)? | ≥ 80% | 93.7% | ✓ |
| Qual a taxa de violações críticas no grafo (SHACL)? | ≤ 5% | 0.1% | ✓ |

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
| 2017 | 0 | 22 |
| 2018 | 0 | 8 |
| 2019 | 6 | 7 |
| 2020 | 11 | 2 |
| 2021 | 5 | 4 |
| 2022 | 0 | 3 |
| 2023 | 3 | 0 |
| 2024 | 3 | 1 |
| 2025 | 20 | 4 |

**Pergunta 2:** Há diferença de densidade de afirmações entre teses de doutorado e dissertações de mestrado?

Critério: teses de doutorado com densidade observavelmente maior.

| Tipo | Documentos | Claims totais | Claims por documento |
|---|---|---|---|
| Doutorado | 455 | 5,996 | 13.18 |
| Mestrado  | 1,386 | 9,164 | 6.61 |

**Pergunta 3:** As limitações declaradas diferem sistematicamente entre áreas do corpus?

Critério: ao menos 2 áreas com perfis de limitação distintos identificáveis.

| Área | Limitações declaradas |
|---|---|
| ENGENHARIAS::ENGENHARIA CIVIL | 283 |
| ENGENHARIAS | 262 |
| ENGENHARIAS::ENGENHARIA ELETRICA | 216 |
| ENGENHARIAS::ENGENHARIA QUIMICA | 157 |
| ENGENHARIAS::ENGENHARIA DE MATERIAIS E METALURGICA | 121 |

---

## 4. Comparação de modelos LLM

A escolha do modelo de extração foi validada experimentalmente em uma amostra
do corpus. Os valores abaixo refletem o modelo adotado para o processamento
completo.

| Dimensão | Métrica | Valor |
|---|---|---|
| Confiabilidade | Taxa de saída genérica | 2.0% |
| Qualidade | Tipo retórico correto | 83.3% |
| Completude | Campos preenchidos por documento | 3.19/4 |

---

_Relatório gerado automaticamente por `generate_report.py` em 13/04/2026 02:48_
