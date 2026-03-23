#!/usr/bin/env python3
# quality_gate.py — pipeline de validação em três estágios
#
# ESTÁGIOS:
#   stage1  — PDFs (pré-GROBID):   detecta scans ruins, tamanho, magia
#   stage2  — TEI XMLs (pós-GROBID): detecta corpo vazio, OCR-lixo, metadados falsos
#   stage3  — TTLs RDF (pós-conversão): valida integridade vs manifest e audita campos
#
# USO:
#   python quality_gate.py stage1                    # só PDFs
#   python quality_gate.py stage2                    # só TEIs
#   python quality_gate.py stage3                    # só TTLs (auditoria)
#   python quality_gate.py stage3 --patch            # audita E corrige TTLs
#   python quality_gate.py stage3 --patch --dry-run  # simula sem salvar
#   python quality_gate.py all                       # todos os estágios
#   python quality_gate.py stage3 --handle 11422/2286
#   python quality_gate.py stage2 --apply            # move TEIs ruins para rejected/
#
# FILOSOFIA DE CONFIANÇA (importante):
#   GROBID é confiável para: estrutura (seções, parágrafos, body, referências)
#   GROBID NÃO é confiável para: metadados (título, autores, data, subjects)
#   O manifest OAI-PMH é a fonte autoritativa para metadados bibliográficos.
#   Portanto, no stage3 os campos do manifest SEMPRE prevalecem sobre o GROBID.

import argparse
import json
import os
import re
import shutil
import sys
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, RDF, XSD
from tqdm import tqdm

# ── Namespaces ────────────────────────────────────────────────────────────────
FABIO  = Namespace("http://purl.org/spar/fabio/")
DOCO   = Namespace("http://purl.org/spar/doco/")
DEO    = Namespace("http://purl.org/spar/deo/")
BIBO   = Namespace("http://purl.org/ontology/bibo/")
SCHEMA = Namespace("http://schema.org/")
C4O    = Namespace("http://purl.org/spar/c4o/")
PO     = Namespace("http://www.essepuntato.it/2008/12/pattern#")
BASE   = Namespace("http://pantheon.ufrj.br/resource/")
TEI_NS = "http://www.tei-c.org/ns/1.0"

# ── Caminhos padrão ───────────────────────────────────────────────────────────
PDF_DIR     = "../fase_1/data/pdfs"
TEI_DIR     = "data/tei"
TEI_REJ_DIR = "data/tei_rejected"
RDF_DIR     = "data/rdf"
REPORT_DIR  = "data/quality_reports"

MANIFEST_CANDIDATES = [
    "data/manifest.jsonl",
    "../fase_1/data/manifest.jsonl",
    "../../fase_1/data/manifest.jsonl",
    "../data/manifest.jsonl",
    "manifest.jsonl",
]

# ── Thresholds ────────────────────────────────────────────────────────────────
PDF_MIN_SIZE_KB    = 10
PDF_MAX_SIZE_MB    = 80
PDF_MAGIC          = b"%PDF-"
TEI_MIN_BODY_CHARS = 800
TEI_MAX_GARBAGE    = 0.35
TEI_MIN_SECTIONS   = 2
TEI_MAX_TOC_RATIO  = 0.5
TTL_MIN_TRIPLES    = 50

# ── Padrões ───────────────────────────────────────────────────────────────────
TOC_TITLE_PATTERNS = [
    r"•{3,}", r"-{5,}", r"\.{5,}",
    r"^\s*cap[íi]tulo\s+[IVX\d]",
    r"\d{2,}\s*$",
]
TOC_AUTHOR_PATTERNS = [
    r"•{2,}", r"-{3,}",
    r"^(cap[íi]tulo|seção|parte|anexo|ap[êe]ndice)\s",
    r"\d{2,}$", r"^\W+$",
    r"^[A-Z][a-z]*(\s+[A-Z][a-z]*){3,}",
]
TYPE_MAP = {
    "tese": "DoctoralThesis", "doutorado": "DoctoralThesis",
    "doctoral": "DoctoralThesis",
    "dissertação": "MastersThesis", "mestrado": "MastersThesis",
    "masters": "MastersThesis",
}

# Campos a validar no stage3:
# (predicado, campo_manifest, obrigatorio, substituir_pelo_manifest)
# substituir=True → remove o que GROBID colocou e coloca o do manifest
# substituir=False → só adiciona o que está faltando
FIELD_SPEC = [
    (DCTERMS.title,    "title",      True,  False),  # TEI pode ter título bom
    (DCTERMS.creator,  "creators",   True,  True),   # GROBID mente → substitui
    (DCTERMS.date,     "date",       True,  True),   # manifest tem data real → substitui
    (DCTERMS.subject,  "subjects",   True,  False),  # TEI não tem → só adiciona
    (DCTERMS.language, "language",   False, False),
    (SCHEMA.url,       "handle_url", False, False),
]


# ══════════════════════════════════════════════════════════════════════════════
# Utilitários
# ══════════════════════════════════════════════════════════════════════════════

def tei_text(elem) -> str:
    if elem is None:
        return ""
    return " ".join(elem.itertext()).strip()


def garbage_ratio(text: str) -> float:
    if not text:
        return 1.0
    ok = sum(1 for c in text if c.isalnum() or c.isspace())
    return 1.0 - ok / len(text)


def matches_any(text: str, patterns: list) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def get_doc_type(tipos: list) -> URIRef:
    for t in tipos:
        for key, cls in TYPE_MAP.items():
            if key in t.lower():
                return FABIO[cls]
    return FABIO["MastersThesis"]


def parse_date_clean(raw: str) -> tuple:
    """'2017-06-06T18:51:42Z' → ('2017-06-06', xsd:date)"""
    if not raw:
        return "", XSD.gYear
    clean = raw[:10].strip()
    if len(clean) == 10 and clean[4] == "-" and clean[7] == "-":
        return clean, XSD.date
    year = clean[:4]
    return (year, XSD.gYear) if year.isdigit() else ("", XSD.gYear)


def find_manifest(explicit) -> str:
    candidates = ([explicit] if explicit else []) + MANIFEST_CANDIDATES
    for path in candidates:
        if path and os.path.exists(path):
            return path
    print("\nERRO FATAL: manifest.jsonl não encontrado.")
    print("Locais procurados:")
    for c in candidates:
        print(f"  {c}")
    print("\nSolução: cp ../fase_1/data/manifest.jsonl data/manifest.jsonl")
    sys.exit(1)


def load_manifest(path: str) -> dict:
    records = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                h = r.get("handle")
                if h:
                    records[h] = r
            except json.JSONDecodeError:
                pass
    return records


def save_report(name: str, results: list) -> str:
    os.makedirs(REPORT_DIR, exist_ok=True)
    path = os.path.join(REPORT_DIR, f"{name}.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path


def print_header(title: str):
    print(f"\n{'═'*65}")
    print(f"  {title}")
    print(f"{'═'*65}")


# ══════════════════════════════════════════════════════════════════════════════
# ESTÁGIO 1 — PDFs (pré-GROBID)
# ══════════════════════════════════════════════════════════════════════════════

def check_pdf(pdf_path: str) -> dict:
    """
    Valida PDF antes de enviar ao GROBID.
    Confia no GROBID para extração de estrutura — esta função só garante
    que o arquivo é um PDF válido e provavelmente tem texto extraível.
    """
    path   = Path(pdf_path)
    size_b = path.stat().st_size
    result = {
        "pdf_path": pdf_path,
        "handle":   path.stem.replace("_", "/", 1),
        "size_mb":  round(size_b / 1e6, 2),
        "reject":   False,
        "reasons":  [],
    }

    try:
        with open(pdf_path, "rb") as f:
            magic = f.read(5)
        if magic != PDF_MAGIC:
            result["reject"] = True
            result["reasons"].append(f"invalid_magic: {magic[:5]}")
            return result
    except OSError as e:
        result["reject"] = True
        result["reasons"].append(f"read_error: {e}")
        return result

    size_kb = size_b / 1024
    size_mb = size_b / 1e6

    if size_kb < PDF_MIN_SIZE_KB:
        result["reject"] = True
        result["reasons"].append(f"too_small: {size_kb:.1f}KB")

    if size_mb > PDF_MAX_SIZE_MB:
        result["reject"] = True
        result["reasons"].append(f"too_large: {size_mb:.0f}MB")

    # Heurística de densidade de texto nos primeiros 50KB
    try:
        with open(pdf_path, "rb") as f:
            sample = f.read(51200)
        readable = sum(1 for b in sample if 32 <= b < 127)
        density  = readable / len(sample) if sample else 0
        result["text_density"] = round(density, 3)
        if density < 0.05:
            result["reject"] = True
            result["reasons"].append(f"likely_scan: density={density:.1%}")
    except OSError:
        result["text_density"] = None

    return result


def run_stage1(pdf_dir: str, apply: bool) -> list:
    print_header("ESTÁGIO 1 — Validação de PDFs (pré-GROBID)")

    pdf_files = sorted(Path(pdf_dir).glob("*.pdf"))
    if not pdf_files:
        print(f"\n  Nenhum PDF encontrado em: {pdf_dir}")
        return []

    print(f"\n  Analisando {len(pdf_files)} PDFs...")

    results  = []
    rejected = []

    for pdf in tqdm(pdf_files, desc="PDFs", unit="pdf"):
        r = check_pdf(str(pdf))
        results.append(r)
        if r["reject"]:
            rejected.append(r)

    ok = len(results) - len(rejected)
    print(f"\n  Total : {len(results)}")
    print(f"  ✓ OK  : {ok} ({100*ok//max(len(results),1)}%)")
    print(f"  ✗ Rej.: {len(rejected)} ({100*len(rejected)//max(len(results),1)}%)")

    counter: Counter = Counter()
    for r in rejected:
        for reason in r["reasons"]:
            counter[reason.split(":")[0]] += 1
    if counter:
        print("\n  Motivos:")
        for k, v in counter.most_common():
            print(f"    {v:4d}x  {k}")

    if rejected[:5]:
        print("\n  Exemplos:")
        for r in rejected[:5]:
            print(f"    {Path(r['pdf_path']).name:<35} {r['reasons'][0]}")

    if apply and rejected:
        rej_dir = str(Path(pdf_dir).parent / "pdfs_rejected")
        os.makedirs(rej_dir, exist_ok=True)
        moved = sum(
            1 for r in rejected
            if os.path.exists(r["pdf_path"]) and
               not shutil.move(r["pdf_path"],
                               os.path.join(rej_dir, Path(r["pdf_path"]).name)) or True
        )
        print(f"\n  {len(rejected)} PDFs movidos para {rej_dir}/")

    print(f"\n  Relatório: {save_report('stage1_pdfs', results)}")
    return results


# ══════════════════════════════════════════════════════════════════════════════
# ESTÁGIO 2 — TEIs (pós-GROBID)
# ══════════════════════════════════════════════════════════════════════════════

def check_tei(tei_path: str) -> dict:
    """
    Valida TEI produzido pelo GROBID.

    O que o GROBID faz bem (e não verificamos aqui):
      - Extração de body/seções/parágrafos quando o PDF tem texto
      - Extração de referências em artigos modernos

    O que o GROBID faz mal em scans antigos (e detectamos aqui):
      - Lê sumário como campo de autores → grobid_authors_unreliable (aviso, não rejeita)
      - Lê página de conteúdos como título → title_is_toc (rejeita)
      - Retorna body quase vazio → body_too_short (rejeita)
      - OCR de baixa qualidade domina → high_garbage (rejeita)

    Nota: erros de subjects/date NÃO são detectados aqui porque
    esses campos vêm do manifest, não do GROBID. Stage 3 verifica isso.
    """
    ns = {"tei": TEI_NS}
    result = {
        "tei_path": tei_path,
        "handle":   Path(tei_path).stem.replace(".tei", "").replace("_", "/", 1),
        "reject":   False,
        "reasons":  [],
        "metrics":  {},
    }

    try:
        tree = ET.parse(tei_path)
        root = tree.getroot()
    except ET.ParseError as e:
        result["reject"] = True
        result["reasons"].append(f"parse_error: {e}")
        return result

    # Título
    title_el = root.find(".//tei:fileDesc/tei:titleStmt/tei:title", ns)
    if title_el is None:
        title_el = root.find(".//tei:titleStmt/tei:title", ns)
    title = tei_text(title_el) if title_el is not None else ""
    if title and matches_any(title, TOC_TITLE_PATTERNS):
        result["reject"] = True
        result["reasons"].append("title_is_toc")

    # Autores extraídos pelo GROBID — aviso, não rejeição
    # O manifest vai corrigir isso no stage 3
    pers_els = root.findall(".//tei:fileDesc//tei:analytic//tei:persName", ns)
    if not pers_els:
        pers_els = root.findall(".//tei:fileDesc//tei:author//tei:persName", ns)
    n_toc = sum(1 for p in pers_els if matches_any(tei_text(p), TOC_AUTHOR_PATTERNS))
    result["metrics"]["n_authors"]   = len(pers_els)
    result["metrics"]["toc_authors"] = n_toc
    if pers_els and (n_toc / len(pers_els)) > TEI_MAX_TOC_RATIO:
        result["reasons"].append(
            f"grobid_authors_unreliable: {n_toc}/{len(pers_els)} parecem TOC "
            f"(será corrigido pelo manifest no stage3)"
        )

    # Body
    body = root.find(".//tei:body", ns)
    if body is None:
        result["reject"] = True
        result["reasons"].append("no_body")
        return result

    body_text = tei_text(body)
    g_ratio   = garbage_ratio(body_text)
    result["metrics"]["body_chars"]    = len(body_text)
    result["metrics"]["garbage_ratio"] = round(g_ratio, 3)

    if len(body_text) < TEI_MIN_BODY_CHARS:
        result["reject"] = True
        result["reasons"].append(f"body_too_short: {len(body_text)}ch")

    if g_ratio > TEI_MAX_GARBAGE:
        result["reject"] = True
        result["reasons"].append(f"high_garbage: {g_ratio:.0%}")

    # Seções com cabeçalho real
    divs = body.findall(".//tei:div", ns)
    good = sum(
        1 for d in divs
        if d.find("tei:head", ns) is not None
        and len(tei_text(d.find("tei:head", ns)).strip()) > 2
        and not matches_any(tei_text(d.find("tei:head", ns)), TOC_TITLE_PATTERNS)
    )
    result["metrics"]["good_sections"]  = good
    result["metrics"]["total_sections"] = len(divs)
    if good < TEI_MIN_SECTIONS:
        result["reject"] = True
        result["reasons"].append(f"few_real_sections: {good}")

    # Referências com OCR-lixo (aviso)
    refs = root.findall(".//tei:listBibl/tei:biblStruct", ns)
    result["metrics"]["n_refs"] = len(refs)
    if refs:
        def _ref_title(r):
            el = r.find(".//tei:title[@level='a']", ns)
            if el is None:
                el = r.find(".//tei:title[@level='m']", ns)
            return tei_text(el)
        ref_titles = [_ref_title(r) for r in refs]
        garbage_refs = sum(1 for t in ref_titles if t and garbage_ratio(t) > 0.3)
        if (garbage_refs / len(refs)) > 0.5:
            result["reasons"].append(
                f"grobid_refs_unreliable: {garbage_refs}/{len(refs)} são OCR-lixo"
            )

    return result


def run_stage2(tei_dir: str, apply: bool) -> list:
    print_header("ESTÁGIO 2 — Validação de TEIs (pós-GROBID)")
    print("\n  Hierarquia de confiança:")
    print("    GROBID confiável para  : body, seções, parágrafos, refs")
    print("    GROBID não confiável   : título (pode ser TOC), autores em scans")
    print("    avisos unreliable      : não rejeitam — manifest corrige no stage3")

    tei_files = sorted(Path(tei_dir).glob("*.tei.xml"))
    if not tei_files:
        print(f"\n  Nenhum TEI encontrado em: {tei_dir}")
        return []

    print(f"\n  Analisando {len(tei_files)} TEIs...")

    results  = []
    rejected = []
    warnings = []

    for tei in tqdm(tei_files, desc="TEIs", unit="tei"):
        r = check_tei(str(tei))
        results.append(r)
        if r["reject"]:
            rejected.append(r)
        elif r["reasons"]:
            warnings.append(r)

    ok = len(results) - len(rejected)
    print(f"\n  Total       : {len(results)}")
    print(f"  ✓ OK        : {ok} ({100*ok//max(len(results),1)}%)")
    print(f"  ✗ Rejeit.   : {len(rejected)} ({100*len(rejected)//max(len(results),1)}%)")
    print(f"  ⚠ Avisos    : {len(warnings)} (não rejeitados — manifest corrige)")

    counter: Counter = Counter()
    for r in rejected:
        for reason in r["reasons"]:
            counter[reason.split(":")[0]] += 1
    if counter:
        print("\n  Motivos de rejeição:")
        for k, v in counter.most_common():
            print(f"    {v:4d}x  {k}")

    chars = [r["metrics"].get("body_chars", 0) for r in results if not r["reject"]]
    if chars:
        print(f"\n  Body chars (aceitos): "
              f"min={min(chars):,} | média={sum(chars)//len(chars):,} | max={max(chars):,}")

    if rejected[:5]:
        print("\n  Exemplos rejeitados:")
        for r in rejected[:5]:
            m = r["metrics"]
            print(f"    {Path(r['tei_path']).name:<38} "
                  f"body={m.get('body_chars',0):6,}ch "
                  f"garbage={m.get('garbage_ratio',0):.0%}")

    if apply and rejected:
        os.makedirs(TEI_REJ_DIR, exist_ok=True)
        moved = 0
        for r in rejected:
            src = r["tei_path"]
            if os.path.exists(src):
                shutil.move(src, os.path.join(TEI_REJ_DIR, Path(src).name))
                moved += 1
        print(f"\n  {moved} TEIs movidos para {TEI_REJ_DIR}/")

    print(f"\n  Relatório: {save_report('stage2_teis', results)}")
    return results


# ══════════════════════════════════════════════════════════════════════════════
# ESTÁGIO 3 — TTLs RDF (pós-conversão)
# ══════════════════════════════════════════════════════════════════════════════

def check_ttl(ttl_path: str, manifest_record: dict) -> dict:
    """
    Audita TTL RDF contra o manifest OAI-PMH.

    Hierarquia de confiança aplicada aqui:
      manifest → autoridade em: tipo, date, creators, subjects, language, url
      GROBID/TEI → autoridade em: body, seções, parágrafos, referências estruturadas

    Verificações:
      1. Tipo correto (Tese vs Dissertação — vem do manifest)
      2. subjects presentes (GROBID não extrai — vem SEMPRE do manifest)
      3. date presente e correta (manifest tem a data do OAI)
      4. creators corretos (GROBID mente em scans)
      5. title presente (TEI ou manifest)
      6. Mínimo de triplas (TTL não é vazio)
      7. Pelo menos uma seção retórica DEO identificada
      8. Abstract presente
    """
    result = {
        "handle":   Path(ttl_path).stem.replace("_", "/", 1),
        "ttl_path": ttl_path,
        "problems": [],
        "missing":  {},
        "wrong":    {},
        "metrics":  {},
    }

    try:
        g = Graph()
        g.parse(ttl_path, format="turtle")
    except Exception as e:
        result["problems"].append(f"parse_error: {e}")
        return result

    doc_uri = BASE[Path(ttl_path).stem]

    # 1. Tipo correto
    tipos    = manifest_record.get("types", [])
    expected = get_doc_type(tipos)
    actual   = set(g.objects(doc_uri, RDF.type))
    if expected not in actual:
        actual_fabio = [str(t).split("/")[-1] for t in actual if "fabio" in str(t)]
        result["wrong"]["doc_type"] = (actual_fabio, str(expected).split("/")[-1])
        result["missing"]["doc_type"] = expected
        result["problems"].append(
            f"wrong_type: {actual_fabio} → {str(expected).split('/')[-1]}"
        )

    # 2-6. Campos do manifest
    for pred, mfield, obrigatorio, _ in FIELD_SPEC:
        mval = manifest_record.get(mfield)
        if not mval:
            continue
        existing = list(g.objects(doc_uri, pred))
        if isinstance(mval, list):
            existing_strs = {str(v) for v in existing}
            missing_vals  = [v for v in mval if v and v not in existing_strs]
            if missing_vals and obrigatorio:
                result["missing"][mfield] = missing_vals
                result["problems"].append(f"missing_{mfield}: {len(missing_vals)} valor(es)")
        else:
            if not existing and obrigatorio:
                result["missing"][mfield] = mval
                result["problems"].append(f"missing_{mfield}")

    # 6. Mínimo de triplas
    n_triples = len(g)
    result["metrics"]["n_triples"] = n_triples
    if n_triples < TTL_MIN_TRIPLES:
        result["problems"].append(f"too_few_triples: {n_triples}")

    # 7. Seções retóricas DEO
    rhetorical = [DEO["Introduction"], DEO["Conclusion"], DEO["Methods"],
                  DEO["Results"], DEO["Discussion"], DEO["RelatedWork"], DEO["Background"]]
    n_rhetorical = sum(1 for rt in rhetorical if list(g.subjects(RDF.type, rt)))
    result["metrics"]["n_rhetorical_sections"] = n_rhetorical
    if n_rhetorical == 0:
        result["problems"].append("no_rhetorical_sections")

    # 8. Abstract
    abs_uris = list(g.subjects(RDF.type, DOCO["Abstract"]))
    has_abstract = any(list(g.objects(u, C4O["hasContent"])) for u in abs_uris)
    result["metrics"]["has_abstract"] = has_abstract

    # 9. Referências
    result["metrics"]["n_refs"] = len(list(g.subjects(RDF.type, BIBO["Article"])))

    return result


def patch_ttl(ttl_path: str, manifest_record: dict, audit: dict,
              dry_run: bool = False) -> int:
    """
    Aplica correções no TTL com dados do manifest.

    Para campos com substituir=True (creators, date):
      Remove o que o GROBID colocou (pode ser lixo) e coloca o do manifest.
    Para campos com substituir=False (subjects, title, language, url):
      Só adiciona o que está faltando, sem remover nada.
    """
    if not audit["missing"] and not audit["wrong"]:
        return 0

    g = Graph()
    g.parse(ttl_path, format="turtle")
    for prefix, ns_uri in [
        ("doco", "http://purl.org/spar/doco/"), ("deo", "http://purl.org/spar/deo/"),
        ("c4o", "http://purl.org/spar/c4o/"), ("fabio", "http://purl.org/spar/fabio/"),
        ("po", "http://www.essepuntato.it/2008/12/pattern#"),
        ("bibo", "http://purl.org/ontology/bibo/"), ("schema", "http://schema.org/"),
        ("dcterms", str(DCTERMS)), ("base", "http://pantheon.ufrj.br/resource/"),
    ]:
        g.bind(prefix, Namespace(ns_uri))

    doc_uri = BASE[Path(ttl_path).stem]
    added   = 0
    meta    = manifest_record

    # Tipo
    if "doc_type" in audit["missing"] or "doc_type" in audit["wrong"]:
        new_type = get_doc_type(meta.get("types", []))
        for t in list(g.objects(doc_uri, RDF.type)):
            if "fabio" in str(t) and "Work" not in str(t):
                g.remove((doc_uri, RDF.type, t))
        g.add((doc_uri, RDF.type, new_type))
        g.add((doc_uri, RDF.type, FABIO["Work"]))
        added += 1

    # Campos
    for pred, mfield, obrigatorio, substituir in FIELD_SPEC:
        if mfield not in audit["missing"]:
            continue
        mval = meta.get(mfield)
        if not mval:
            continue

        if isinstance(mval, list):
            values = [v for v in mval if v]
            if not values:
                continue
            if substituir:
                for existing in list(g.objects(doc_uri, pred)):
                    g.remove((doc_uri, pred, existing))
            existing_strs = {str(v) for v in g.objects(doc_uri, pred)}
            for val in values:
                if val not in existing_strs:
                    g.add((doc_uri, pred, Literal(val)))
                    added += 1
        else:
            if substituir:
                for existing in list(g.objects(doc_uri, pred)):
                    g.remove((doc_uri, pred, existing))
            if mfield == "date":
                clean, dtype = parse_date_clean(str(mval))
                if clean:
                    g.add((doc_uri, pred, Literal(clean, datatype=dtype)))
                    added += 1
            elif mfield == "handle_url":
                g.add((doc_uri, pred, URIRef(str(mval))))
                added += 1
            else:
                g.add((doc_uri, pred, Literal(str(mval))))
                added += 1

    if not dry_run and added > 0:
        g.serialize(destination=ttl_path, format="turtle")

    return added


def run_stage3(rdf_dir: str, manifest: dict, patch: bool, dry_run: bool,
               handle_filter) -> list:
    print_header("ESTÁGIO 3 — Validação de TTLs RDF (pós-conversão)")
    print("\n  Hierarquia de confiança aplicada:")
    print("    manifest   → tipo, date, creators, subjects, language, url")
    print("    GROBID/TEI → body, seções, parágrafos, referências estruturadas")

    ttl_files = sorted(Path(rdf_dir).glob("*.ttl"))
    if handle_filter:
        safe = handle_filter.replace("/", "_")
        ttl_files = [f for f in ttl_files if f.stem == safe]
        if not ttl_files:
            print(f"\n  ERRO: TTL para '{handle_filter}' não encontrado em {rdf_dir}")
            return []

    if not ttl_files:
        print(f"\n  Nenhum TTL encontrado em: {rdf_dir}")
        return []

    print(f"\n  Auditando {len(ttl_files)} TTLs...")

    results            = []
    docs_with_problems = []
    docs_ok            = []
    docs_not_in_manifest = []
    all_problems: Counter = Counter()

    for ttl in tqdm(ttl_files, desc="TTLs", unit="ttl",
                    disable=bool(handle_filter)):
        handle = ttl.stem.replace("_", "/", 1)
        meta   = manifest.get(handle)
        if meta is None:
            docs_not_in_manifest.append(handle)
            continue
        audit = check_ttl(str(ttl), meta)
        results.append(audit)
        if audit["problems"]:
            docs_with_problems.append((ttl, meta, audit))
            for p in audit["problems"]:
                all_problems[p.split(":")[0]] += 1
        else:
            docs_ok.append(handle)

    total = len(ttl_files)
    n_ok  = len(docs_ok)
    n_err = len(docs_with_problems)
    n_nm  = len(docs_not_in_manifest)

    print(f"\n  Total TTLs          : {total}")
    print(f"  ✓ Sem problemas     : {n_ok} ({100*n_ok//max(total,1)}%)")
    print(f"  ✗ Com problemas     : {n_err} ({100*n_err//max(total,1)}%)")
    if n_nm:
        print(f"  ? Não no manifest   : {n_nm}")

    if all_problems:
        print(f"\n  Problemas encontrados:")
        for prob, count in all_problems.most_common():
            print(f"    {count:5d}x  {prob}")

    # Métricas estruturais
    if results:
        n_rhet   = sum(1 for r in results if r["metrics"].get("n_rhetorical_sections", 0) > 0)
        n_abs    = sum(1 for r in results if r["metrics"].get("has_abstract"))
        avg_trip = sum(r["metrics"].get("n_triples", 0) for r in results) // max(len(results), 1)
        print(f"\n  Métricas estruturais (GROBID confiável aqui):")
        print(f"    Média triplas/doc        : {avg_trip:,}")
        print(f"    Com seção retórica (DEO) : {n_rhet}/{len(results)} ({100*n_rhet//max(len(results),1)}%)")
        print(f"    Com abstract             : {n_abs}/{len(results)} ({100*n_abs//max(len(results),1)}%)")

    show_n = len(docs_with_problems) if handle_filter else min(20, len(docs_with_problems))
    if docs_with_problems:
        print(f"\n  Detalhes (primeiros {show_n}):")
        print(f"  {'Handle':<24} Problemas")
        print(f"  {'-'*60}")
        for ttl_path, meta, audit in docs_with_problems[:show_n]:
            handle = Path(ttl_path).stem.replace("_", "/", 1)
            short  = [p.split(":")[0] for p in audit["problems"]]
            print(f"  {handle:<24} {', '.join(short)}")
            if handle_filter:
                for field, vals in audit["missing"].items():
                    v_str = str(vals[:2]) if isinstance(vals, list) else str(vals)[:60]
                    print(f"      MISSING  {field}: {v_str}")
                for field, (atual, correto) in audit["wrong"].items():
                    print(f"      WRONG    {field}: {atual} → {correto}")

    # Patch
    if patch and docs_with_problems:
        mode = "SIMULANDO" if dry_run else "CORRIGINDO"
        print(f"\n  {mode} {n_err} TTLs com dados do manifest...")
        total_added  = 0
        patched_docs = 0
        for ttl_path, meta, audit in tqdm(docs_with_problems, desc="Patch", unit="ttl"):
            added = patch_ttl(str(ttl_path), meta, audit, dry_run=dry_run)
            if added > 0:
                patched_docs += 1
                total_added  += added
        action = "seriam adicionadas" if dry_run else "adicionadas"
        print(f"\n  Documentos corrigidos : {patched_docs}")
        print(f"  Triplas {action}: {total_added:,}")
        if dry_run:
            print("\n  [DRY-RUN] Nenhum arquivo modificado.")
            print(f"  Aplique com: python quality_gate.py stage3 --patch")
        else:
            print(f"\n  ✓ Confirme rodando: python quality_gate.py stage3")
    elif not patch and docs_with_problems:
        print(f"\n  Para corrigir os {n_err} TTLs:")
        print(f"    python quality_gate.py stage3 --patch --dry-run")
        print(f"    python quality_gate.py stage3 --patch")

    print(f"\n  Relatório: {save_report('stage3_ttls', results)}")
    return results


# ══════════════════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Quality gate em 3 estágios — pipeline DoCO",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Estágios:
  stage1  Valida PDFs (pré-GROBID)
  stage2  Valida TEIs (pós-GROBID) — detecta onde o GROBID falhou
  stage3  Valida e corrige TTLs RDF — manifest é a fonte autoritativa
  all     Roda todos os estágios

Exemplos:
  python quality_gate.py stage3                         # audita TTLs
  python quality_gate.py stage3 --patch --dry-run       # simula correção
  python quality_gate.py stage3 --patch                 # CORRIGE os 1970 TTLs
  python quality_gate.py stage3 --handle 11422/2286     # analisa 1 handle
  python quality_gate.py stage2 --apply                 # move TEIs ruins
  python quality_gate.py all                            # pipeline completo
        """,
    )
    parser.add_argument("stage", choices=["stage1", "stage2", "stage3", "all"])
    parser.add_argument("--patch",    action="store_true")
    parser.add_argument("--dry-run",  action="store_true")
    parser.add_argument("--apply",    action="store_true",
                        help="Move rejeitados para subdir _rejected/ (stage1/2)")
    parser.add_argument("--manifest", type=str, default=None)
    parser.add_argument("--handle",   type=str, default=None)
    parser.add_argument("--pdf-dir",  type=str, default=PDF_DIR)
    parser.add_argument("--tei-dir",  type=str, default=TEI_DIR)
    parser.add_argument("--rdf-dir",  type=str, default=RDF_DIR)
    args = parser.parse_args()

    stages = ["stage1", "stage2", "stage3"] if args.stage == "all" else [args.stage]

    manifest = {}
    if "stage3" in stages:
        manifest_path = find_manifest(args.manifest)
        print(f"Manifest: {manifest_path}")
        manifest = load_manifest(manifest_path)
        print(f"  {len(manifest)} registros carregados")

    if "stage1" in stages:
        run_stage1(args.pdf_dir, apply=args.apply)

    if "stage2" in stages:
        run_stage2(args.tei_dir, apply=args.apply)

    if "stage3" in stages:
        run_stage3(
            args.rdf_dir, manifest,
            patch=args.patch,
            dry_run=args.dry_run,
            handle_filter=args.handle,
        )

    print(f"\n{'═'*65}")
    print(f"  Relatórios JSONL em: {REPORT_DIR}/")
    print(f"{'═'*65}\n")


if __name__ == "__main__":
    main()