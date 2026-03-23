#!/usr/bin/env python3
# sparql_advanced.py — queries avançadas de análise do corpus
#
# Complementa o sparql_queries.py com análises mais profundas:
#   - Evolução temporal de temas
#   - Redes de co-ocorrência de keywords
#   - Análise por subárea CNPq
#   - Padrões de limitações por área
#
# Uso:
#   python sparql_advanced.py              # roda todas
#   python sparql_advanced.py --query 2    # roda query específica
#   python sparql_advanced.py --export resultados_avancados.json

import argparse
import json
import sys

import requests
from tabulate import tabulate

FUSEKI_URL  = "http://localhost:3030"
DATASET     = "pantheon"
FUSEKI_USER = "admin"
FUSEKI_PASS = "pantheon123"
SPARQL_URL  = f"{FUSEKI_URL}/{DATASET}/query"

PREFIXES = """
PREFIX doco:     <http://purl.org/spar/doco/>
PREFIX deo:      <http://purl.org/spar/deo/>
PREFIX c4o:      <http://purl.org/spar/c4o/>
PREFIX fabio:    <http://purl.org/spar/fabio/>
PREFIX po:       <http://www.essepuntato.it/2008/12/pattern#>
PREFIX dcterms:  <http://purl.org/dc/terms/>
PREFIX bibo:     <http://purl.org/ontology/bibo/>
PREFIX schema:   <http://schema.org/>
PREFIX base:     <http://pantheon.ufrj.br/resource/>
PREFIX discourse:<http://pantheon.ufrj.br/ontology/discourse#>
PREFIX xsd:      <http://www.w3.org/2001/XMLSchema#>
"""

QUERIES = [
    {
        "id":    1,
        "name":  "Evolução temporal: machine learning na COPPE",
        "desc":  "Quantas teses/dissertações por ano mencionam ML/IA em seus claims",
        "sparql": """
SELECT ?ano (COUNT(DISTINCT ?doc) AS ?docs_com_ml)
WHERE {
  ?doc a fabio:Work .
  ?doc dcterms:date ?date .
  BIND(SUBSTR(STR(?date), 1, 4) AS ?ano)
  FILTER(STRLEN(?ano) = 4)
  ?doc discourse:hasClaim ?c .
  ?c c4o:hasContent ?claim .
  FILTER(
    CONTAINS(LCASE(?claim), "machine learning") ||
    CONTAINS(LCASE(?claim), "aprendizado de máquina") ||
    CONTAINS(LCASE(?claim), "deep learning") ||
    CONTAINS(LCASE(?claim), "rede neural") ||
    CONTAINS(LCASE(?claim), "inteligência artificial")
  )
}
GROUP BY ?ano
ORDER BY ?ano
""",
    },
    {
        "id":    2,
        "name":  "Distribuição de trabalhos futuros por área CNPq",
        "desc":  "Quais áreas geram mais direções de pesquisa futura",
        "sparql": """
SELECT ?area (COUNT(?fw) AS ?n_futuros)
WHERE {
  ?doc a fabio:Work .
  ?doc dcterms:subject ?area .
  ?doc discourse:hasFutureWork ?fw .
  FILTER(STRSTARTS(?area, "CNPQ::"))
  FILTER(STRLEN(STR(?area)) > 10)
}
GROUP BY ?area
ORDER BY DESC(?n_futuros)
LIMIT 20
""",
    },
    {
        "id":    3,
        "name":  "Teses vs Dissertações: densidade de claims",
        "desc":  "Comparação de riqueza de extração entre tipo de documento",
        "sparql": """
SELECT ?tipo
  (COUNT(DISTINCT ?doc) AS ?n_docs)
  (COUNT(?claim) AS ?total_claims)
WHERE {
  ?doc a ?tipo .
  FILTER(?tipo IN (fabio:DoctoralThesis, fabio:MastersThesis))
  OPTIONAL {
    ?doc discourse:hasClaim ?claim .
  }
}
GROUP BY ?tipo
ORDER BY ?tipo
""",
    },
    {
        "id":    4,
        "name":  "Top limitações mencionadas em Engenharia Civil",
        "desc":  "Limitações mais frequentes nas teses de Engenharia Civil",
        "sparql": """
SELECT ?limitacao
WHERE {
  ?doc a fabio:Work .
  ?doc dcterms:subject ?subj .
  FILTER(CONTAINS(LCASE(?subj), "engenharia civil"))
  ?doc discourse:hasLimitation ?lim .
  ?lim c4o:hasContent ?limitacao .
  FILTER(STRLEN(?limitacao) > 30)
}
LIMIT 20
""",
    },
    {
        "id":    5,
        "name":  "Documentos com maior densidade estrutural (DoCO)",
        "desc":  "Teses com mais seções e parágrafos identificados pelo GROBID",
        "sparql": """
SELECT ?titulo (COUNT(DISTINCT ?sec) AS ?n_secoes) (COUNT(DISTINCT ?para) AS ?n_paragrafos)
WHERE {
  ?doc a fabio:Work .
  ?doc dcterms:title ?titulo .
  ?doc po:contains ?sec .
  ?sec a doco:Section .
  ?sec po:contains ?para .
  ?para a doco:Paragraph .
  FILTER(STRLEN(STR(?titulo)) > 20)
}
GROUP BY ?titulo
ORDER BY DESC(?n_paragrafos)
LIMIT 15
""",
    },
    {
        "id":    6,
        "name":  "Referências canônicas por subárea",
        "desc":  "Livros/artigos mais citados em cada grande área",
        "sparql": """
SELECT ?area ?ref_titulo (COUNT(?ref) AS ?n)
WHERE {
  ?doc a fabio:Work .
  ?doc dcterms:subject ?area .
  ?doc po:contains ?reflist .
  ?reflist a doco:ListOfReferences .
  ?reflist po:contains ?ref .
  ?ref dcterms:title ?ref_titulo .
  FILTER(STRSTARTS(?area, "CNPQ::ENGENHARIAS::"))
  FILTER(STRLEN(?ref_titulo) > 8)
  FILTER(!CONTAINS(?ref_titulo, "Disponível"))
  FILTER(!CONTAINS(?ref_titulo, "Rio de Janeiro"))
  FILTER(!CONTAINS(?ref_titulo, "Referências"))
}
GROUP BY ?area ?ref_titulo
ORDER BY ?area DESC(?n)
LIMIT 30
""",
    },
    {
        "id":    7,
        "name":  "Análise do discurso: contribuições únicas por documento",
        "desc":  "Teses com as contribuições mais específicas (não genéricas)",
        "sparql": """
SELECT ?titulo ?contribuicao
WHERE {
  ?doc a fabio:Work .
  ?doc dcterms:title ?titulo .
  ?doc discourse:hasContribution ?contrib .
  ?contrib c4o:hasContent ?contribuicao .
  FILTER(STRLEN(?contribuicao) > 60)
  FILTER(STRLEN(STR(?titulo)) > 20)
  FILTER(!CONTAINS(LCASE(?contribuicao), "este trabalho"))
  FILTER(!CONTAINS(LCASE(?contribuicao), "neste trabalho"))
  FILTER(!CONTAINS(LCASE(?contribuicao), "this work"))
  FILTER(!CONTAINS(LCASE(?contribuicao), "this thesis"))
}
ORDER BY RAND()
LIMIT 15
""",
    },
    {
        "id":    8,
        "name":  "Análise temporal: sustentabilidade como tema",
        "desc":  "Evolução do tema sustentabilidade/ambiental no corpus",
        "sparql": """
SELECT ?ano (COUNT(DISTINCT ?doc) AS ?total)
WHERE {
  ?doc a fabio:Work .
  ?doc dcterms:date ?date .
  BIND(SUBSTR(STR(?date), 1, 4) AS ?ano)
  FILTER(STRLEN(?ano) = 4)
  {
    ?doc dcterms:subject ?subj .
    FILTER(CONTAINS(LCASE(?subj), "sustentab") || CONTAINS(LCASE(?subj), "ambiental"))
  } UNION {
    ?doc discourse:inferredKeyword ?kw .
    FILTER(CONTAINS(LCASE(?kw), "sustentab") || CONTAINS(LCASE(?kw), "ambiental"))
  }
}
GROUP BY ?ano
ORDER BY ?ano
""",
    },
    {
        "id":    9,
        "name":  "Cobertura DoCO: seções por tipo retórico por ano",
        "desc":  "Como a estrutura retórica das teses evoluiu ao longo do tempo",
        "sparql": """
SELECT ?ano ?tipo (COUNT(?sec) AS ?total)
WHERE {
  ?doc a fabio:Work .
  ?doc dcterms:date ?date .
  BIND(SUBSTR(STR(?date), 1, 4) AS ?ano)
  FILTER(STRLEN(?ano) = 4 && ?ano >= "2015")
  ?doc po:contains ?sec .
  ?sec a ?tipo .
  FILTER(?tipo IN (deo:Introduction, deo:Methods, deo:Results,
                   deo:Conclusion, deo:Discussion, deo:RelatedWork))
}
GROUP BY ?ano ?tipo
ORDER BY ?ano ?tipo
""",
    },
    {
        "id":    10,
        "name":  "Claims com números/métricas (resultados quantitativos)",
        "desc":  "Claims que contêm valores numéricos — resultados mais mensuráveis",
        "sparql": """
SELECT ?titulo ?claim
WHERE {
  ?doc a fabio:Work .
  ?doc dcterms:title ?titulo .
  ?doc discourse:hasClaim ?c .
  ?c c4o:hasContent ?claim .
  FILTER(STRLEN(STR(?titulo)) > 20)
  FILTER(STRLEN(?claim) > 50)
  FILTER(
    CONTAINS(?claim, "%") ||
    CONTAINS(?claim, "melhoria de") ||
    CONTAINS(?claim, "redução de") ||
    CONTAINS(?claim, "aumento de") ||
    CONTAINS(?claim, "improvement of") ||
    CONTAINS(?claim, "reduction of") ||
    CONTAINS(?claim, " vezes ") ||
    CONTAINS(?claim, "superior a") ||
    CONTAINS(?claim, "inferior a") ||
    CONTAINS(?claim, "acurácia de") ||
    CONTAINS(?claim, "precisão de") ||
    CONTAINS(?claim, "eficiência de")
  )
}
LIMIT 20
""",
    },
]


def run_query(sparql: str) -> list[dict]:
    try:
        r = requests.get(
            SPARQL_URL,
            params={"query": PREFIXES + sparql},
            headers={"Accept": "application/sparql-results+json"},
            auth=(FUSEKI_USER, FUSEKI_PASS),
            timeout=90,
        )
        if r.status_code != 200:
            print(f"  Erro HTTP {r.status_code}: {r.text[:200]}")
            return []
        data  = r.json()
        vars_ = data["head"]["vars"]
        rows  = []
        for binding in data["results"]["bindings"]:
            row = {}
            for v in vars_:
                val = binding.get(v, {}).get("value", "")
                val = val.replace("http://purl.org/spar/deo/", "deo:")
                val = val.replace("http://purl.org/spar/doco/", "doco:")
                val = val.replace("http://purl.org/spar/fabio/", "fabio:")
                val = val.replace("CNPQ::", "")
                row[v] = val[:120]
            rows.append(row)
        return rows
    except Exception as e:
        print(f"  Erro: {e}")
        return []


def main():
    parser = argparse.ArgumentParser(description="Queries SPARQL avançadas")
    parser.add_argument("--query",  type=int, default=None)
    parser.add_argument("--export", type=str, default=None)
    args = parser.parse_args()

    try:
        r = requests.get(f"{FUSEKI_URL}/$/ping",
                         auth=(FUSEKI_USER, FUSEKI_PASS), timeout=5)
        assert r.status_code == 200
        print(f"✓ Fuseki em {SPARQL_URL}\n")
    except Exception:
        print("✗ Fuseki não acessível")
        sys.exit(1)

    to_run = [q for q in QUERIES if q["id"] == args.query] if args.query else QUERIES
    all_results = {}

    for q in to_run:
        print(f"{'='*65}")
        print(f"[{q['id']}] {q['name']}")
        print(f"    {q['desc']}")
        print()
        rows = run_query(q["sparql"])
        if rows:
            print(tabulate(rows, headers="keys", tablefmt="rounded_outline",
                           maxcolwidths=70))
            print(f"\n  {len(rows)} resultados")
        else:
            print("  Sem resultados.")
        all_results[q["id"]] = {"query": q, "results": rows}
        print()

    if args.export:
        with open(args.export, "w", encoding="utf-8") as f:
            json.dump(all_results, f, ensure_ascii=False, indent=2)
        print(f"Resultados exportados: {args.export}")


if __name__ == "__main__":
    main()