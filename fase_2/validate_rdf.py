#!/usr/bin/env python3
# validate_rdf.py — audita TTLs e detecta campos perdidos vs. manifest
#
# Uso:
#   python validate_rdf.py                        # audita, não modifica nada
#   python validate_rdf.py --patch                # corrige TTLs in-place
#   python validate_rdf.py --patch --dry-run      # simula correção sem salvar
#   python validate_rdf.py --manifest caminho.jsonl
#
# O script busca o manifest.jsonl automaticamente nas localizações mais comuns.
# Falha com erro claro se não encontrar — nunca continua silenciosamente.

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, RDF, XSD

# ── Namespaces ────────────────────────────────────────────────────────────────
FABIO  = Namespace("http://purl.org/spar/fabio/")
BIBO   = Namespace("http://purl.org/ontology/bibo/")
SCHEMA = Namespace("http://schema.org/")
BASE   = Namespace("http://pantheon.ufrj.br/resource/")

# ── Localização dos arquivos ──────────────────────────────────────────────────
RDF_DIR = "data/rdf"

# Caminhos candidatos para o manifest (ordem de prioridade)
MANIFEST_CANDIDATES = [
    "data/manifest.jsonl",           # manifest copiado para a fase 2
    "../fase_1/data/manifest.jsonl", # layout original por fase
    "../../fase_1/data/manifest.jsonl",
    "../data/manifest.jsonl",
    "manifest.jsonl",
]


# ── Campos obrigatórios e opcionais ──────────────────────────────────────────
# Cada campo é: (predicado_rdf, campo_no_manifest, obrigatorio)
FIELD_SPEC = [
    (DCTERMS.title,    "title",    True),
    (DCTERMS.creator,  "creators", True),   # lista
    (DCTERMS.date,     "date",     True),
    (DCTERMS.subject,  "subjects", True),   # lista — era 0% de cobertura
    (DCTERMS.language, "language", False),
    (SCHEMA.url,       "handle_url", False),
]

# Mapeamento de tipos
TYPE_MAP = {
    "tese":        FABIO["DoctoralThesis"],
    "doutorado":   FABIO["DoctoralThesis"],
    "doctoral":    FABIO["DoctoralThesis"],
    "dissertação": FABIO["MastersThesis"],
    "mestrado":    FABIO["MastersThesis"],
    "masters":     FABIO["MastersThesis"],
}


def find_manifest(explicit_path: str | None) -> str:
    """Localiza o manifest.jsonl. Aborta se não encontrar."""
    candidates = ([explicit_path] if explicit_path else []) + MANIFEST_CANDIDATES
    for path in candidates:
        if path and os.path.exists(path):
            return path

    print("\nERRO FATAL: manifest.jsonl não encontrado.")
    print("Locais procurados:")
    for c in candidates:
        print(f"  {c}")
    print("\nSoluções:")
    print("  1. Copie o manifest para a pasta atual:  cp ../fase_1/data/manifest.jsonl data/")
    print("  2. Ou use --manifest /caminho/completo/manifest.jsonl")
    sys.exit(1)


def load_manifest(path: str) -> dict[str, dict]:
    records = {}
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                h = r.get("handle")
                if h:
                    records[h] = r
            except json.JSONDecodeError as e:
                print(f"  AVISO: linha {i} inválida no manifest: {e}")
    return records


def get_doc_type(tipos: list[str]) -> URIRef:
    for t in tipos:
        t_lower = t.lower()
        for key, uri in TYPE_MAP.items():
            if key in t_lower:
                return uri
    return FABIO["MastersThesis"]   # fallback (mas será reportado como aviso)


def parse_date(raw: str) -> tuple[str, URIRef]:
    """Extrai date limpa e datatype correto."""
    if not raw:
        return "", XSD.gYear
    # Remove timezone e hora: '2017-06-06T18:51:42Z' → '2017-06-06'
    clean = raw[:10].strip()
    if len(clean) == 10 and clean[4] == "-" and clean[7] == "-":
        return clean, XSD.date
    # Só ano
    year = clean[:4]
    if year.isdigit():
        return year, XSD.gYear
    return "", XSD.gYear


def audit_ttl(ttl_path: str, manifest_record: dict) -> dict:
    """
    Lê um TTL e compara com o manifest.
    Retorna dict com problemas encontrados e valores ausentes.
    """
    handle = Path(ttl_path).stem.replace("_", "/", 1)
    result = {
        "handle":   handle,
        "ttl_path": ttl_path,
        "problems": [],
        "missing":  {},   # campo → valor que deveria ter
        "wrong":    {},   # campo → (atual, correto)
    }

    try:
        g = Graph()
        g.parse(ttl_path, format="turtle")
    except Exception as e:
        result["problems"].append(f"parse_error: {e}")
        return result

    # URI do documento principal
    doc_uri = BASE[Path(ttl_path).stem]

    # ── Checa tipo do documento ───────────────────────────────────────────────
    tipos_manifest = manifest_record.get("types", [])
    expected_type  = get_doc_type(tipos_manifest)
    actual_types   = set(g.objects(doc_uri, RDF.type))

    if expected_type not in actual_types:
        result["wrong"]["doc_type"] = (
            [str(t).split("/")[-1] for t in actual_types if "fabio" in str(t)],
            str(expected_type).split("/")[-1],
        )
        result["missing"]["doc_type"] = expected_type

    # ── Checa se tipo fallback foi usado sem manifest ─────────────────────────
    if not tipos_manifest:
        result["problems"].append("manifest_empty: meta não carregado no momento da conversão")

    # ── Checa campos simples e de lista ──────────────────────────────────────
    for pred, mfield, obrigatorio in FIELD_SPEC:
        mval = manifest_record.get(mfield)
        if not mval:
            continue  # manifest também não tem, ok

        existing = list(g.objects(doc_uri, pred))

        if isinstance(mval, list):
            # Campo de lista (creators, subjects)
            existing_strs = {str(v) for v in existing}
            missing_vals  = [v for v in mval if v and v not in existing_strs]
            if missing_vals and obrigatorio:
                result["missing"][mfield] = missing_vals
                result["problems"].append(f"missing_{mfield}: {len(missing_vals)} valores ausentes")
        else:
            # Campo simples
            if not existing:
                result["missing"][mfield] = mval
                if obrigatorio:
                    result["problems"].append(f"missing_{mfield}")

    return result


def patch_ttl(ttl_path: str, manifest_record: dict, audit: dict,
              dry_run: bool = False) -> int:
    """
    Adiciona triplas faltantes ao TTL.
    Retorna número de triplas adicionadas.
    """
    if not audit["missing"] and not audit["wrong"]:
        return 0

    g = Graph()
    g.parse(ttl_path, format="turtle")

    # Preserva prefixos originais
    for prefix, ns in [
        ("doco",    "http://purl.org/spar/doco/"),
        ("deo",     "http://purl.org/spar/deo/"),
        ("c4o",     "http://purl.org/spar/c4o/"),
        ("fabio",   "http://purl.org/spar/fabio/"),
        ("po",      "http://www.essepuntato.it/2008/12/pattern#"),
        ("bibo",    "http://purl.org/ontology/bibo/"),
        ("schema",  "http://schema.org/"),
        ("dcterms", "http://purl.org/dc/terms/"),
        ("base",    "http://pantheon.ufrj.br/resource/"),
    ]:
        g.bind(prefix, Namespace(ns))

    doc_uri   = BASE[Path(ttl_path).stem]
    added     = 0
    meta      = manifest_record

    # ── Corrige tipo do documento ─────────────────────────────────────────────
    if "doc_type" in audit["wrong"] or "doc_type" in audit["missing"]:
        tipos     = meta.get("types", [])
        new_type  = get_doc_type(tipos)
        # Remove tipos fabio errados
        for t in list(g.objects(doc_uri, RDF.type)):
            if "fabio" in str(t) and "Work" not in str(t):
                g.remove((doc_uri, RDF.type, t))
        g.add((doc_uri, RDF.type, new_type))
        g.add((doc_uri, RDF.type, FABIO["Work"]))
        added += 1

    # ── Título do manifest (fallback quando GROBID rejeitou o título do TEI) ────
    # O tei_to_doco.py rejeita títulos que parecem TOC/lixo de OCR, mas nesses
    # casos o título real está no manifest. O manifest é sempre a fonte autoritativa.
    if "title" in audit["missing"]:
        title = meta.get("title", "")
        if title and not list(g.objects(doc_uri, DCTERMS.title)):
            g.add((doc_uri, DCTERMS.title, Literal(title)))
            added += 1

    # ── Adiciona subjects (eram 0% de cobertura) ──────────────────────────────
    if "subjects" in audit["missing"]:
        existing = {str(v) for v in g.objects(doc_uri, DCTERMS.subject)}
        for subj in meta.get("subjects", []):
            if subj and subj not in existing:
                g.add((doc_uri, DCTERMS.subject, Literal(subj)))
                added += 1

    # ── Creators: substitui pelo manifest quando ele tem dados ───────────────
    # Razão: GROBID extrai lixo do índice/sumário como autores.
    # O manifest (Dublin Core OAI-PMH) é a fonte autoritativa.
    manifest_creators = [c for c in meta.get("creators", []) if c]
    if manifest_creators and "creators" in audit["missing"]:
        # Remove TODOS os creators existentes (podem ser lixo do TEI)
        for existing_creator in list(g.objects(doc_uri, DCTERMS.creator)):
            g.remove((doc_uri, DCTERMS.creator, existing_creator))
        # Adiciona apenas os do manifest
        for creator in manifest_creators:
            g.add((doc_uri, DCTERMS.creator, Literal(creator)))
            added += 1

    # ── Adiciona/corrige date ─────────────────────────────────────────────────
    if "date" in audit["missing"]:
        raw = meta.get("date", "")
        clean, dtype = parse_date(raw)
        if clean:
            g.add((doc_uri, DCTERMS.date, Literal(clean, datatype=dtype)))
            added += 1

    # ── Adiciona language ─────────────────────────────────────────────────────
    if "language" in audit["missing"]:
        lang = meta.get("language", "")
        if lang:
            g.add((doc_uri, DCTERMS.language, Literal(lang)))
            added += 1

    # ── Adiciona handle_url ───────────────────────────────────────────────────
    if "handle_url" in audit["missing"]:
        url = meta.get("handle_url", "")
        if url:
            g.add((doc_uri, SCHEMA.url, URIRef(url)))
            added += 1

    if not dry_run and added > 0:
        g.serialize(destination=ttl_path, format="turtle")

    return added


def main():
    parser = argparse.ArgumentParser(
        description="Audita e corrige TTLs DoCO contra o manifest OAI-PMH",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python validate_rdf.py                       # só audita, mostra problemas
  python validate_rdf.py --patch --dry-run     # simula correção (não salva)
  python validate_rdf.py --patch               # corrige TTLs in-place
  python validate_rdf.py --handle 11422/2286   # audita um handle específico
  python validate_rdf.py --patch --only-missing subjects  # corrige só subjects
        """,
    )
    parser.add_argument("--patch",        action="store_true",
                        help="Corrige os TTLs com dados do manifest")
    parser.add_argument("--dry-run",      action="store_true",
                        help="Simula sem salvar (requer --patch)")
    parser.add_argument("--manifest",     type=str, default=None,
                        help="Caminho explícito para o manifest.jsonl")
    parser.add_argument("--rdf-dir",      type=str, default=RDF_DIR,
                        help=f"Diretório dos TTLs (padrão: {RDF_DIR})")
    parser.add_argument("--handle",       type=str, default=None,
                        help="Audita só um handle específico (ex: 11422/2286)")
    parser.add_argument("--only-missing", type=str, default=None,
                        help="No modo --patch, corrige só este campo (ex: subjects)")
    parser.add_argument("--show-ok",      action="store_true",
                        help="Mostra também os TTLs sem problemas")
    args = parser.parse_args()

    # ── Localiza e carrega manifest ───────────────────────────────────────────
    manifest_path = find_manifest(args.manifest)
    print(f"Carregando manifest: {manifest_path}")
    manifest = load_manifest(manifest_path)
    print(f"  {len(manifest)} registros carregados\n")

    # ── Coleta TTLs a auditar ─────────────────────────────────────────────────
    rdf_dir = Path(args.rdf_dir)
    if not rdf_dir.exists():
        print(f"ERRO: diretório {rdf_dir} não existe")
        sys.exit(1)

    ttl_files = sorted(rdf_dir.glob("*.ttl"))
    if args.handle:
        safe = args.handle.replace("/", "_")
        ttl_files = [f for f in ttl_files if f.stem == safe]
        if not ttl_files:
            print(f"ERRO: TTL para handle {args.handle} não encontrado em {rdf_dir}")
            sys.exit(1)

    print(f"Auditando {len(ttl_files)} TTLs em {rdf_dir}/\n")

    # ── Audita ────────────────────────────────────────────────────────────────
    all_problems: Counter  = Counter()
    docs_with_problems     = []
    docs_ok                = []
    docs_not_in_manifest   = []

    for ttl_path in ttl_files:
        handle = ttl_path.stem.replace("_", "/", 1)
        meta   = manifest.get(handle)

        if meta is None:
            docs_not_in_manifest.append(handle)
            continue

        audit = audit_ttl(str(ttl_path), meta)

        if audit["problems"]:
            docs_with_problems.append((ttl_path, meta, audit))
            for p in audit["problems"]:
                all_problems[p.split(":")[0]] += 1
        else:
            docs_ok.append(handle)

    # ── Relatório ─────────────────────────────────────────────────────────────
    total = len(ttl_files)
    n_ok  = len(docs_ok)
    n_err = len(docs_with_problems)
    n_nm  = len(docs_not_in_manifest)

    print("=" * 65)
    print("RESULTADO DA AUDITORIA")
    print(f"  Total TTLs        : {total}")
    print(f"  ✓ Sem problemas   : {n_ok}  ({100*n_ok//max(total,1)}%)")
    print(f"  ✗ Com problemas   : {n_err} ({100*n_err//max(total,1)}%)")
    print(f"  ? Não no manifest : {n_nm}")
    print()

    if all_problems:
        print("Problemas encontrados (por tipo):")
        for prob, count in all_problems.most_common():
            print(f"  {count:5d}x  {prob}")
        print()

    # Detalha os primeiros 20 com problemas
    show_n = 20 if not args.handle else len(docs_with_problems)
    if docs_with_problems:
        print(f"Detalhes (primeiros {min(show_n, len(docs_with_problems))}):")
        header = f"  {'Handle':<22} {'Problemas'}"
        print(header)
        print("  " + "-" * 60)
        for ttl_path, meta, audit in docs_with_problems[:show_n]:
            handle = Path(ttl_path).stem.replace("_", "/", 1)
            short  = [p.split(":")[0] for p in audit["problems"]]
            print(f"  {handle:<22} {', '.join(short)}")
            if args.handle:
                # Detalhe completo para handle específico
                for field, vals in audit["missing"].items():
                    print(f"    MISSING {field}: {vals if not isinstance(vals, list) else vals[:3]}")
                for field, (atual, correto) in audit["wrong"].items():
                    print(f"    WRONG   {field}: atual={atual} → correto={correto}")
        print()

    if docs_not_in_manifest and len(docs_not_in_manifest) <= 10:
        print(f"TTLs não encontrados no manifest ({len(docs_not_in_manifest)}):")
        for h in docs_not_in_manifest[:10]:
            print(f"  {h}")
        print()

    # ── Patch ─────────────────────────────────────────────────────────────────
    if args.patch:
        mode = "SIMULANDO" if args.dry_run else "CORRIGINDO"
        print(f"{'='*65}")
        print(f"{mode} {len(docs_with_problems)} TTLs...")
        print()

        total_added  = 0
        patched_docs = 0

        for ttl_path, meta, audit in docs_with_problems:
            # Filtra por campo se --only-missing foi passado
            if args.only_missing:
                filtered = {
                    "missing": {k: v for k, v in audit["missing"].items()
                                if k == args.only_missing},
                    "wrong":   audit["wrong"],
                }
                if not filtered["missing"]:
                    continue
                audit_to_apply = filtered
            else:
                audit_to_apply = audit

            added = patch_ttl(
                str(ttl_path), meta, audit_to_apply,
                dry_run=args.dry_run,
            )
            if added > 0:
                patched_docs += 1
                total_added  += added

        action = "seriam adicionadas" if args.dry_run else "adicionadas"
        print(f"  Documentos corrigidos : {patched_docs}")
        print(f"  Triplas {action}: {total_added}")
        if args.dry_run:
            print("\n  [DRY-RUN] Nenhum arquivo foi modificado.")
            print("  Execute sem --dry-run para aplicar as correções.")
        else:
            print(f"\n  ✓ TTLs atualizados em {args.rdf_dir}/")
            print("  Execute este script novamente sem --patch para confirmar.")
    else:
        if docs_with_problems:
            print("Para corrigir os TTLs, execute:")
            print(f"  python {sys.argv[0]} --patch --dry-run   # simula primeiro")
            print(f"  python {sys.argv[0]} --patch             # aplica")


if __name__ == "__main__":
    main()