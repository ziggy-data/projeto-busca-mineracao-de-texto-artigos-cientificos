#!/usr/bin/env python3
# enrich_graph.py — converte saídas do LLM em triplas RDF e envia ao Fuseki
#
# Uso:
#   python enrich_graph.py              # enriquece todos os docs analisados
#   python enrich_graph.py --dry-run    # mostra triplas sem enviar ao Fuseki

import argparse
import json
import os
from pathlib import Path

import requests
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, RDF, XSD
from tqdm import tqdm

# ── Namespaces ────────────────────────────────────────────────────────────────
BASE    = Namespace("http://pantheon.ufrj.br/resource/")
DOCO    = Namespace("http://purl.org/spar/doco/")
DEO     = Namespace("http://purl.org/spar/deo/")
C4O     = Namespace("http://purl.org/spar/c4o/")
FABIO   = Namespace("http://purl.org/spar/fabio/")
PO      = Namespace("http://www.essepuntato.it/2008/12/pattern#")

# Namespace customizado para discurso científico
DISCOURSE = Namespace("http://pantheon.ufrj.br/ontology/discourse#")

# ── Configuração ──────────────────────────────────────────────────────────────
DISCOURSE_DIR = "data/discourse"
ENRICHED_DIR  = "data/enriched"
FUSEKI_URL    = "http://localhost:3030"
DATASET       = "pantheon"
FUSEKI_USER   = "admin"
FUSEKI_PASS   = "pantheon123"


def handle_to_uri(handle: str) -> URIRef:
    return BASE[handle.replace("/", "_")]


def build_discourse_graph(doc: dict) -> Graph:
    """
    Converte o JSON de análise de discurso em triplas RDF.

    Estrutura gerada:
      :doc  discourse:hasClaim       :claim_0
            discourse:hasContribution :contrib_0
            discourse:hasLimitation  :limit_0
            discourse:hasFutureWork  :fw_0

      :claim_0  a discourse:ScientificClaim
                discourse:inSection  :sec_N
                c4o:hasContent "..."
                discourse:confidence "high"

      :sec_N    a deo:Conclusion (ou Results, etc.)
    """
    g = Graph()
    g.bind("discourse", DISCOURSE)
    g.bind("doco",  DOCO)
    g.bind("deo",   DEO)
    g.bind("c4o",   C4O)
    g.bind("fabio", FABIO)
    g.bind("base",  BASE)
    g.bind("dcterms", DCTERMS)

    handle  = doc["handle"]
    doc_uri = handle_to_uri(handle)
    safe    = handle.replace("/", "_")

    # Tipo de documento (preservado)
    g.add((doc_uri, RDF.type, DISCOURSE["AnalyzedDocument"]))

    for i, sec in enumerate(doc.get("sections", [])):
        sec_head = sec.get("section_head", "")
        rhet     = sec.get("rhetorical_type", "mixed")
        sec_uri  = BASE[f"{safe}_disc_sec_{i}"]

        # Mapeia tipo retórico para DEO
        rhet_map = {
            "conclusion":   DEO["Conclusion"],
            "results":      DEO["Results"],
            "discussion":   DEO["Discussion"],
            "contribution": DEO["Background"],
            "mixed":        DOCO["Section"],
        }
        g.add((sec_uri, RDF.type, rhet_map.get(rhet, DOCO["Section"])))
        if sec_head:
            g.add((sec_uri, DCTERMS.title, Literal(sec_head)))
        g.add((doc_uri, DISCOURSE["hasAnalyzedSection"], sec_uri))

        # Claims
        for j, claim in enumerate(sec.get("claims", [])):
            if not claim or len(claim) < 10:
                continue
            claim_uri = BASE[f"{safe}_disc_sec_{i}_claim_{j}"]
            g.add((claim_uri, RDF.type,              DISCOURSE["ScientificClaim"]))
            g.add((claim_uri, C4O["hasContent"],     Literal(claim)))
            g.add((claim_uri, DISCOURSE["inSection"], sec_uri))
            g.add((sec_uri,   DISCOURSE["hasClaim"],  claim_uri))
            g.add((doc_uri,   DISCOURSE["hasClaim"],  claim_uri))

        # Contribuições
        for j, contrib in enumerate(sec.get("contributions", [])):
            if not contrib or len(contrib) < 10:
                continue
            contrib_uri = BASE[f"{safe}_disc_sec_{i}_contrib_{j}"]
            g.add((contrib_uri, RDF.type,                  DISCOURSE["Contribution"]))
            g.add((contrib_uri, C4O["hasContent"],         Literal(contrib)))
            g.add((contrib_uri, DISCOURSE["inSection"],    sec_uri))
            g.add((sec_uri,     DISCOURSE["hasContribution"], contrib_uri))
            g.add((doc_uri,     DISCOURSE["hasContribution"], contrib_uri))

        # Limitações
        for j, limit in enumerate(sec.get("limitations", [])):
            if not limit or len(limit) < 10:
                continue
            limit_uri = BASE[f"{safe}_disc_sec_{i}_limit_{j}"]
            g.add((limit_uri, RDF.type,                 DISCOURSE["Limitation"]))
            g.add((limit_uri, C4O["hasContent"],        Literal(limit)))
            g.add((limit_uri, DISCOURSE["inSection"],   sec_uri))
            g.add((sec_uri,   DISCOURSE["hasLimitation"], limit_uri))
            g.add((doc_uri,   DISCOURSE["hasLimitation"], limit_uri))

        # Trabalho futuro
        for j, fw in enumerate(sec.get("future_work", [])):
            if not fw or len(fw) < 10:
                continue
            fw_uri = BASE[f"{safe}_disc_sec_{i}_fw_{j}"]
            g.add((fw_uri, RDF.type,                  DISCOURSE["FutureWork"]))
            g.add((fw_uri, C4O["hasContent"],         Literal(fw)))
            g.add((fw_uri, DISCOURSE["inSection"],    sec_uri))
            g.add((doc_uri, DISCOURSE["hasFutureWork"], fw_uri))

        # Keywords inferidas pelo LLM
        for kw in sec.get("keywords_inferred", []):
            if kw:
                g.add((doc_uri, DISCOURSE["inferredKeyword"], Literal(kw)))

    return g


def upload_to_fuseki(graph: Graph, handle: str) -> bool:
    """Envia o grafo como named graph para o Fuseki."""
    graph_uri = f"urn:corpus:discourse:{handle.replace('/', '_')}"
    ttl_data  = graph.serialize(format="turtle")

    try:
        # Envia para o default graph (sem parâmetro 'graph')
        r = requests.post(
            f"{FUSEKI_URL}/{DATASET}/data",
            data=ttl_data.encode("utf-8"),
            headers={"Content-Type": "text/turtle"},
            auth=(FUSEKI_USER, FUSEKI_PASS),
            timeout=30,
        )
        return r.status_code in (200, 201, 204)
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser(description="Enriquece o grafo com análise de discurso")
    parser.add_argument("--dry-run", action="store_true",
                        help="Mostra triplas sem enviar ao Fuseki")
    args = parser.parse_args()

    os.makedirs(ENRICHED_DIR, exist_ok=True)

    # Verifica Fuseki (se não for dry-run)
    if not args.dry_run:
        try:
            r = requests.get(f"{FUSEKI_URL}/$/ping",
                             auth=(FUSEKI_USER, FUSEKI_PASS), timeout=5)
            assert r.status_code == 200
            print(f"✓ Fuseki em {FUSEKI_URL}")
        except Exception:
            print(f"✗ Fuseki não acessível. Execute: python fuseki_setup.py")
            return

    disc_files = sorted(Path(DISCOURSE_DIR).glob("*.json"))
    print(f"Documentos analisados : {len(disc_files)}")

    if not disc_files:
        print("Nenhum arquivo de discurso encontrado.")
        print("Execute primeiro: python discourse_analysis.py")
        return

    stats = {"ok": 0, "empty": 0, "error": 0}
    total_triples = 0

    for disc_file in tqdm(disc_files, desc="Enriquecendo grafo", unit="doc"):
        with open(disc_file, encoding="utf-8") as f:
            doc = json.load(f)

        if doc.get("status") != "ok" or not doc.get("sections"):
            stats["empty"] += 1
            continue

        g = build_discourse_graph(doc)
        total_triples += len(g)

        # Salva TTL local
        out_path = os.path.join(ENRICHED_DIR, disc_file.stem + "_discourse.ttl")
        g.serialize(destination=out_path, format="turtle")

        if args.dry_run:
            print(f"\n── {doc['handle']} ({len(g)} triplas)")
            # Mostra amostra de claims
            for sec in doc.get("sections", [])[:1]:
                print(f"  Seção: {sec.get('section_head', '')}")
                for c in sec.get("claims", [])[:2]:
                    print(f"  → Claim: {c[:100]}")
            stats["ok"] += 1
        else:
            ok = upload_to_fuseki(g, doc["handle"])
            stats["ok" if ok else "error"] += 1

    print(f"\n{'='*50}")
    print(f"Enriquecimento concluído")
    print(f"  ✓ OK        : {stats['ok']}")
    print(f"  ⚠ Sem dados : {stats['empty']}")
    print(f"  ✗ Erros     : {stats['error']}")
    print(f"  Triplas     : {total_triples:,}")
    if not args.dry_run:
        print(f"\nTTLs em: {ENRICHED_DIR}/")
        print(f"Próximo: python sparql_queries.py")


if __name__ == "__main__":
    main()