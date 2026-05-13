# Análise Estatística do Corpus — Grafo de Conhecimento de Discurso Científico

**Projeto:** Busca e Mineração de Texto — PESC/COPPE/UFRJ  
**Gerado em:** 13/05/2026 17:19

---

## 1. Corpus (metadados OAI-PMH)

| Métrica | Valor |
|---|---|
| Total de registros no manifest | 2,452 |
| Teses de Doutorado | 717 |
| Dissertações de Mestrado | 1735 |
| Documentos em português | 2096 |
| Documentos em inglês | 340 |
| Comprimento médio do título | 94.23 chars (DP=31.338) |
| Subjects CNPq por documento (mediana) | 4.0 |

![Distribuição temporal](charts/01_distribuicao_temporal.png)
![Tipos e idiomas](charts/02_tipos_idiomas.png)

---

## 2. Estrutura do Grafo (DoCO/DEO)

| Métrica | Média | Mediana | DP | P95 |
|---|---|---|---|---|
| Seções DoCO por documento | 37.114 | 32.0 | 28.499 | 86.0 |
| Parágrafos por documento | 160.141 | 135.0 | 116.873 | 374.0 |
| Referências por documento | 66.655 | 53.0 | 56.32 | 166.2 |

### Cobertura dos tipos retóricos DEO

| Tipo DEO | Documentos | % do corpus |
|---|---|---|
| `deo:Results` | 1,083 | 58.8% |
| `deo:Conclusion` | 998 | 54.2% |
| `deo:Introduction` | 928 | 50.4% |
| `deo:Methods` | 836 | 45.4% |
| `deo:Discussion` | 771 | 41.9% |
| `deo:RelatedWork` | 610 | 33.1% |
| `deo:Background` | 309 | 16.8% |
| `deo:FutureWork` | 172 | 9.3% |
| `deo:Acknowledgements` | 119 | 6.5% |

![Distribuição seções e parágrafos](charts/03_dist_secoes_paragrafos.png)
![Cobertura DEO](charts/04_cobertura_deo.png)
![Distribuição de referências](charts/05_dist_referencias.png)

---

## 3. Discurso Científico (extração LLM)

| Elemento | Média/doc | Mediana | DP | P95 |
|---|---|---|---|---|
| Claims | 9.663 | 7.0 | 8.22 | 25.0 |
| Limitações | 1.631 | 1.0 | 2.21 | 5.0 |
| Trabalhos futuros | 3.218 | 2.0 | 3.098 | 9.0 |

### Concentração da extração

**Coeficiente de Gini (claims):** `0.4073`

> O coeficiente de Gini mede concentração: 0 = distribuição uniforme, 1 = máxima concentração.
> Valor `0.4073` indica concentração moderada — distribuição heterogênea mas não extrema.

### Correlação tamanho de seção × claims extraídos

**Spearman ρ = `0.598`** — correlação positiva significativa: seções maiores produzem sistematicamente mais claims.

### Distribuição de keywords — Lei de Zipf

**Expoente α = `0.32` (R² = `0.751`)**

> A lei de Zipf clássica (vocabulário de língua natural) tem α ≈ 1. Expoente menor
> indica cauda mais longa — termos técnicos distribuem-se de forma menos concentrada
> que vocabulário geral, o que é esperado em um corpus científico especializado.

### Top 10 keywords inferidas pelo LLM

| # | Keyword | Frequência |
|---|---|---|
| 1 | método dos elementos finitos | 265 |
| 2 | rede lstm | 58 |
| 3 | análise tga | 54 |
| 4 | rede neural | 31 |
| 5 | modelo matemático | 20 |
| 6 | otimização | 18 |
| 7 | algoritmo | 17 |
| 8 | aprendizado de máquina | 17 |
| 9 | modelagem | 16 |
| 10 | pvdf | 15 |

![Distribuição claims](charts/06_dist_claims_boxplot.png)
![Tipos retóricos LLM](charts/07_tipos_retoricos_llm.png)
![Zipf keywords](charts/08_zipf_keywords.png)
![Correlação seção × claims](charts/09_correlacao_secao_claims.png)

---

## 4. Análise por Área CNPq

![Claims por área](charts/10_claims_por_area.png)

---

## 5. Evolução Temporal

| Ano | Documentos | Claims/doc | Limitações/doc |
|---|---|---|---|
| 2017 | 192 | 2.82 | 0.4 |
| 2018 | 295 | 2.78 | 0.42 |
| 2019 | 340 | 10.2 | 1.65 |
| 2020 | 392 | 10.1 | 1.74 |
| 2021 | 195 | 8.95 | 1.51 |
| 2022 | 28 | 4.57 | 0.96 |
| 2023 | 73 | 10.4 | 1.75 |
| 2024 | 69 | 12.26 | 2.33 |
| 2025 | 220 | 11.38 | 2.02 |

![Evolução temporal](charts/11_evolucao_temporal.png)

---

## 6. Análise de Rede do Grafo RDF

A análise de rede examina o grafo RDF como uma estrutura de dados relacional,
revelando a topologia das conexões entre documentos, seções, parágrafos e elementos de discurso.

| Métrica | Valor |
|---|---|
| Nós no subgrafo analisado | 44,445 |
| Arestas (relações) | 6,297 |
| Componentes conectados | 38148 |
| Maior componente | 0.0% dos nós |
| In-degree médio | 0.142 |
| In-degree máximo | 1.0 |
| Out-degree médio | 0.142 |

### Distribuição de tipos de nós

| Tipo | Nós |
|---|---|
| Parágrafo | 27,876 |
| Outro | 10,682 |
| Seção | 5,737 |
| Referências | 150 |

A distribuição de grau em escala logarítmica (gráfico abaixo) revela se o grafo
segue uma lei de potência (comum em grafos de conhecimento reais), onde poucos nós
concentram a maior parte das conexões.

![Distribuição de grau](charts/12_degree_distribution.png)
![Tipos de nós no grafo](charts/13_tipos_nos_grafo.png)

---

## 7. Estrutura Bruta dos Documentos (TEI)

![Tamanho dos documentos](charts/14_tei_body_size.png)

---

*Relatório gerado automaticamente por `corpus_statistics.py` — 13/05/2026 17:19*
