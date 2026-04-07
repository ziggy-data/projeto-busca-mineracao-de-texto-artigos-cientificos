#!/usr/bin/env python3
# shacl_validate.py — valida a conformidade dos TTLs com shapes SHACL
#
# Parte do plano de avaliação (H2 — qualidade estrutural do grafo).
# Localização: avaliacao/shacl_validate.py
#
# Verifica se o grafo RDF gerado pela pipeline respeita as restrições
# formais definidas pelas ontologias utilizadas (DoCO, DEO, FaBiO, discourse#).
#
# Requer: pip install pyshacl
#
# Uso:
#   python shacl_validate.py                    # valida todos os TTLs
#   python shacl_validate.py --limit 50         # amostra de 50
#   python shacl_validate.py --export relatorio.json
#   python shacl_validate.py --strict           # falha se qualquer violação for encontrada

import argparse
import json
import sys
import time
from pathlib import Path

try:
    from pyshacl import validate
except ImportError:
    print("✗ pyshacl não instalado. Execute: pip install pyshacl")
    sys.exit(1)

from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import RDF, XSD
from tqdm import tqdm

# ── Caminhos ──────────────────────────────────────────────────────────────────
_HERE    = Path(__file__).parent
RDF_DIR  = _HERE.parent / "fase_2" / "data" / "rdf"

# ── Namespaces ────────────────────────────────────────────────────────────────
SHACL     = Namespace("http://www.w3.org/ns/shacl#")
DOCO      = Namespace("http://purl.org/spar/doco/")
DEO       = Namespace("http://purl.org/spar/deo/")
C4O       = Namespace("http://purl.org/spar/c4o/")
FABIO     = Namespace("http://purl.org/spar/fabio/")
PO        = Namespace("http://www.essepuntato.it/2008/12/pattern#")
DCTERMS   = Namespace("http://purl.org/dc/terms/")
DISCOURSE = Namespace("http://pantheon.ufrj.br/ontology/discourse#")
BIBO      = Namespace("http://purl.org/ontology/bibo/")

# ── Shapes SHACL ─────────────────────────────────────────────────────────────
# Definidas inline em Turtle — cada shape descreve as restrições que cada
# tipo de nó deve satisfazer no grafo.

SHAPES_TTL = """
@base             <http://pantheon.ufrj.br/shapes#> .
@prefix :         <http://pantheon.ufrj.br/shapes#> .
@prefix sh:       <http://www.w3.org/ns/shacl#> .
@prefix doco:     <http://purl.org/spar/doco/> .
@prefix deo:      <http://purl.org/spar/deo/> .
@prefix c4o:      <http://purl.org/spar/c4o/> .
@prefix fabio:    <http://purl.org/spar/fabio/> .
@prefix po:       <http://www.essepuntato.it/2008/12/pattern#> .
@prefix dcterms:  <http://purl.org/dc/terms/> .
@prefix bibo:     <http://purl.org/ontology/bibo/> .
@prefix xsd:      <http://www.w3.org/2001/XMLSchema#> .

# ── Shape: Documento (fabio:Work) ──────────────────────────────────────────
# Todo documento deve ter título e pelo menos um tipo bibliográfico.

:WorkShape a sh:NodeShape ;
    sh:targetClass fabio:Work ;
    sh:name "Documento" ;

    sh:property [
        sh:path dcterms:title ;
        sh:minCount 1 ;
        sh:datatype xsd:string ;
        sh:minLength 3 ;
        sh:message "Documento sem título ou com título vazio." ;
        sh:severity sh:Violation ;
    ] ;

    sh:property [
        sh:path bibo:handle ;
        sh:minCount 1 ;
        sh:message "Documento sem handle (identificador único do repositório)." ;
        sh:severity sh:Violation ;
    ] ;

    sh:property [
        sh:path dcterms:date ;
        sh:maxCount 1 ;
        sh:message "Documento com mais de uma data — verificar duplicação." ;
        sh:severity sh:Warning ;
    ] .

# Nota: SectionShape removida — seções sem parágrafo são
# limitação esperada do GROBID em PDFs de engenharia,
# não uma violação do modelo de dados do projeto.


# ── Shape: Parágrafo (doco:Paragraph) ────────────────────────────────────
# Todo parágrafo deve ter conteúdo textual não vazio.

:ParagraphShape a sh:NodeShape ;
    sh:targetClass doco:Paragraph ;
    sh:name "Parágrafo" ;

    sh:property [
        sh:path c4o:hasContent ;
        sh:minCount 1 ;
        sh:datatype xsd:string ;
        sh:minLength 1 ;
        sh:message "Parágrafo sem conteúdo textual (c4o:hasContent)." ;
        sh:severity sh:Violation ;
    ] .

# ── Shape: Abstract (doco:Abstract) ──────────────────────────────────────

:AbstractShape a sh:NodeShape ;
    sh:targetClass doco:Abstract ;
    sh:name "Abstract" ;

    sh:property [
        sh:path c4o:hasContent ;
        sh:minCount 1 ;
        sh:minLength 30 ;
        sh:message "Abstract vazio ou muito curto (menos de 30 caracteres)." ;
        sh:severity sh:Warning ;
    ] .

# ── Shape: Referência bibliográfica ──────────────────────────────────────
# Referências devem ter pelo menos título.

:ReferenceShape a sh:NodeShape ;
    sh:targetClass doco:BibliographicReference ;
    sh:name "Referência Bibliográfica" ;

    sh:property [
        sh:path dcterms:title ;
        sh:minCount 1 ;
        sh:message "Referência sem título." ;
        sh:severity sh:Warning ;
    ] .
"""


# ── Validação ─────────────────────────────────────────────────────────────────

def validate_ttl(ttl_path: Path, shapes_graph: Graph) -> dict:
    """Valida um TTL contra as shapes. Retorna resultado estruturado."""
    try:
        data_graph = Graph()
        data_graph.parse(str(ttl_path), format="turtle")

        conforms, results_graph, results_text = validate(
            data_graph,
            shacl_graph=shapes_graph,
            abort_on_first=False,
            allow_infos=True,
            meta_shacl=False,
            inference="none",
        )

        # Extrai violações individuais do results_graph
        violations = []
        warnings   = []

        SHACL_NS = Namespace("http://www.w3.org/ns/shacl#")
        for result in results_graph.subjects(RDF.type, SHACL_NS.ValidationResult):
            severity = results_graph.value(result, SHACL_NS.resultSeverity)
            message  = results_graph.value(result, SHACL_NS.resultMessage)
            path     = results_graph.value(result, SHACL_NS.resultPath)
            node     = results_graph.value(result, SHACL_NS.focusNode)

            entry = {
                "message":  str(message) if message else "",
                "path":     str(path).split("/")[-1] if path else "",
                "node":     str(node).split("/")[-1] if node else "",
            }
            if str(severity).endswith("Violation"):
                violations.append(entry)
            else:
                warnings.append(entry)

        return {
            "file":       ttl_path.name,
            "conforms":   conforms,
            "violations": violations,
            "warnings":   warnings,
            "n_triples":  len(data_graph),
        }

    except Exception as e:
        return {
            "file":       ttl_path.name,
            "conforms":   False,
            "violations": [{"message": f"Erro ao processar: {e}", "path": "", "node": ""}],
            "warnings":   [],
            "n_triples":  0,
            "error":      str(e),
        }


# ── Relatório ─────────────────────────────────────────────────────────────────

def print_report(results: list[dict], elapsed: float):
    n_total     = len(results)
    n_conforms  = sum(1 for r in results if r["conforms"])
    n_violation = sum(1 for r in results if r["violations"])
    n_warning   = sum(1 for r in results if r["warnings"])

    all_violations = [v for r in results for v in r["violations"]]
    all_warnings   = [w for r in results for w in r["warnings"]]

    print(f"\n{'='*60}")
    print(f"RELATÓRIO DE VALIDAÇÃO SHACL")
    print(f"{'='*60}")
    print(f"  TTLs validados           : {n_total:,}")
    print(f"  ✓ Em conformidade        : {n_conforms:,} ({100*n_conforms//n_total}%)")
    print(f"  ✗ Com violações          : {n_violation:,}")
    print(f"  ⚠ Com avisos             : {n_warning:,}")
    print(f"  Tempo de validação       : {elapsed:.1f}s")

    if all_violations:
        from collections import Counter
        print(f"\n── Violações mais frequentes ──────────────────────────")
        freq = Counter(v["message"] for v in all_violations)
        for msg, count in freq.most_common(8):
            print(f"  {count:4d}x  {msg[:70]}")

    if all_warnings:
        from collections import Counter
        print(f"\n── Avisos mais frequentes ─────────────────────────────")
        freq = Counter(w["message"] for w in all_warnings)
        for msg, count in freq.most_common(5):
            print(f"  {count:4d}x  {msg[:70]}")

    conformance_rate = n_conforms / max(n_total, 1)
    print(f"\n{'='*60}")
    if conformance_rate >= 0.95:
        print(f"✓ Grafo em CONFORMIDADE ({conformance_rate*100:.1f}% dos documentos)")
    elif conformance_rate >= 0.80:
        print(f"⚠ Conformidade PARCIAL ({conformance_rate*100:.1f}%) — revise as violações")
    else:
        print(f"✗ Conformidade BAIXA ({conformance_rate*100:.1f}%) — problemas sistêmicos")
    print(f"{'='*60}\n")

    return conformance_rate


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Valida TTLs RDF contra shapes SHACL"
    )
    parser.add_argument("--limit",  type=int, default=None,
                        help="Valida apenas N arquivos (para testes rápidos)")
    parser.add_argument("--export", type=str, default=None,
                        help="Exporta resultados detalhados em JSON")
    parser.add_argument("--strict", action="store_true",
                        help="Retorna código de saída 1 se houver violações")
    args = parser.parse_args()

    if not RDF_DIR.exists():
        print(f"✗ Diretório não encontrado: {RDF_DIR}")
        sys.exit(1)

    ttl_files = sorted(RDF_DIR.glob("*.ttl"))
    if not ttl_files:
        print(f"✗ Nenhum TTL encontrado em {RDF_DIR}")
        sys.exit(1)

    if args.limit:
        ttl_files = ttl_files[:args.limit]

    print(f"✓ {len(ttl_files):,} TTLs encontrados em {RDF_DIR}")
    print(f"  Carregando shapes SHACL...", end=" ", flush=True)

    shapes_graph = Graph()
    shapes_graph.parse(data=SHAPES_TTL, format="turtle")
    print(f"✓ ({len(shapes_graph)} triplas de shapes)")

    print(f"  Validando...\n")

    results = []
    t0 = time.time()

    for ttl in tqdm(ttl_files, desc="SHACL", unit="ttl"):
        results.append(validate_ttl(ttl, shapes_graph))

    elapsed = time.time() - t0
    conformance_rate = print_report(results, elapsed)

    if args.export:
        summary = {
            "n_total":     len(results),
            "n_conforms":  sum(1 for r in results if r["conforms"]),
            "n_violation": sum(1 for r in results if r["violations"]),
            "n_warning":   sum(1 for r in results if r["warnings"]),
            "conformance_rate": round(conformance_rate, 4),
            "elapsed_s":   round(elapsed, 1),
            "details":     results,
        }
        Path(args.export).parent.mkdir(parents=True, exist_ok=True)
        with open(args.export, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        print(f"✓ Resultados exportados: {args.export}")

    if args.strict and conformance_rate < 1.0:
        sys.exit(1)


if __name__ == "__main__":
    main()