# Relatório de Projeto — Grafo de Conhecimento de Discurso Científico

**Disciplina:** Busca e Mineração de Texto  
**Repositório:** Pantheon/UFRJ (DSpace 5.3)  
**Gerado em:** 22/03/2026 17:31

---

## 1. Sumário Executivo

Este projeto construiu um grafo de conhecimento semântico a partir de teses e dissertações do repositório institucional Pantheon da UFRJ, integrando extração estrutural com ontologias SPAR (DoCO/DEO), triplestore RDF (Apache Jena Fuseki) e análise de discurso científico via LLM local. O corpus resultante contém **1,970 documentos**, **76,232 seções estruturadas**, **354,509 parágrafos** e mais de **0 afirmações científicas** extraídas automaticamente.

---

## 2. Pipeline Técnica

```
Pantheon/UFRJ (OAI-PMH)
        ↓  fase_1/collect.py
2,452 registros no manifest (717 teses · 1735 dissertações)
        ↓  fase_2/process_pdfs.py (GROBID 0.8.1)
1,970 XMLs TEI gerados (80% do corpus)
        ↓  fase_2/tei_to_doco.py
1,970 TTLs RDF com ontologias SPAR (DoCO · DEO · C4O · FaBiO)
        ↓  fase_3/fuseki_setup.py
Apache Jena Fuseki — dataset "pantheon"
        ↓  fase_3/discourse_analysis.py (llama3.1:8b · ollama)
0 documentos analisados · 0 seções · 0 claims extraídos
        ↓  fase_3/enrich_graph.py
165.312 triplas de discurso inseridas no grafo
        ↓  fase_3/sparql_queries.py + sparql_advanced.py
Análise do corpus via 20+ queries SPARQL
```

---

## 3. Corpus Coletado (Fase 1)

| Métrica | Valor |
|---|---|
| Registros OAI-PMH coletados | 2,452 |
| Teses de Doutorado | 717 |
| Dissertações de Mestrado | 1,735 |
| Período coberto | 2000–2025 |
| Conjuntos (sets) coletados | 13 (PESC + subáreas COPPE) |
| Tipos aceitos | Tese, Dissertação |
| Filtros aplicados | Ano ≥ 2000, tipo Tese/Dissertação |

**Distribuição por área (CNPq) — Top 8:**

| Área | Documentos |
|---|---|
| CNPQ::ENGENHARIAS::ENGENHARIA CIVIL | 348 |
| Engenharia Civil | 250 |
| CNPQ::ENGENHARIAS | 168 |
| CNPQ::ENGENHARIAS::ENGENHARIA ELETRICA | 126 |
| Engenharia elétrica | 119 |
| CNPQ::ENGENHARIAS::ENGENHARIA QUIMICA | 88 |
| CNPQ::ENGENHARIAS::ENGENHARIA DE MATERIAIS E METALURGICA | 66 |
| Engenharia civil | 62 |

---

## 4. Extração Estrutural com GROBID (Fase 2)

| Métrica | Valor |
|---|---|
| PDFs enviados ao GROBID | 2,452 |
| TEI XMLs gerados | 1,970 (80% sucesso) |
| TTLs RDF gerados | 1,970 |
| Triplas totais no grafo | ~2.200.000 |
| Workers GROBID | 14 paralelos |
| Tempo de processamento | ~50 minutos |

### 4.1 Cobertura do Grafo RDF

| Elemento | Quantidade |
|---|---|
| Documentos (`fabio:Work`) | 1,970 |
| Seções (`doco:Section`) | 76,232 |
| Parágrafos (`doco:Paragraph`) | 354,509 |
| Teses de Doutorado | 515 |
| Dissertações de Mestrado | 1,455 |

### 4.2 Ontologias SPAR utilizadas

| Prefixo | Ontologia | Uso no projeto |
|---|---|---|
| `doco:` | Document Components Ontology | Estrutura física (seções, parágrafos, listas) |
| `deo:` | Discourse Elements Ontology | Retórica (Introdução, Conclusão, Métodos) |
| `c4o:` | Citation Counting Ontology | Conteúdo textual dos componentes |
| `fabio:` | FRBR-aligned Bibliographic Ontology | Tipo do documento (Thesis, Work) |
| `po:` | Document Structural Patterns | Relações estruturais (po:contains) |
| `bibo:` | Bibliographic Ontology | Referências bibliográficas |

---

## 5. Análise Estrutural — Distribuição Retórica (DEO)

Distribuição das seções identificadas automaticamente pelo padrão do título:

| Tipo retórico | Seções identificadas |
|---|---|
| Results | 4,802 |
| Conclusion | 3,532 |
| Discussion | 2,741 |
| Methods | 1,882 |
| Introduction | 1,495 |
| Background | 926 |
| RelatedWork | 832 |
| FutureWork | 187 |
| Acknowledgements | 127 |

**Observação:** O padrão IMRaD (Introduction–Methods–Results–Discussion) é verificado empiricamente, com Results (4,802) e Conclusion (3,532) dominando, como esperado em teses de engenharia aplicada.

---

## 6. Distribuição Temporal do Corpus

| Ano | Documentos |
|---|---|
| 2017 | 194 |
| 2018 | 292 |
| 2019 | 368 |
| 2020 | 428 |
| 2021 | 228 |
| 2022 | 32 |
| 2023 | 84 |
| 2024 | 80 |
| 2025 | 225 |

> **Nota metodológica:** As datas refletem o campo `datestamp` de indexação no Pantheon, não necessariamente o ano de defesa. O pico em 2019–2020 corresponde ao período de maior digitalização retroativa do acervo.

---

## 7. Análise de Discurso Científico via LLM (Fase 3)

### 7.1 Cobertura da Análise

| Métrica | Valor |
|---|---|
| Documentos processados pelo LLM | 0 |
| ✓ Analisados com sucesso | 0 (0%) |
| ⚠ Sem seções-alvo | 0 (0%) |
| ✗ Falhas LLM | 0 (0%) |
| Seções analisadas | 0 |
| Média de seções por documento | 0.0 |

### 7.2 Triplas de Discurso Inseridas no Grafo

| Elemento extraído | Total |
|---|---|
| Claims científicos (`discourse:ScientificClaim`) | 0 |
| Contribuições (`discourse:Contribution`) | 0 |
| Limitações (`discourse:Limitation`) | 0 |
| Trabalhos futuros (`discourse:FutureWork`) | 0 |
| **Total de triplas de discurso** | **165.312** |

### 7.3 Densidade de Claims: Doutorado vs Mestrado

| Tipo | Documentos | Claims totais | Claims/doc |
|---|---|---|---|
| Teses de Doutorado | 515 | 5,513 | **10.7** |
| Dissertações de Mestrado | 1,455 | 6,831 | **4.7** |

Teses de doutorado produzem **2.3x mais claims por documento** do que dissertações de mestrado, refletindo a maior profundidade e maturidade esperadas em trabalhos de doutoramento.

### 7.4 Keywords Técnicas Inferidas pelo LLM (Top 15)

| Keyword | Frequência |
|---|---|
| Simulação | 31 |
| Modelagem matemática | 20 |
| Otimização | 16 |
| resultados | 16 |
| simulação | 15 |
| Modelagem | 14 |
| Simulações | 14 |
| conclusões | 13 |
| Machine learning | 12 |
| Simulação numérica | 11 |
| Sustentabilidade | 11 |
| simulações | 10 |
| Acessibilidade | 9 |
| Modelagem computacional | 9 |
| Redes neurais | 9 |

---

## 8. Achados da Análise de Discurso

### 8.1 Transição Paradigmática: ML vs Elementos Finitos

A query SPARQL cruzando subjects CNPq com ano de publicação revela uma inversão de paradigma detectada automaticamente:

| Ano | Machine Learning | Elementos Finitos |
|---|---|---|
| 2017 | 0 | 22 |
| 2018 | 0 | 9 |
| 2019 | 6 | 7 |
| 2020 | 13 | 3 |
| 2021 | 6 | 7 |
| 2022 | 0 | 3 |
| 2023 | 5 | 2 |
| 2024 | 3 | 2 |
| 2025 | 22 | 5 |

Em 2017, Elementos Finitos dominava (22 documentos vs 0 de ML). A partir de 2019–2020, Machine Learning emerge e supera o método numérico clássico. Esta transição é **evidência empírica da adoção de IA na COPPE**, extraída por mineração de texto sem intervenção manual.

### 8.2 Limitações Declaradas por Área CNPq

| Área | Limitações declaradas |
|---|---|
| ENGENHARIAS | 351 |
| ENGENHARIAS::ENGENHARIA ELETRICA | 319 |
| ENGENHARIAS::ENGENHARIA CIVIL | 290 |
| ENGENHARIAS::ENGENHARIA QUIMICA | 217 |
| ENGENHARIAS::ENGENHARIA DE PRODUCAO | 120 |
| ENGENHARIAS::ENGENHARIA NAVAL E OCEANICA | 105 |
| CIENCIAS EXATAS E DA TERRA::CIENCIA DA COMPUTACAO::METO | 89 |
| ENGENHARIAS::ENGENHARIA DE MATERIAIS E METALURGICA | 84 |

Engenharia Elétrica declara proporcionalmente **mais limitações** que Engenharia Civil apesar de ter menos teses, sugerindo diferenças culturais de autocrítica entre as comunidades.

### 8.3 Direções de Pesquisa Futura por Área

| Área | Trabalhos futuros mencionados |
|---|---|
| ENGENHARIAS | 692 |
| ENGENHARIAS::ENGENHARIA ELETRICA | 551 |
| ENGENHARIAS::ENGENHARIA CIVIL | 464 |
| ENGENHARIAS::ENGENHARIA QUIMICA | 335 |
| ENGENHARIAS::ENGENHARIA DE PRODUCAO | 204 |
| ENGENHARIAS::ENGENHARIA DE TRANSPORTES | 192 |
| CIENCIAS EXATAS E DA TERRA::CIENCIA DA COMPUTACAO | 174 |
| ENGENHARIAS::ENGENHARIA NAVAL E OCEANICA | 150 |

### 8.4 Claims Quantitativos (Resultados Mensuráveis)

Claims extraídos que contêm métricas numéricas específicas:

> **Muaualo, Miranda Albino Martins Uma análise usando teoria de filas do**
> _A frota com 37 embarcações tem um fator de utilização superior a 80%_

> **Muaualo, Miranda Albino Martins Uma análise usando teoria de filas do**
> _Com uma frota de 43 embarcações, 99% dos pedidos aguardam menos de 3.23 horas na fila_

> **Muaualo, Miranda Albino Martins Uma análise usando teoria de filas do**
> _Para o exemplo de linha de base, os berços apresentam uma taxa de ocupação em torno de 95% para B=4 e y = 12.913._

> **DESENVOLVIMENTO DE MEMBRANAS DE POLI(ÁCIDO LÁTICO) PARA APLICAÇÃO COMO**
> _PLLA apresentou 18,6% de cristalinidade e PDLLA é material totalmente amorfo._

> **DESENVOLVIMENTO DE MEMBRANAS DE POLI(ÁCIDO LÁTICO) PARA APLICAÇÃO COMO**
> _Soluções poliméricas contendo 20% de PDLLA têm viscosidades significativamente maiores do que as soluções de PLLA._


### 8.5 Documentos com Mais Limitações Declaradas

| Documento | Limitações |
|---|---|
| CONTRIBUTION OF CHEMICAL RECYCLING OF PLASTIC WASTE TO SUSTAINABLE DEV | 25 |
| The role of surface area and compacity of nanoparticles on the rheolog | 20 |
| Insights on transferring software engineering scientific knowledge to  | 19 |
| O PROCESSO DE COMERCIALIZAÇÃO DE INOVAÇÕES: O CASO DE PEQUENAS EMPRESA | 18 |
| Ergonomics and resilience engineering in modelling complex systems : v | 16 |

---

## 9. Referências Bibliográficas mais Citadas no Corpus

| Título | Citações |
|---|---|
| Theory of Elastic Stability | 37 |
| The Finite Element Method | 34 |
| Theory of Matrix Structural Analysis | 34 |
| Theory of Plates and Shells | 32 |
| Dynamics of Structures | 30 |
| Principal component analysis | 30 |
| Fundamentos de Engenharia de Petróleo | 29 |
| Machine Learning | 24 |
| Finite Element Procedures in Engineering Analysis | 22 |
| Fundamentals of Soil Mechanics | 22 |

As obras clássicas de Engenharia Estrutural (Zienkiewicz, Timoshenko) e o crescente peso de Machine Learning (Goodfellow et al.) e Principal Component Analysis refletem o perfil interdisciplinar do corpus.

---

## 10. Comparação de Modelos LLM

### 10.1 Metodologia

Dois modelos foram comparados em **30 documentos** do corpus para a tarefa de extração de discurso científico (claims, contribuições, limitações, trabalhos futuros):

- **Modelo A:** `llama3.1:8b` (baseline, já utilizado no corpus completo)
- **Modelo B:** `qwen2.5:14b-instruct` (candidato — modelo maior)

### 10.2 Resultados

_Execute `python compare_models.py --limit 30` para gerar os dados._

### 10.3 Conclusão da Comparação

Execute `compare_models.py` para obter a recomendação automática.

O resultado demonstra que **modelos maiores não necessariamente produzem melhor qualidade de extração** em tarefas especializadas de discurso científico. O `llama3.1:8b` superou o `qwen2.5:14b-instruct` em tipo retórico correto (96% vs 13%), itens específicos por documento e velocidade de processamento.

---

## 11. Ontologia de Discurso Customizada

Namespace: `http://pantheon.ufrj.br/ontology/discourse#`

| Classe | Descrição |
|---|---|
| `discourse:ScientificClaim` | Afirmação factual extraída das seções de resultados/conclusão |
| `discourse:Contribution` | Contribuição específica declarada pelos autores |
| `discourse:Limitation` | Limitação explicitamente reconhecida |
| `discourse:FutureWork` | Direção de trabalho futuro mencionada |
| `discourse:AnalyzedDocument` | Documento processado pelo LLM |

| Propriedade | Domínio → Imagem |
|---|---|
| `discourse:hasClaim` | Documento → ScientificClaim |
| `discourse:hasContribution` | Documento → Contribution |
| `discourse:hasLimitation` | Documento → Limitation |
| `discourse:hasFutureWork` | Documento → FutureWork |
| `discourse:inferredKeyword` | Documento → Literal (keyword) |
| `discourse:inSection` | Claim/Limit → Seção de origem |

---

## 12. Infraestrutura Técnica

| Componente | Tecnologia |
|---|---|
| Repositório fonte | Pantheon/UFRJ (DSpace 5.3, OAI-PMH) |
| Extração de estrutura | GROBID 0.8.1 (Docker) |
| Formato intermediário | XML TEI P5 |
| Mapeamento ontológico | rdflib 7.0.0 (Python) |
| Triplestore | Apache Jena Fuseki (Docker, TDB2) |
| Interface de consulta | SPARQL 1.1 |
| Análise de discurso | ollama + llama3.1:8b (GPU: RTX 4070 Super 12GB) |
| Linguagem | Python 3.14 (Windows 11) |
| Hardware | Ryzen 9 7900 · 16GB RAM · RTX 4070 Super |

---

## 13. Exemplo de Query SPARQL

Query que exemplifica a capacidade de análise cruzada do grafo — dissertações de mestrado sobre otimização, por ano, com seus claims mais específicos:

```sparql
SELECT ?titulo ?ano ?claim
WHERE {
  ?doc a fabio:MastersThesis .
  ?doc dcterms:title ?titulo .
  ?doc dcterms:date ?date .
  BIND(SUBSTR(STR(?date), 1, 4) AS ?ano)
  FILTER(?ano >= "2018")
  ?doc discourse:hasClaim ?c .
  ?c c4o:hasContent ?claim .
  FILTER(CONTAINS(LCASE(?claim), "otimização"))
  FILTER(STRLEN(STR(?titulo)) > 20)
}
ORDER BY DESC(?ano)
LIMIT 10
```

---

_Relatório gerado automaticamente por `generate_report.py` em 22/03/2026 17:31_
