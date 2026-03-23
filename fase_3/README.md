# Fase 3 — Fuseki + SPARQL + Análise de Discurso

## Visão geral

```
data/rdf/*.ttl           data/discourse/*.json
      │                         │
      ▼                         ▼
 [fuseki_setup.py]      [discourse_analysis.py]
      │                         │
      ▼                         ▼
 Fuseki triplestore      [enrich_graph.py]
      │                         │
      └──────────┬──────────────┘
                 ▼
         [sparql_queries.py]
                 │
                 ▼
        Análise do corpus
```

## Setup

```bash
pip install -r requirements.txt
```

## Passo a passo

### 3A — Subir o Fuseki e carregar o corpus

```bash
python fuseki_setup.py
```

- Sobe o Apache Jena Fuseki via Docker
- Cria o dataset `pantheon`
- Carrega todos os 1.970 TTLs (~2,2M triplas)
- Acesso web: http://localhost:3030 (admin / pantheon123)

Para recarregar após atualizar os TTLs:
```bash
python fuseki_setup.py --reload
```

### 3B — Análise de discurso com LLM local

Requer ollama com llama3.1:8b:
```bash
ollama pull llama3.1:8b
```

Teste com 20 documentos:
```bash
python discourse_analysis.py --limit 20
```

Corpus completo (~3-4 horas com RTX 4070):
```bash
python discourse_analysis.py
```

O que é extraído de cada seção de Conclusão/Resultados:
- **claims**: afirmações factais centrais do trabalho
- **contributions**: contribuições específicas declaradas pelos autores
- **limitations**: limitações explicitamente reconhecidas
- **future_work**: direções de trabalho futuro mencionadas
- **keywords_inferred**: conceitos técnicos inferidos pelo LLM

### 3C — Enriquecer o grafo com os resultados

Teste sem enviar ao Fuseki:
```bash
python enrich_graph.py --dry-run
```

Envia para o Fuseki:
```bash
python enrich_graph.py
```

### 3D — Executar queries SPARQL

Lista as queries disponíveis:
```bash
python sparql_queries.py --list
```

Roda todas as queries:
```bash
python sparql_queries.py
```

Roda uma query específica:
```bash
python sparql_queries.py --query 5
```

Exporta resultados:
```bash
python sparql_queries.py --export resultados.json
```

## Queries disponíveis

| ID | Nome | Descrição |
|---|---|---|
| 1 | Visão geral | Contagem de docs, seções, parágrafos |
| 2 | Tipos de documento | Teses vs Dissertações |
| 3 | Tipos retóricos (DEO) | Distribuição de Introduction, Conclusion, etc. |
| 4 | Top keywords | Termos mais frequentes nos metadados |
| 5 | Busca em conclusões | Parágrafos de Conclusão com termo X |
| 6 | Documentos por ano | Distribuição temporal |
| 7 | Claims por documento | Documentos mais ricos em afirmações |
| 8 | Busca em claims | Claims que mencionam conceito X |
| 9 | Sem conclusão | Docs sem deo:Conclusion (qualidade) |
| 10 | Refs mais citadas | Artigos mais referenciados no corpus |
| 11 | Limitações por área | Limitações por keyword técnica |
| 12 | Trabalhos futuros | Direções de pesquisa agregadas |

## Ontologia de discurso customizada

Namespace: `http://pantheon.ufrj.br/ontology/discourse#`

| Classe/Propriedade | Descrição |
|---|---|
| `discourse:ScientificClaim` | Afirmação factual extraída pelo LLM |
| `discourse:Contribution` | Contribuição declarada pelos autores |
| `discourse:Limitation` | Limitação reconhecida pelos autores |
| `discourse:FutureWork` | Direção de trabalho futuro |
| `discourse:AnalyzedDocument` | Documento processado pelo LLM |
| `discourse:hasClaim` | doc → claim |
| `discourse:hasContribution` | doc → contribution |
| `discourse:hasLimitation` | doc → limitation |
| `discourse:hasFutureWork` | doc → future work |
| `discourse:inferredKeyword` | keyword técnica inferida |
| `discourse:inSection` | claim/limitation → seção de origem |

## Exemplo de query avançada

"Quais conclusões de dissertações sobre redes neurais a partir de 2015
 mencionam limitações de dados?"

```sparql
SELECT ?titulo ?ano ?claim ?limitacao
WHERE {
  ?doc a fabio:MastersThesis .
  ?doc dcterms:title ?titulo .
  ?doc dcterms:date ?data .
  BIND(SUBSTR(STR(?data), 1, 4) AS ?ano)
  FILTER(xsd:integer(?ano) >= 2015)
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
