#!/usr/bin/env python3
# sparql_queries.py — executa queries SPARQL de análise sobre o corpus
#
# Uso:
#   python sparql_queries.py              # roda todas as queries
#   python sparql_queries.py --query 3   # roda só a query 3
#   python sparql_queries.py --list      # lista as queries disponíveis

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

# ── Catálogo de queries ───────────────────────────────────────────────────────
QUERIES = [
    {
        "id":    1,
        "name":  "Visão geral do corpus",
        "desc":  "Conta documentos, seções e parágrafos por tipo",
        "sparql": """
SELECT
  (COUNT(DISTINCT ?doc) AS ?documentos)
  (COUNT(DISTINCT ?sec) AS ?secoes)
  (COUNT(DISTINCT ?para) AS ?paragrafos)
WHERE {
  ?doc a fabio:Work .
  OPTIONAL { ?doc po:contains ?sec . ?sec a doco:Section }
  OPTIONAL { ?sec po:contains ?para . ?para a doco:Paragraph }
}
""",
    },
    {
        "id":    2,
        "name":  "Distribuição por tipo de documento",
        "desc":  "Teses vs Dissertações",
        "sparql": """
SELECT ?tipo (COUNT(?doc) AS ?total)
WHERE {
  ?doc a ?tipo .
  FILTER(?tipo IN (fabio:DoctoralThesis, fabio:MastersThesis, fabio:Work))
}
GROUP BY ?tipo
ORDER BY DESC(?total)
""",
    },
    {
        "id":    3,
        "name":  "Distribuição de tipos retóricos (DEO)",
        "desc":  "Quantas seções de cada tipo retórico existem no corpus",
        "sparql": """
SELECT ?tipo (COUNT(?sec) AS ?total)
WHERE {
  ?sec a ?tipo .
  FILTER(STRSTARTS(STR(?tipo), "http://purl.org/spar/deo/"))
}
GROUP BY ?tipo
ORDER BY DESC(?total)
""",
    },
    {
        "id":    4,
        "name":  "Top 20 keywords por frequência",
        "desc":  "Termos mais frequentes nos dc:subject do corpus",
        "sparql": """
SELECT ?keyword (COUNT(?doc) AS ?freq)
WHERE {
  ?doc a fabio:Work .
  ?doc dcterms:subject ?keyword .
}
GROUP BY ?keyword
ORDER BY DESC(?freq)
LIMIT 20
""",
    },
    {
        "id":    5,
        "name":  "Busca em conclusões — termo livre",
        "desc":  "Parágrafos de Conclusão que mencionam um termo",
        "sparql": """
SELECT ?titulo ?paragrafo
WHERE {
  ?doc dcterms:title ?titulo .
  ?doc po:contains ?sec .
  ?sec a deo:Conclusion .
  ?sec po:contains ?para .
  ?para a doco:Paragraph .
  ?para c4o:hasContent ?paragrafo .
  FILTER(CONTAINS(LCASE(?paragrafo), "aprendizado de máquina"))
}
LIMIT 10
""",
    },
    {
        "id":    6,
        "name":  "Documentos por ano",
        "desc":  "Distribuição temporal do corpus",
        "sparql": """
SELECT ?ano (COUNT(?doc) AS ?total)
WHERE {
  ?doc a fabio:Work .
  ?doc dcterms:date ?date .
  BIND(SUBSTR(STR(?date), 1, 4) AS ?ano)
  FILTER(?ano >= "1970" && ?ano <= "2030")
}
GROUP BY ?ano
ORDER BY ?ano
""",
    },
    {
        "id":    7,
        "name":  "Claims por documento (análise de discurso)",
        "desc":  "Documentos com mais claims extraídos pelo LLM",
        "sparql": """
SELECT ?titulo (COUNT(?claim) AS ?n_claims)
WHERE {
  ?doc a fabio:Work .
  ?doc dcterms:title ?titulo .
  ?doc discourse:hasClaim ?claim .
  FILTER(STRLEN(STR(?titulo)) > 20)
}
GROUP BY ?titulo
ORDER BY DESC(?n_claims)
LIMIT 15
""",
    },
    {
        "id":    8,
        "name":  "Busca em claims — termo livre",
        "desc":  "Claims que mencionam um conceito específico",
        "sparql": """
SELECT ?titulo ?claim
WHERE {
  ?doc dcterms:title ?titulo .
  ?doc discourse:hasClaim ?c .
  ?c c4o:hasContent ?claim .
  FILTER(CONTAINS(LCASE(?claim), "redes neurais"))
}
LIMIT 20
""",
    },
    {
        "id":    9,
        "name":  "Documentos sem conclusão estruturada",
        "desc":  "Identifica teses sem seção deo:Conclusion (qualidade do GROBID)",
        "sparql": """
SELECT ?titulo
WHERE {
  ?doc a fabio:Work .
  ?doc dcterms:title ?titulo .
  FILTER NOT EXISTS {
    ?doc po:contains ?sec .
    ?sec a deo:Conclusion .
  }
}
LIMIT 20
""",
    },
    {
        "id":    10,
        "name":  "Referências mais citadas (título exato)",
        "desc":  "Artigos mais referenciados no corpus",
        "sparql": """
SELECT ?ref_titulo (COUNT(?ref) AS ?n_citacoes)
WHERE {
  ?reflist a doco:ListOfReferences .
  ?reflist po:contains ?ref .
  ?ref dcterms:title ?ref_titulo .
  FILTER(STRLEN(?ref_titulo) > 10)
}
GROUP BY ?ref_titulo
ORDER BY DESC(?n_citacoes)
LIMIT 20
""",
    },
    {
        "id":    11,
        "name":  "Limitações por área (keywords inferidas)",
        "desc":  "Limitações associadas a conceitos técnicos",
        "sparql": """
SELECT ?keyword ?limitacao
WHERE {
  ?doc discourse:inferredKeyword ?keyword .
  ?doc discourse:hasLimitation ?lim .
  ?lim c4o:hasContent ?limitacao .
  FILTER(CONTAINS(LCASE(?keyword), "otimização"))
}
LIMIT 20
""",
    },
    {
        "id":    12,
        "name":  "Trabalhos futuros — visão agregada",
        "desc":  "Direções de pesquisa futura mencionadas no corpus",
        "sparql": """
SELECT ?future_work
WHERE {
  ?doc discourse:hasFutureWork ?fw .
  ?fw c4o:hasContent ?future_work .
}
LIMIT 30
""",
    },
    {
        "id":    13,
        "name":  "Top keywords inferidas pelo LLM",
        "desc":  "Conceitos técnicos mais frequentes extraídos da análise de discurso",
        "sparql": """
SELECT ?keyword (COUNT(?doc) AS ?freq)
WHERE {
  ?doc discourse:inferredKeyword ?keyword .
  FILTER(STRLEN(?keyword) > 4)
}
GROUP BY ?keyword
ORDER BY DESC(?freq)
LIMIT 25
""",
    },
    {
        "id":    14,
        "name":  "Teses com mais limitações declaradas",
        "desc":  "Documentos onde os autores mais explicitamente reconheceram limitações",
        "sparql": """
SELECT ?titulo (COUNT(?lim) AS ?n_limitacoes)
WHERE {
  ?doc a fabio:Work .
  ?doc dcterms:title ?titulo .
  ?doc discourse:hasLimitation ?lim .
  FILTER(STRLEN(STR(?titulo)) > 20)
}
GROUP BY ?titulo
ORDER BY DESC(?n_limitacoes)
LIMIT 15
""",
    },
    {
        "id":    15,
        "name":  "Busca cruzada: claims + ano + tipo de documento",
        "desc":  "Claims de teses de doutorado a partir de 2015 sobre otimização",
        "sparql": """
SELECT ?titulo ?ano ?claim
WHERE {
  ?doc dcterms:title ?titulo .
  ?doc dcterms:date ?date .
  BIND(SUBSTR(STR(?date), 1, 4) AS ?ano)
  FILTER(?ano >= "2015")
  ?doc discourse:hasClaim ?c .
  ?c c4o:hasContent ?claim .
  FILTER(CONTAINS(LCASE(?claim), "otimização") || CONTAINS(LCASE(?claim), "optimization"))
  FILTER(STRLEN(?titulo) > 15)
}
ORDER BY DESC(?ano)
LIMIT 15
""",
    },
    {
        "id":    16,
        "name":  "Evolução temporal: ML vs Elementos Finitos",
        "desc":  "Compara frequência de dois tópicos por ano",
        "sparql": """
SELECT ?ano
  (SUM(IF(CONTAINS(LCASE(STR(?kw)), "machine learning") || CONTAINS(LCASE(STR(?kw)), "aprendizado"), 1, 0)) AS ?ml)
  (SUM(IF(CONTAINS(LCASE(STR(?kw)), "elementos finitos") || CONTAINS(LCASE(STR(?kw)), "finite element"), 1, 0)) AS ?fem)
WHERE {
  ?doc a fabio:Work .
  ?doc dcterms:date ?date .
  ?doc dcterms:subject ?kw .
  BIND(SUBSTR(STR(?date), 1, 4) AS ?ano)
  FILTER(STRLEN(?ano) = 4)
}
GROUP BY ?ano
ORDER BY ?ano
""",
    },
    {
        "id":    17,
        "name":  "Limitações por área CNPq",
        "desc":  "Quais áreas têm mais limitações declaradas",
        "sparql": """
SELECT ?area (COUNT(?lim) AS ?n_limitacoes)
WHERE {
  ?doc a fabio:Work .
  ?doc dcterms:subject ?area .
  ?doc discourse:hasLimitation ?lim .
  FILTER(STRSTARTS(STR(?area), "CNPQ::"))
}
GROUP BY ?area
ORDER BY DESC(?n_limitacoes)
LIMIT 15
""",
    },
    {
        "id":    18,
        "name":  "Teses de doutorado com mais trabalhos futuros",
        "desc":  "Quais teses apontaram mais direções de pesquisa futura",
        "sparql": """
SELECT ?titulo ?ano (COUNT(?fw) AS ?n_fw)
WHERE {
  ?doc a fabio:DoctoralThesis .
  ?doc dcterms:title ?titulo .
  ?doc dcterms:date ?date .
  ?doc discourse:hasFutureWork ?fw .
  BIND(SUBSTR(STR(?date), 1, 4) AS ?ano)
  FILTER(STRLEN(STR(?titulo)) > 20)
}
GROUP BY ?titulo ?ano
ORDER BY DESC(?n_fw)
LIMIT 15
""",
    },
    {
        "id":    19,
        "name":  "Claims por tipo de seção retórica",
        "desc":  "Em quais seções DEO o LLM extrai mais claims",
        "sparql": """
SELECT ?tipo_secao (COUNT(?claim) AS ?n_claims)
WHERE {
  ?sec a ?tipo_secao .
  ?sec discourse:hasClaim ?claim .
  FILTER(STRSTARTS(STR(?tipo_secao), "http://purl.org/spar/deo/"))
}
GROUP BY ?tipo_secao
ORDER BY DESC(?n_claims)
""",
    },
    {
        "id":    20,
        "name":  "Teses em inglês",
        "desc":  "Documentos com idioma inglês no corpus",
        "sparql": """
SELECT ?titulo
WHERE {
  ?doc a fabio:Work .
  ?doc dcterms:title ?titulo .
  ?doc dcterms:language "eng" .
  FILTER(STRLEN(STR(?titulo)) > 20)
}
ORDER BY ?titulo
LIMIT 20
""",
    },
]


def run_query(sparql: str) -> list[dict]:
    full_query = PREFIXES + sparql
    try:
        r = requests.get(
            SPARQL_URL,
            params={"query": full_query},
            headers={"Accept": "application/sparql-results+json"},
            auth=(FUSEKI_USER, FUSEKI_PASS),
            timeout=60,
        )
        if r.status_code != 200:
            print(f"  Erro HTTP {r.status_code}: {r.text[:300]}")
            return []
        data    = r.json()
        vars_   = data["head"]["vars"]
        results = []
        for binding in data["results"]["bindings"]:
            row = {}
            for v in vars_:
                val = binding.get(v, {}).get("value", "")
                # Encurta URIs
                val = val.replace("http://purl.org/spar/deo/", "deo:")
                val = val.replace("http://purl.org/spar/doco/", "doco:")
                val = val.replace("http://purl.org/spar/fabio/", "fabio:")
                row[v] = val[:120]  # trunca valores longos
            results.append(row)
        return results
    except Exception as e:
        print(f"  Erro: {e}")
        return []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", type=int, default=None,
                        help="Roda só esta query (pelo id)")
    parser.add_argument("--list",  action="store_true",
                        help="Lista queries disponíveis")
    parser.add_argument("--export", type=str, default=None,
                        help="Exporta resultados para JSON")
    args = parser.parse_args()

    if args.list:
        print("\nQueries disponíveis:\n")
        for q in QUERIES:
            print(f"  [{q['id']:2d}] {q['name']}")
            print(f"       {q['desc']}")
        return

    # Verifica Fuseki
    try:
        r = requests.get(f"{FUSEKI_URL}/$/ping",
                         auth=(FUSEKI_USER, FUSEKI_PASS), timeout=5)
        assert r.status_code == 200
        print(f"✓ Fuseki em {SPARQL_URL}\n")
    except Exception:
        print("✗ Fuseki não acessível. Execute: python fuseki_setup.py")
        sys.exit(1)

    to_run = [q for q in QUERIES if q["id"] == args.query] if args.query else QUERIES
    all_results = {}

    for q in to_run:
        print(f"{'='*60}")
        print(f"[{q['id']}] {q['name']}")
        print(f"    {q['desc']}")
        print()

        rows = run_query(q["sparql"])
        if rows:
            print(tabulate(rows, headers="keys", tablefmt="rounded_outline",
                           maxcolwidths=80))
            print(f"\n  {len(rows)} resultados")
        else:
            print("  Sem resultados.")

        all_results[q["id"]] = {"query": q, "results": rows}
        print()

    if args.export:
        with open(args.export, "w", encoding="utf-8") as f:
            json.dump(all_results, f, ensure_ascii=False, indent=2)
        print(f"Resultados exportados para: {args.export}")


if __name__ == "__main__":
    main()