#!/usr/bin/env python3
# tei_to_doco.py — converte XML TEI (GROBID) em RDF anotado com DoCO
#
# MUDANÇAS CRÍTICAS v2:
#   - manifest obrigatório: falha ruidosamente se não encontrado
#   - sanity check pós-build: aborta se TTL não tem subjects/date/type correto
#   - date: usa manifest (authoritative), não o TEI
#   - type: determinado SEMPRE pelo manifest, TEI é fallback apenas para título/autores
#   - relatório final mostra cobertura de campos obrigatórios
#
# Uso:
#   python tei_to_doco.py               # converte todos os TEIs novos
#   python tei_to_doco.py --limit 10    # teste rápido
#   python tei_to_doco.py --workers 8   # força número de workers
#   python tei_to_doco.py --reprocess   # reprocessa mesmo os já feitos
#   python tei_to_doco.py --manifest /caminho/manifest.jsonl

import argparse
import json
import os
import re
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from xml.etree import ElementTree as ET

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, RDF, XSD
from tqdm import tqdm

# ── Namespaces SPAR ───────────────────────────────────────────────────────────
DOCO   = Namespace("http://purl.org/spar/doco/")
DEO    = Namespace("http://purl.org/spar/deo/")
C4O    = Namespace("http://purl.org/spar/c4o/")
FABIO  = Namespace("http://purl.org/spar/fabio/")
PO     = Namespace("http://www.essepuntato.it/2008/12/pattern#")
BIBO   = Namespace("http://purl.org/ontology/bibo/")
SCHEMA = Namespace("http://schema.org/")
BASE   = Namespace("http://pantheon.ufrj.br/resource/")
TEI_NS = "http://www.tei-c.org/ns/1.0"

# ── Configuração ──────────────────────────────────────────────────────────────
TEI_DIR      = "data/tei"
RDF_DIR      = "data/rdf"
CONVERT_LOG  = "data/tei_to_doco_report.jsonl"
DEFAULT_WORKERS = os.cpu_count() or 4

# Caminhos candidatos para o manifest (pesquisados em ordem)
MANIFEST_CANDIDATES = [
    "data/manifest.jsonl",
    "../fase_1/data/manifest.jsonl",
    "../../fase_1/data/manifest.jsonl",
    "../data/manifest.jsonl",
    "manifest.jsonl",
]

# Thresholds
MIN_BODY_CHARS  = 500
MIN_TRIPLES     = 50
MIN_PARA_CHARS  = 30
MAX_TITLE_LEN   = 250

# ── Mapeamento de tipo ────────────────────────────────────────────────────────
TYPE_MAP = {
    "tese":        "DoctoralThesis",
    "doutorado":   "DoctoralThesis",
    "doctoral":    "DoctoralThesis",
    "dissertação": "MastersThesis",
    "mestrado":    "MastersThesis",
    "masters":     "MastersThesis",
}

# ── Padrões retóricos ─────────────────────────────────────────────────────────
SECTION_PATTERNS = [
    # ── Palavras-chave diretas ─────────────────────────────────────────────────
    (r"\b(introduc|introdu[çc])",                                          DEO,  "Introduction"),
    (r"\b(abstract|resumo|sum[aá]rio\s+em\s+ingl)",                       DOCO, "Abstract"),
    (r"\b(conclus|conclud|encerr)",                                        DEO,  "Conclusion"),
    (r"\bconsidera[çc][õo]es\s*finais",                                    DEO,  "Conclusion"),
    (r"\bfinal\s*(remarks?|considerations?|thoughts?)?$",                  DEO,  "Conclusion"),
    (r"\b(related.work|trabalho.relacion|literatura|revis[ãa]o|review)",   DEO,  "RelatedWork"),
    (r"\b(method|metodolog|materiai|materials|proposta|arquitetura)",      DEO,  "Methods"),
    (r"\b(experiment|experimen|avalia|evaluation|result|resultado)",       DEO,  "Results"),
    (r"\b(discuss|an[áa]lise|analysis)",                                   DEO,  "Discussion"),
    (r"\b(background|fundament|conceitos\s+b[áa]sicos|theoretical|referencial)",
                                                                           DEO,  "Background"),
    (r"\b(acknowledgement|agradec)",                                       DEO,  "Acknowledgements"),
    (r"^referên[çc]ias\b",                                                 DOCO, "ListOfReferences"),
    (r"\b(bibliograf|works.cited|referências\s+bibliogr)",                 DOCO, "ListOfReferences"),
    (r"\b(referenc)",                                                      DOCO, "ListOfReferences"),
    (r"\b(appendix|ap[êe]ndice|anexo)",                                    DOCO, "Appendix"),
    (r"^sugest[õo]es\b",                                                   DEO,  "FutureWork"),
    # ── Prefixo numérico/romano — cobre "VII - CONCLUSÕES", "6. Resultados" ───
    (r"^\s*[IVX]+[\.\s\-]+.*\b(introduc|introdu[çc])",                    DEO,  "Introduction"),
    (r"^\s*[IVX]+[\.\s\-]+.*\b(conclus|considera)",                       DEO,  "Conclusion"),
    (r"^\s*[IVX]+[\.\s\-]+.*\b(result|avalia|experiment)",                DEO,  "Results"),
    (r"^\s*[IVX]+[\.\s\-]+.*\b(discuss|an[áa]lise)",                      DEO,  "Discussion"),
    (r"^\s*[IVX]+[\.\s\-]+.*\b(method|metodolog)",                        DEO,  "Methods"),
    (r"^\s*[IVX]+[\.\s\-]+.*\b(referenc|bibliograf)",                     DOCO, "ListOfReferences"),
    (r"^\s*[IVX]+[\.\s\-]+sugest[õo]es\b",                                DEO,  "FutureWork"),
    (r"^\s*\d+[\.\s\-]+.*\b(introduc|introdu[çc])",                       DEO,  "Introduction"),
    (r"^\s*\d+[\.\s\-]+.*\b(conclus|considera|final)",                    DEO,  "Conclusion"),
    (r"^\s*\d+[\.\s\-]+.*\b(result|avalia|experiment)",                   DEO,  "Results"),
    (r"^\s*\d+[\.\s\-]+.*\b(discuss|an[áa]lise)",                         DEO,  "Discussion"),
    (r"^\s*\d+[\.\s\-]+.*\b(method|metodolog|proposta)",                  DEO,  "Methods"),
    (r"^\s*cap[íi]tulo\s+\d+.*\b(conclus|considera)",                     DEO,  "Conclusion"),
    (r"^\s*cap[íi]tulo\s+\d+.*\b(result|avalia)",                         DEO,  "Results"),
]

ABSTRACT_SKIP = [
    "agradeç", "agradecimento", "acknowledge", "dedico", "dedicatória",
    "à minha", "ao meu", "lista de ", "sumário", "índice geral",
]

BAD_TITLE_PATTERNS = [
    r"•{3,}", r"-{5,}", r"\.{5,}",
    r"^\s*cap[íi]tulo\s+[IVX\d]", r"\d{2,}\s*$",
]

BAD_AUTHOR_PATTERNS = [
    r"•{2,}", r"-{3,}",
    r"^(cap[íi]tulo|seção|parte|anexo|ap[êe]ndice)\s",
    r"\d{2,}$", r"^\W+$",
    r"^[A-Z][a-z]*(\s+[A-Z][a-z]*){3,}",
]


# ── Utilitários ───────────────────────────────────────────────────────────────

def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def tei_text(elem) -> str:
    if elem is None:
        return ""
    return " ".join(elem.itertext()).strip()


def is_bad_title(t: str) -> bool:
    return len(t) > MAX_TITLE_LEN or any(
        re.search(p, t, re.IGNORECASE) for p in BAD_TITLE_PATTERNS
    )


def is_bad_author(a: str) -> bool:
    return any(re.search(p, a, re.IGNORECASE) for p in BAD_AUTHOR_PATTERNS)


def infer_doco_type(head: str):
    h = head.lower()
    for pattern, ns, cls in SECTION_PATTERNS:
        if re.search(pattern, h):
            return (ns, cls)
    return (DOCO, "Section")


def get_doc_type(tipos: list) -> URIRef:
    """Determina tipo FABIO a partir da lista dc:type do manifest."""
    for t in tipos:
        t_lower = t.lower()
        for key, cls in TYPE_MAP.items():
            if key in t_lower:
                return FABIO[cls]
    return FABIO["MastersThesis"]


def parse_date(raw: str) -> tuple[str, URIRef]:
    """Extrai data limpa do campo dc:date (que pode ser timestamp ISO)."""
    if not raw:
        return "", XSD.gYear
    clean = raw[:10].strip()
    if len(clean) == 10 and clean[4] == "-" and clean[7] == "-":
        return clean, XSD.date
    year = clean[:4]
    return (year, XSD.gYear) if year.isdigit() else ("", XSD.gYear)


# ── Manifest ──────────────────────────────────────────────────────────────────

def find_manifest(explicit: str | None) -> str:
    """
    Localiza o manifest.jsonl.
    FALHA RUIDOSAMENTE se não encontrar — nunca continua com meta vazio.
    """
    candidates = ([explicit] if explicit else []) + MANIFEST_CANDIDATES
    for path in candidates:
        if path and os.path.exists(path):
            return path

    print("\n" + "="*65)
    print("ERRO FATAL: manifest.jsonl não encontrado.")
    print("Este arquivo é OBRIGATÓRIO — sem ele, os TTLs ficam sem")
    print("subjects, date correto, tipo e creators.")
    print("\nLocais procurados:")
    for c in candidates:
        print(f"  {c}")
    print("\nSolução mais rápida:")
    print("  cp ../fase_1/data/manifest.jsonl data/manifest.jsonl")
    print("  python tei_to_doco.py")
    print("="*65 + "\n")
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


# ── Parse TEI ─────────────────────────────────────────────────────────────────

def parse_tei(tei_path: str) -> dict:
    ns = {"tei": TEI_NS}
    try:
        tree = ET.parse(tei_path)
        root = tree.getroot()
    except ET.ParseError as e:
        return {"error": str(e)}

    def find(path):
        return root.find(path, ns)

    def findall(path):
        return root.findall(path, ns)

    def text(path):
        el = find(path)
        return clean_text(tei_text(el)) if el is not None else ""

    # Título
    title = (
        text(".//tei:fileDesc/tei:titleStmt/tei:title") or
        text(".//tei:titleStmt/tei:title") or ""
    )
    if is_bad_title(title):
        title = ""

    # Autores (do TEI — usados como fallback se manifest não tiver)
    authors = []
    seen = set()
    pers_list = (
        findall(".//tei:fileDesc//tei:analytic//tei:persName") or
        findall(".//tei:fileDesc//tei:author//tei:persName") or
        findall(".//tei:sourceDesc//tei:persName")[:5]
    )
    for pers in pers_list:
        forenames = " ".join(
            clean_text(tei_text(fn))
            for fn in pers.findall("tei:forename", ns)
            if tei_text(fn).strip()
        )
        sn_el = pers.find("tei:surname", ns)
        surname = clean_text(tei_text(sn_el)) if sn_el is not None else ""
        full = f"{forenames} {surname}".strip()
        if not full or len(full.split()) > 5:
            continue
        if any(c.isdigit() for c in full):
            continue
        if is_bad_author(full):
            continue
        if full not in seen:
            seen.add(full)
            authors.append(full)

    # Abstract
    abstract = ""
    abs_el = find(".//tei:profileDesc/tei:abstract")
    if abs_el is not None:
        paragraphs = abs_el.findall(".//tei:p", ns) or [abs_el]
        best = ""
        for p in paragraphs:
            txt = clean_text(tei_text(p))
            low = txt.lower()
            if any(skip in low[:120] for skip in ABSTRACT_SKIP):
                continue
            if any(kw in low[:80] for kw in [
                "resumo", "abstract", "neste trabalho", "this work",
                "this paper", "este trabalho", "o presente", "this dissertation",
            ]):
                best = txt
                break
            if len(txt) > len(best):
                best = txt
        abstract = best

    # Seções
    sections = []
    body = find(".//tei:body")
    if body is not None:
        body_text = clean_text(tei_text(body))
        if len(body_text) < MIN_BODY_CHARS:
            return {"error": f"body_too_short: {len(body_text)} chars"}

        for div in body.findall(".//tei:div", ns):
            head_el  = div.find("tei:head", ns)
            head_txt = clean_text(tei_text(head_el)) if head_el is not None else ""
            paras    = [
                clean_text(tei_text(p))
                for p in div.findall("tei:p", ns)
                if len(clean_text(tei_text(p))) >= MIN_PARA_CHARS
            ]
            if not head_txt and not paras:
                continue
            sections.append({
                "head":       head_txt,
                "doco_type":  infer_doco_type(head_txt),
                "paragraphs": paras,
                "n":          head_el.get("n", "") if head_el is not None else "",
            })
    else:
        return {"error": "no_body_element"}

    # ── Referências ───────────────────────────────────────────────────────────
    # Padrões que indicam pseudo-título de ref (OCR-lixo, fragmentos, locais)
    BAD_REF_PATTERNS = [
        r"^disponível\s+em\b",          # "Disponível em http://..."
        r"^acesso\s+em\b",              # "Acesso em: 12 jan 2020"
        r"^rio\s+de\s+janeiro\b",       # "Rio de Janeiro" como título
        r"^s[ãa]o\s+paulo\b",
        r"^referências\s+bibliogr",     # "Referências Bibliográficas: p."
        r"^\s*https?://",               # URLs puras
        r"^\s*www\.",
        r"^\s*p\.\s*\d",               # "p. 123"
        r"^\d{1,4}\s*$",               # só número de página
        r"^in:\s",                      # "In: Proceedings..."
    ]

    def is_bad_ref_title(title: str) -> bool:
        t = title.lower().strip()
        if len(t) < 5:
            return True
        # Menos de 3 palavras alfanuméricas = provavelmente lixo
        words = [w for w in re.split(r'\W+', t) if len(w) > 1]
        if len(words) < 2:
            return True
        # Fração muito alta de dígitos
        digit_ratio = sum(c.isdigit() for c in t) / max(len(t), 1)
        if digit_ratio > 0.4:
            return True
        return any(re.search(p, t, re.IGNORECASE) for p in BAD_REF_PATTERNS)

    refs = []
    for bib in findall(".//tei:listBibl/tei:biblStruct"):
        def text_in(path):
            el = bib.find(path, ns)
            return clean_text(tei_text(el)) if el is not None else ""

        def attr_in(path, attr):
            el = bib.find(path, ns)
            return el.get(attr, "") if el is not None else ""

        ref_title = text_in(".//tei:title[@level='a']") or text_in(".//tei:title[@level='m']")
        ref_year  = attr_in(".//tei:date[@type='published']", "when")
        ref_authors = [
            clean_text(tei_text(p)) for p in bib.findall(".//tei:persName", ns)
            if not is_bad_author(clean_text(tei_text(p))) and
               len(clean_text(tei_text(p)).split()) <= 4
        ]

        # Filtro aprimorado: rejeita lixo de OCR e pseudo-títulos
        if ref_title and not is_bad_ref_title(ref_title) and sum(c.isalpha() for c in ref_title) > 10:
            refs.append({
                "title":   ref_title,
                "year":    ref_year[:4] if ref_year else "",
                "authors": ref_authors[:3],
            })

    return {
        "title": title, "authors": authors, "abstract": abstract,
        "sections": sections, "refs": refs,
    }


# ── Build Graph ───────────────────────────────────────────────────────────────

def build_graph(handle: str, tei_data: dict, meta: dict) -> Graph:
    g = Graph()
    for prefix, ns_uri in [
        ("doco",    "http://purl.org/spar/doco/"),
        ("deo",     "http://purl.org/spar/deo/"),
        ("c4o",     "http://purl.org/spar/c4o/"),
        ("fabio",   "http://purl.org/spar/fabio/"),
        ("po",      "http://www.essepuntato.it/2008/12/pattern#"),
        ("bibo",    "http://purl.org/ontology/bibo/"),
        ("schema",  "http://schema.org/"),
        ("dcterms", str(DCTERMS)),
        ("base",    "http://pantheon.ufrj.br/resource/"),
    ]:
        g.bind(prefix, Namespace(ns_uri))

    safe    = handle.replace("/", "_")
    doc_uri = BASE[safe]

    # ── Tipo do documento — SEMPRE do manifest ────────────────────────────────
    tipos    = meta.get("types", [])
    doc_type = get_doc_type(tipos)
    g.add((doc_uri, RDF.type, doc_type))
    g.add((doc_uri, RDF.type, FABIO["Work"]))
    g.add((doc_uri, BIBO["handle"], Literal(handle)))

    # ── Título — TEI primeiro, manifest como fallback ─────────────────────────
    title = tei_data.get("title") or meta.get("title", "")
    if title:
        g.add((doc_uri, DCTERMS.title, Literal(title)))

    # ── Autores — manifest primeiro (confiável), TEI como fallback ────────────
    authors = meta.get("creators") or tei_data.get("authors", [])
    for creator in authors:
        if creator:
            g.add((doc_uri, DCTERMS.creator, Literal(creator)))

    # ── Data — SEMPRE do manifest, com parse correto ──────────────────────────
    raw_date  = meta.get("date", "")
    clean_date, dtype = parse_date(raw_date)
    if clean_date:
        g.add((doc_uri, DCTERMS.date, Literal(clean_date, datatype=dtype)))

    # ── Subjects — SEMPRE do manifest ────────────────────────────────────────
    for subj in meta.get("subjects", []):
        if subj:
            g.add((doc_uri, DCTERMS.subject, Literal(subj)))

    # ── Idioma ────────────────────────────────────────────────────────────────
    lang = meta.get("language", "")
    if lang:
        g.add((doc_uri, DCTERMS.language, Literal(lang)))

    # ── URL do handle ─────────────────────────────────────────────────────────
    url = meta.get("handle_url", "")
    if url:
        g.add((doc_uri, SCHEMA.url, URIRef(url)))

    # ── Abstract — TEI se bom, manifest como fallback ─────────────────────────
    tei_abs  = tei_data.get("abstract", "")
    meta_abs = meta.get("description", "")
    # Hierarquia: TEI se >= 100 chars, depois manifest se >= 20 chars (threshold menor
    # para capturar abstracts legítimos do OAI que são concisos), depois qualquer coisa
    abstract = (tei_abs  if len(tei_abs)  >= 100
                else meta_abs if len(meta_abs) >= 20
                else tei_abs or meta_abs)
    if abstract:
        abs_uri = BASE[f"{safe}_abstract"]
        g.add((abs_uri, RDF.type,          DOCO["Abstract"]))
        g.add((abs_uri, C4O["hasContent"], Literal(abstract)))
        g.add((doc_uri, PO["contains"],    abs_uri))

    # ── Seções e parágrafos ───────────────────────────────────────────────────
    for i, sec in enumerate(tei_data.get("sections", [])):
        ns_cls, cls_name = sec["doco_type"]
        sec_uri = BASE[f"{safe}_sec_{i}"]
        g.add((sec_uri, RDF.type,       ns_cls[cls_name]))
        if ns_cls != DOCO or cls_name != "Section":
            g.add((sec_uri, RDF.type,   DOCO["Section"]))
        g.add((doc_uri, PO["contains"], sec_uri))
        if sec["head"]:
            g.add((sec_uri, DCTERMS.title, Literal(sec["head"])))
        if sec["n"]:
            g.add((sec_uri, SCHEMA.position, Literal(sec["n"])))
        for j, para_text in enumerate(sec["paragraphs"]):
            if not para_text:
                continue
            para_uri = BASE[f"{safe}_sec_{i}_para_{j}"]
            g.add((para_uri, RDF.type,          DOCO["Paragraph"]))
            g.add((para_uri, C4O["hasContent"], Literal(para_text)))
            g.add((sec_uri,  PO["contains"],    para_uri))

    # ── Referências ───────────────────────────────────────────────────────────
    refs = tei_data.get("refs", [])
    if refs:
        reflist_uri = BASE[f"{safe}_references"]
        g.add((reflist_uri, RDF.type,       DOCO["ListOfReferences"]))
        g.add((doc_uri,     PO["contains"], reflist_uri))
        for k, ref in enumerate(refs):
            ref_uri = BASE[f"{safe}_ref_{k}"]
            g.add((ref_uri,     RDF.type,        BIBO["Article"]))
            g.add((reflist_uri, PO["contains"],  ref_uri))
            if ref.get("title"):
                g.add((ref_uri, DCTERMS.title,   Literal(ref["title"])))
            if ref.get("year"):
                g.add((ref_uri, DCTERMS.date,    Literal(ref["year"])))
            for auth in ref.get("authors", []):
                g.add((ref_uri, DCTERMS.creator, Literal(auth)))

    return g


# ── Sanity check pós-build ────────────────────────────────────────────────────

def sanity_check(g: Graph, doc_uri: URIRef, meta: dict) -> list[str]:
    """
    Verifica campos obrigatórios no grafo antes de salvar.
    Retorna lista de problemas. Lista vazia = OK.
    """
    problems = []

    # Tipo correto
    tipos    = meta.get("types", [])
    expected = get_doc_type(tipos)
    if expected not in set(g.objects(doc_uri, RDF.type)):
        problems.append(f"tipo_errado: esperado {str(expected).split('/')[-1]}")

    # Subjects
    if meta.get("subjects") and not list(g.objects(doc_uri, DCTERMS.subject)):
        problems.append("subjects_ausentes")

    # Date
    if meta.get("date") and not list(g.objects(doc_uri, DCTERMS.date)):
        problems.append("date_ausente")

    # Creator
    if meta.get("creators") and not list(g.objects(doc_uri, DCTERMS.creator)):
        problems.append("creators_ausentes")

    return problems


# ── Worker (ProcessPoolExecutor) ──────────────────────────────────────────────

def convert_one(args_tuple) -> dict:
    tei_path, handle, meta, out_dir, min_triples = args_tuple
    result = {"handle": handle, "tei_path": tei_path, "status": "pending",
              "sanity": []}

    # Meta vazio é erro — mas não abortamos, apenas reportamos
    if not meta:
        result.update(status="no_manifest_meta",
                      error="handle não encontrado no manifest")
        return result

    tei_data = parse_tei(tei_path)
    if "error" in tei_data:
        result.update(status="parse_error", error=tei_data["error"])
        return result

    doc_uri = BASE[handle.replace("/", "_")]
    g       = build_graph(handle, tei_data, meta)

    # Sanity check antes de salvar
    sanity_errors = sanity_check(g, doc_uri, meta)
    result["sanity"] = sanity_errors

    n_triples = len(g)
    if n_triples < min_triples:
        result.update(status="too_few_triples",
                      error=f"{n_triples} triplas < mínimo {min_triples}",
                      triples=n_triples)
        return result

    out_path = os.path.join(out_dir, handle.replace("/", "_") + ".ttl")
    g.serialize(destination=out_path, format="turtle")

    result.update(
        status="ok" if not sanity_errors else "ok_with_warnings",
        rdf_path=out_path,
        triples=n_triples,
        sections=len(tei_data.get("sections", [])),
        refs=len(tei_data.get("refs", [])),
        has_conclusion=any(
            sec["doco_type"] == (DEO, "Conclusion")
            for sec in tei_data.get("sections", [])
        ),
        has_abstract=bool(tei_data.get("abstract")),
        has_subjects=bool(meta.get("subjects")),
    )
    return result


# ── Main ──────────────────────────────────────────────────────────────────────

def load_done(log_path: str) -> set:
    done = set()
    if not os.path.exists(log_path):
        return done
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
                if r.get("status") in ("ok", "ok_with_warnings"):
                    done.add(r["handle"])
            except Exception:
                pass
    return done


def main():
    parser = argparse.ArgumentParser(
        description="TEI XML → DoCO RDF com sanity check embutido"
    )
    parser.add_argument("--limit",       type=int, default=None)
    parser.add_argument("--workers",     type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--reprocess",   action="store_true")
    parser.add_argument("--min-triples", type=int, default=MIN_TRIPLES)
    parser.add_argument("--manifest",    type=str, default=None,
                        help="Caminho explícito para o manifest.jsonl")
    args = parser.parse_args()

    # Manifest é obrigatório — falha ruidosamente se não encontrar
    manifest_path = find_manifest(args.manifest)
    print(f"Manifest: {manifest_path}")
    manifest = load_manifest(manifest_path)
    print(f"  {len(manifest)} registros carregados")

    os.makedirs(RDF_DIR, exist_ok=True)

    done      = set() if args.reprocess else load_done(CONVERT_LOG)
    tei_files = sorted(Path(TEI_DIR).glob("*.tei.xml"))
    no_meta   = []

    tasks = []
    for tei in tei_files:
        stem   = tei.name.replace(".tei.xml", "")
        handle = stem.replace("_", "/", 1)
        if handle in done:
            continue
        meta = manifest.get(handle)
        if not meta:
            no_meta.append(handle)
            continue
        tasks.append((str(tei), handle, meta, RDF_DIR, args.min_triples))

    if args.limit:
        tasks = tasks[:args.limit]

    print(f"\nTEIs encontrados  : {len(tei_files)}")
    print(f"Já convertidos    : {len(done)}")
    print(f"Sem meta manifest : {len(no_meta)}")
    print(f"A converter agora : {len(tasks)}")
    print(f"Workers (CPU)     : {args.workers}")
    print(f"Min triplas       : {args.min_triples}\n")

    if no_meta:
        print(f"AVISO: {len(no_meta)} TEIs sem correspondência no manifest:")
        for h in no_meta[:10]:
            print(f"  {h}")
        if len(no_meta) > 10:
            print(f"  ... e mais {len(no_meta)-10}")
        print()

    if not tasks:
        print("Nada a converter.")
        return

    stats = {"ok": 0, "ok_with_warnings": 0, "parse_error": 0,
             "too_few_triples": 0, "error": 0}
    total_triples        = 0
    docs_with_conclusion = 0
    docs_with_abstract   = 0
    sanity_failures      = []
    log = open(CONVERT_LOG, "a", encoding="utf-8")

    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(convert_one, task): task[1] for task in tasks}

        with tqdm(total=len(futures), desc="DoCO RDF",
                  unit="doc", dynamic_ncols=True) as pbar:
            for future in as_completed(futures):
                try:
                    res = future.result()
                except Exception as e:
                    handle = futures[future]
                    res = {"handle": handle, "status": "error", "error": str(e),
                           "sanity": []}

                log.write(json.dumps(res, ensure_ascii=False) + "\n")
                log.flush()

                st = res.get("status", "error")
                stats[st] = stats.get(st, 0) + 1

                if st in ("ok", "ok_with_warnings"):
                    total_triples        += res.get("triples", 0)
                    docs_with_conclusion += int(res.get("has_conclusion", False))
                    docs_with_abstract   += int(res.get("has_abstract", False))

                if res.get("sanity"):
                    sanity_failures.append((res["handle"], res["sanity"]))

                pbar.set_postfix(
                    {k: v for k, v in stats.items() if v > 0}, refresh=False
                )
                pbar.update(1)

    log.close()
    ok_total = stats["ok"] + stats["ok_with_warnings"]

    print(f"\n{'='*60}")
    print(f"Conversão concluída")
    print(f"  ✓ OK                : {stats['ok']}")
    print(f"  ⚠ OK c/ avisos      : {stats['ok_with_warnings']}")
    print(f"  ✗ Erros de parse    : {stats['parse_error']}")
    print(f"  ✗ Poucas triplas    : {stats['too_few_triples']}")
    print(f"  ✗ Outros erros      : {stats['error']}")
    print(f"\n  Total de triplas    : {total_triples:,}")
    print(f"  Média triplas/doc   : {total_triples // max(ok_total, 1):,}")
    print(f"  Com Conclusão       : {docs_with_conclusion} ({100*docs_with_conclusion//max(ok_total,1)}%)")
    print(f"  Com Abstract        : {docs_with_abstract} ({100*docs_with_abstract//max(ok_total,1)}%)")

    if sanity_failures:
        print(f"\n  ⚠ SANITY FAILURES   : {len(sanity_failures)} docs")
        print("  (run validate_rdf.py --patch para corrigir)")
        for handle, errs in sanity_failures[:5]:
            print(f"    {handle}: {', '.join(errs)}")
    else:
        print(f"\n  ✓ SANITY OK: todos os campos obrigatórios presentes")

    print(f"\n  RDF em: {RDF_DIR}/")
    print(f"\nPróximo: python validate_rdf.py  → confirma integridade")
    print(f"         python quality_gate.py  → filtra scans ruins")


if __name__ == "__main__":
    main()