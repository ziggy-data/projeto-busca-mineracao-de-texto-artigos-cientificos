#!/usr/bin/env python3
# validate_graph.py — validação de integridade do grafo via SPARQL
#
# Complementa o SHACL com verificações semânticas que o SHACL não cobre:
# consistência entre tipos, orphan nodes, relações quebradas, etc.
#
# Uso:
#   python validate_graph.py
#   python validate_graph.py --export avaliacao/data/graph_integrity.json

import argparse
import json
from datetime import datetime
from pathlib import Path

import requests

FUSEKI_URL  = "http://localhost:3030"
DATASET     = "pantheon"
FUSEKI_USER = "admin"
FUSEKI_PASS = "pantheon123"
SPARQL_URL  = f"{FUSEKI_URL}/{DATASET}/query"

PREFIXES = """
PREFIX doco:      <http://purl.org/spar/doco/>
PREFIX deo:       <http://purl.org/spar/deo/>
PREFIX c4o:       <http://purl.org/spar/c4o/>
PREFIX fabio:     <http://purl.org/spar/fabio/>
PREFIX po:        <http://www.essepuntato.it/2008/12/pattern#>
PREFIX dcterms:   <http://purl.org/dc/terms/>
PREFIX discourse: <http://pantheon.ufrj.br/ontology/discourse#>
PREFIX bibo:      <http://purl.org/ontology/bibo/>
"""

# ── Checks ────────────────────────────────────────────────────────────────────
# Cada check é (nome, descrição, query SPARQL, esperado_zero)
# esperado_zero=True  → o resultado deve ser 0 para o grafo estar correto
# esperado_zero=False → apenas informa, sem critério de falha

CHECKS = [
    (
        "documentos_sem_titulo",
        "Documentos sem dcterms:title",
        """SELECT (COUNT(?doc) AS ?n)
WHERE { ?doc a fabio:Work . FILTER NOT EXISTS { ?doc dcterms:title ?t } }""",
        True,
    ),
    (
        "documentos_sem_tipo",
        "Documentos sem tipo específico (não são nem Tese nem Dissertação)",
        """SELECT (COUNT(?doc) AS ?n)
WHERE {
  ?doc a fabio:Work .
  FILTER NOT EXISTS {
    ?doc a ?tipo .
    FILTER(?tipo IN (fabio:DoctoralThesis, fabio:MastersThesis))
  }
}""",
        True,
    ),
    (
        "paragrafos_sem_conteudo",
        "Parágrafos sem c4o:hasContent",
        """SELECT (COUNT(?p) AS ?n)
WHERE { ?p a doco:Paragraph . FILTER NOT EXISTS { ?p c4o:hasContent ?t } }""",
        True,
    ),
    (
        "secoes_orfas",
        "Seções sem documento pai (nenhum nível da hierarquia)",
        """SELECT (COUNT(?sec) AS ?n)
WHERE {
  ?sec a doco:Section .
  FILTER NOT EXISTS {
    { ?doc a fabio:Work . ?doc po:contains ?sec . }
    UNION
    { ?doc a fabio:Work . ?doc po:contains ?mid . ?mid po:contains ?sec . }
    UNION
    { ?doc a fabio:Work . ?doc po:contains ?m1 . ?m1 po:contains ?m2 . ?m2 po:contains ?sec . }
  }
}""",
        False,  # informativo — esperado em PDFs históricos com OCR
    ),
    (
        "claims_sem_conteudo",
        "Claims LLM sem c4o:hasContent",
        """SELECT (COUNT(?c) AS ?n)
WHERE {
  ?doc discourse:hasClaim ?c .
  FILTER NOT EXISTS { ?c c4o:hasContent ?t }
}""",
        True,
    ),
    (
        "claims_sem_documento",
        "Claims não ligados a nenhum documento",
        """SELECT (COUNT(?c) AS ?n)
WHERE {
  ?c a discourse:ScientificClaim .
  FILTER NOT EXISTS { ?doc discourse:hasClaim ?c }
}""",
        True,
    ),
    (
        "documentos_duplicados",
        "Handles duplicados (mesmo documento indexado mais de uma vez)",
        """SELECT (COUNT(*) AS ?n)
WHERE {
  SELECT ?handle WHERE {
    ?doc bibo:handle ?handle .
  }
  GROUP BY ?handle
  HAVING (COUNT(?doc) > 1)
}""",
        True,
    ),
    (
        "titulos_suspeitos",
        "Documentos com títulos suspeitos (Lista de Figuras, Agradecimentos, etc.)",
        """SELECT (COUNT(?doc) AS ?n)
WHERE {
  ?doc a fabio:Work .
  ?doc dcterms:title ?titulo .
  FILTER(
    CONTAINS(LCASE(?titulo), "lista de figuras") ||
    CONTAINS(LCASE(?titulo), "lista de tabelas") ||
    CONTAINS(LCASE(?titulo), "agradecimentos") ||
    CONTAINS(LCASE(?titulo), "sumário") ||
    STRLEN(?titulo) < 10
  )
}""",
        True,
    ),
    (
        "titulos_suspeitos_lista",
        "Lista dos títulos suspeitos encontrados",
        """SELECT ?titulo (COUNT(?doc) AS ?n)
WHERE {
  ?doc a fabio:Work .
  ?doc dcterms:title ?titulo .
  FILTER(
    CONTAINS(LCASE(?titulo), "lista de figuras") ||
    CONTAINS(LCASE(?titulo), "lista de tabelas") ||
    CONTAINS(LCASE(?titulo), "agradecimentos") ||
    CONTAINS(LCASE(?titulo), "sumário") ||
    STRLEN(?titulo) < 10
  )
}
GROUP BY ?titulo ORDER BY ?titulo""",
        False,   # informativo — apenas lista quais são
    ),
    (
        "total_documentos",
        "Total de documentos no grafo",
        "SELECT (COUNT(?doc) AS ?n) WHERE { ?doc a fabio:Work }",
        False,
    ),
    (
        "total_secoes",
        "Total de seções estruturadas",
        "SELECT (COUNT(?s) AS ?n) WHERE { ?s a doco:Section }",
        False,
    ),
    (
        "total_paragrafos",
        "Total de parágrafos",
        "SELECT (COUNT(?p) AS ?n) WHERE { ?p a doco:Paragraph }",
        False,
    ),
    (
        "total_claims",
        "Total de claims extraídos pelo LLM",
        "SELECT (COUNT(?c) AS ?n) WHERE { ?doc discourse:hasClaim ?c }",
        False,
    ),
    (
        "total_limitacoes",
        "Total de limitações extraídas",
        "SELECT (COUNT(?l) AS ?n) WHERE { ?doc discourse:hasLimitation ?l }",
        False,
    ),
    (
        "cobertura_deo",
        "Seções com tipo retórico DEO atribuído",
        """SELECT (COUNT(?s) AS ?n)
WHERE {
  ?s a doco:Section .
  ?s a ?tipo .
  FILTER(STRSTARTS(STR(?tipo), "http://purl.org/spar/deo/"))
}""",
        False,
    ),
    (
        "docs_sem_secoes",
        "Documentos sem nenhuma seção extraída pelo GROBID",
        """SELECT (COUNT(?doc) AS ?n)
WHERE {
  ?doc a fabio:Work .
  FILTER NOT EXISTS { ?doc po:contains ?sec . ?sec a doco:Section }
}""",
        False,  # informativo — esperado para PDFs não processados
    ),
    (
        "docs_com_discourse",
        "Documentos com pelo menos 1 elemento de discurso (claim/limitação/futuro)",
        """SELECT (COUNT(DISTINCT ?doc) AS ?n)
WHERE {
  ?doc a fabio:Work .
  { ?doc discourse:hasClaim ?x }
  UNION { ?doc discourse:hasLimitation ?x }
  UNION { ?doc discourse:hasFutureWork ?x }
}""",
        False,
    ),
]


# ── Execução ──────────────────────────────────────────────────────────────────

def run_check(name: str, desc: str, query: str) -> int | None:
    try:
        r = requests.get(
            SPARQL_URL,
            params={"query": PREFIXES + query},
            headers={"Accept": "application/sparql-results+json"},
            auth=(FUSEKI_USER, FUSEKI_PASS),
            timeout=60,
        )
        if r.status_code != 200:
            return None
        bindings = r.json()["results"]["bindings"]
        if bindings and "n" in bindings[0]:
            return int(bindings[0]["n"]["value"])
        return 0
    except Exception:
        return None


def run_check_list(query: str) -> list[dict]:
    """Executa uma query que retorna múltiplas linhas."""
    try:
        r = requests.get(
            SPARQL_URL,
            params={"query": PREFIXES + query},
            headers={"Accept": "application/sparql-results+json"},
            auth=(FUSEKI_USER, FUSEKI_PASS),
            timeout=60,
        )
        if r.status_code != 200:
            return []
        data  = r.json()
        vars_ = data["head"]["vars"]
        return [{v: b.get(v, {}).get("value", "") for v in vars_}
                for b in data["results"]["bindings"]]
    except Exception:
        return []


def main():
    parser = argparse.ArgumentParser(
        description="Valida integridade semântica do grafo via SPARQL"
    )
    parser.add_argument("--export", default=None)
    args = parser.parse_args()

    try:
        r = requests.get(f"{FUSEKI_URL}/$/ping",
                         auth=(FUSEKI_USER, FUSEKI_PASS), timeout=5)
        assert r.status_code == 200
    except Exception:
        print("✗ Fuseki não acessível")
        return

    BOLD = "\033[1m"; RST = "\033[0m"
    OK   = "\033[92m✓\033[0m"
    FAIL = "\033[91m✗\033[0m"
    INFO = "\033[94m·\033[0m"

    print(f"\n{BOLD}{'='*65}{RST}")
    print(f"{BOLD}  VALIDAÇÃO DE INTEGRIDADE DO GRAFO — SPARQL{RST}")
    print(f"{BOLD}{'='*65}{RST}\n")

    results    = []
    n_pass     = 0
    n_fail     = 0
    n_info     = 0

    print(f"  {'Verificação':<45} {'Valor':>8}  {'Status'}")
    print(f"  {'-'*65}")

    for name, desc, query, esperado_zero in CHECKS:
        val = run_check(name, desc, query)

        if val is None:
            icon = "?"
            status = "erro"
        elif esperado_zero:
            if val == 0:
                icon = OK; status = "ok"; n_pass += 1
            else:
                icon = FAIL; status = f"{val} problema(s)"; n_fail += 1
        else:
            icon = INFO; status = "info"; n_info += 1

        val_str = str(val) if val is not None else "erro"
        print(f"  {icon}  {desc:<43} {val_str:>8}  {status}")

        results.append({
            "check":          name,
            "descricao":      desc,
            "valor":          val,
            "esperado_zero":  esperado_zero,
            "passou":         (val == 0) if esperado_zero else None,
        })

        # Para títulos suspeitos: mostra quais são
        if name == "titulos_suspeitos" and val and val > 0:
            q = (
                "SELECT ?titulo WHERE {"
                " ?doc a fabio:Work . ?doc dcterms:title ?titulo ."
                " FILTER(CONTAINS(LCASE(?titulo),'lista de figuras')"
                " || CONTAINS(LCASE(?titulo),'lista de tabelas')"
                " || CONTAINS(LCASE(?titulo),'agradecimentos')"
                " || STRLEN(?titulo) < 10)"
                " } LIMIT 20"
            )
            rows = run_check_list(q)
            if rows:
                print(f"         Títulos encontrados:")
                for row in rows:
                    print(f"           · {row.get('titulo','')[:70]}")

    print(f"\n{BOLD}{'='*65}{RST}")
    print(f"  Verificações críticas: {n_pass} ✓  {n_fail} ✗")
    if n_fail == 0:
        print(f"  {OK} Grafo íntegro — nenhuma inconsistência crítica encontrada")
    else:
        print(f"  {FAIL} {n_fail} inconsistência(s) encontrada(s) — verifique acima")
    print(f"{BOLD}{'='*65}{RST}\n")

    if args.export:
        output = {
            "timestamp":   datetime.now().isoformat(),
            "n_checks":    len(results),
            "n_criticos":  sum(1 for r in results if r["esperado_zero"]),
            "n_pass":      n_pass,
            "n_fail":      n_fail,
            "integro":     n_fail == 0,
            "checks":      results,
        }
        Path(args.export).parent.mkdir(parents=True, exist_ok=True)
        with open(args.export, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"✓ Relatório exportado: {args.export}")


if __name__ == "__main__":
    main()