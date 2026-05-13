#!/usr/bin/env python3
# corpus_statistics.py — estatísticas descritivas, gráficos e análise de rede
#
# Gera 14 gráficos PNG + relatório Markdown consolidado.
# Corrige query do Bloco 4 (usa DISTINCT para evitar duplicatas por multi-subject).
#
# Uso:
#   python avaliacao/corpus_statistics.py
#   python avaliacao/corpus_statistics.py --export data/corpus_stats.json
#   python avaliacao/corpus_statistics.py --skip-tei   # pula análise dos XMLs

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import networkx as nx
import numpy as np
import requests
from scipy.stats import spearmanr, linregress

# ── Caminhos ──────────────────────────────────────────────────────────────────
_HERE         = Path(__file__).parent
DISCOURSE_DIR = _HERE.parent / "fase_3" / "data" / "discourse"
MANIFEST_FILE = _HERE.parent / "fase_1" / "data" / "manifest.jsonl"
TEI_DIR       = _HERE.parent / "fase_2" / "data" / "tei"
RDF_DIR       = _HERE.parent / "fase_2" / "data" / "rdf"
CHARTS_DIR    = _HERE / "data" / "charts"

FUSEKI_URL  = "http://localhost:3030"
DATASET     = "pantheon"
FUSEKI_USER = "admin"
FUSEKI_PASS = "pantheon123"
SPARQL_URL  = f"{FUSEKI_URL}/{DATASET}/query"

PREFIXES = """
PREFIX fabio:     <http://purl.org/spar/fabio/>
PREFIX doco:      <http://purl.org/spar/doco/>
PREFIX deo:       <http://purl.org/spar/deo/>
PREFIX c4o:       <http://purl.org/spar/c4o/>
PREFIX po:        <http://www.essepuntato.it/2008/12/pattern#>
PREFIX dcterms:   <http://purl.org/dc/terms/>
PREFIX discourse: <http://pantheon.ufrj.br/ontology/discourse#>
"""

TEI_NS  = "http://www.tei-c.org/ns/1.0"
PALETTE = ["#2196F3","#4CAF50","#FF9800","#E91E63","#9C27B0",
           "#00BCD4","#FF5722","#607D8B","#795548","#3F51B5"]

plt.rcParams.update({"font.family":"DejaVu Sans","font.size":10,
                     "axes.spines.top":False,"axes.spines.right":False})


# ── Helpers ───────────────────────────────────────────────────────────────────

def sparql(query: str) -> list[dict]:
    try:
        r = requests.get(SPARQL_URL, params={"query": PREFIXES + query},
                         headers={"Accept": "application/sparql-results+json"},
                         auth=(FUSEKI_USER, FUSEKI_PASS), timeout=120)
        if r.status_code != 200:
            return []
        data  = r.json(); vars_ = data["head"]["vars"]
        return [{v: b.get(v,{}).get("value","") for v in vars_}
                for b in data["results"]["bindings"]]
    except Exception as e:
        print(f"  Erro SPARQL: {e}"); return []


def section(title: str):
    print(f"\n{'='*65}\n  {title}\n{'='*65}")


def describe(values: list, label: str = "", unit: str = "") -> dict:
    if not values:
        return {}
    arr = np.array(values, dtype=float)
    p   = np.percentile(arr, [5, 25, 50, 75, 95])
    st  = {"n":len(arr),"min":float(arr.min()),"p5":float(p[0]),
           "q1":float(p[1]),"media":float(arr.mean()),"mediana":float(p[2]),
           "q3":float(p[3]),"p95":float(p[4]),"max":float(arr.max()),
           "dp":float(arr.std()),
           "cv":float(arr.std()/arr.mean()) if arr.mean()>0 else 0}
    if label:
        suf = f" {unit}" if unit else ""
        print(f"\n  {label}  (n={st['n']:,})")
        print(f"    Média   : {st['media']:.2f}{suf}   DP={st['dp']:.2f}")
        print(f"    Mediana : {st['mediana']:.2f}{suf}   CV={st['cv']:.2f}")
        print(f"    P5–P95  : [{st['p5']:.1f}, {st['p95']:.1f}]{suf}")
        print(f"    Min–Max : [{st['min']:.1f}, {st['max']:.1f}]{suf}")
    return {k: round(v,3) for k,v in st.items()}


def gini(values: list) -> float:
    arr = np.sort(np.abs(np.array(values, dtype=float)))
    if not len(arr) or arr.sum() == 0:
        return 0.0
    n = len(arr); idx = np.arange(1, n+1)
    return float((2*(idx*arr).sum()/(n*arr.sum())) - (n+1)/n)


def save_chart(fig: plt.Figure, name: str) -> None:
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    path = CHARTS_DIR / f"{name}.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"    → {path.name}")


# ══════════════════════════════════════════════════════════════════════════════
# BLOCO 1 — Manifest
# ══════════════════════════════════════════════════════════════════════════════

def stats_manifest() -> dict:
    section("BLOCO 1 — Corpus: metadados OAI-PMH (manifest.jsonl)")
    if not MANIFEST_FILE.exists():
        print("  Manifest não encontrado."); return {}

    records = []
    with open(MANIFEST_FILE, encoding="utf-8") as f:
        for line in f:
            try: records.append(json.loads(line))
            except: pass
    print(f"  Total de registros: {len(records):,}")

    tipos = Counter(t for r in records for t in r.get("types", []))
    langs = Counter(r.get("language", "?") for r in records)
    years = []
    for r in records:
        d = r.get("date","") or r.get("datestamp","")
        m = re.search(r"\b(19|20)\d{2}\b", str(d))
        if m:
            y = int(m.group())
            if 1970 <= y <= 2030: years.append(y)

    print("\n  Tipos:"); [print(f"    {t:<25} {n:>5} ({100*n/len(records):.1f}%)") for t,n in tipos.most_common(5)]
    print("\n  Idiomas:"); [print(f"    {l:<10} {n:>5} ({100*n/len(records):.1f}%)") for l,n in langs.most_common(4)]

    title_lens = [len(r.get("title","")) for r in records if r.get("title")]
    n_subjects = [len(r.get("subjects",[])) for r in records]
    describe(title_lens, "Comprimento do título", "chars")
    describe(n_subjects, "Subjects CNPq por documento")

    # Gráfico 1 — Distribuição temporal
    yr_c = Counter(years); yrs = sorted(yr_c)
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.bar(yrs, [yr_c[y] for y in yrs], color=PALETTE[0], alpha=0.85)
    ax.set_xlabel("Ano"); ax.set_ylabel("Documentos")
    ax.set_title("Distribuição temporal do corpus")
    ax.yaxis.set_major_locator(mticker.MaxNLocator(integer=True))
    save_chart(fig, "01_distribuicao_temporal")

    # Gráfico 2 — Tipos e idiomas
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    tp = tipos.most_common(5)
    axes[0].barh([t for t,_ in tp], [n for _,n in tp], color=PALETTE[1])
    axes[0].set_title("Tipos de documento"); axes[0].set_xlabel("Documentos")
    tl = langs.most_common(5)
    axes[1].pie([n for _,n in tl], labels=[l for l,_ in tl],
                autopct="%1.1f%%", colors=PALETTE[:len(tl)])
    axes[1].set_title("Idioma dos documentos")
    fig.tight_layout(); save_chart(fig, "02_tipos_idiomas")

    return {"total": len(records), "tipos": dict(tipos.most_common()),
            "idiomas": dict(langs.most_common()),
            "titulo_chars": describe(title_lens), "n_subjects": describe(n_subjects)}


# ══════════════════════════════════════════════════════════════════════════════
# BLOCO 2 — Estrutura do grafo
# ══════════════════════════════════════════════════════════════════════════════

def stats_graph_structure() -> dict:
    section("BLOCO 2 — Grafo: estatísticas estruturais (DoCO/DEO)")

    rows = sparql("""
SELECT ?doc (COUNT(DISTINCT ?sec) AS ?n_sec) (COUNT(DISTINCT ?para) AS ?n_para)
WHERE {
  ?doc a fabio:Work .
  OPTIONAL { ?doc po:contains ?sec  . ?sec  a doco:Section }
  OPTIONAL { ?sec po:contains ?para . ?para a doco:Paragraph }
}
GROUP BY ?doc
""")
    secs  = [int(r["n_sec"])  for r in rows]
    paras = [int(r["n_para"]) for r in rows]
    describe(secs,  "Seções DoCO por documento")
    describe(paras, "Parágrafos por documento")

    deo_rows = sparql("""
SELECT ?tipo (COUNT(DISTINCT ?doc) AS ?n)
WHERE {
  ?doc a fabio:Work . ?doc po:contains ?sec . ?sec a ?tipo .
  FILTER(STRSTARTS(STR(?tipo), "http://purl.org/spar/deo/"))
}
GROUP BY ?tipo ORDER BY DESC(?n)
""")
    total = len(rows)
    deo_cov = {}
    print(f"\n  Cobertura DEO (% de {total:,} docs):")
    for r in deo_rows:
        tipo = r["tipo"].replace("http://purl.org/spar/deo/","deo:")
        n = int(r["n"]); pct = 100*n/total if total else 0
        print(f"    {tipo:<25} {n:>5} ({pct:.1f}%)")
        deo_cov[tipo] = {"n_docs": n, "pct": round(pct,1)}

    ref_rows = sparql("""
SELECT ?doc (COUNT(?ref) AS ?n_refs)
WHERE {
  ?doc a fabio:Work . ?doc po:contains ?reflist .
  ?reflist a doco:ListOfReferences . ?reflist po:contains ?ref .
}
GROUP BY ?doc
""")
    refs_vals = [int(r["n_refs"]) for r in ref_rows if r.get("n_refs")]
    describe(refs_vals, "Referências por documento")

    # Gráfico 3
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    for ax, data, color, label in zip(axes,
        [secs, paras], [PALETTE[0], PALETTE[2]],
        ["Seções por documento","Parágrafos por documento"]):
        ax.hist(data, bins=40, color=color, alpha=0.85, edgecolor="white")
        ax.axvline(np.median(data), color="red", linestyle="--",
                   label=f"Mediana={np.median(data):.0f}")
        ax.set_title(label); ax.legend()
    fig.tight_layout(); save_chart(fig, "03_dist_secoes_paragrafos")

    # Gráfico 4 — Cobertura DEO
    tipos_d = list(deo_cov.keys()); pcts_d = [v["pct"] for v in deo_cov.values()]
    fig, ax = plt.subplots(figsize=(9, 4))
    bars = ax.barh(tipos_d[::-1], pcts_d[::-1], color=PALETTE[4], alpha=0.85)
    ax.bar_label(bars, fmt="%.1f%%", padding=3)
    ax.set_xlabel("% dos documentos"); ax.set_title("Cobertura DEO no corpus")
    ax.set_xlim(0, 75); fig.tight_layout(); save_chart(fig, "04_cobertura_deo")

    # Gráfico 5 — Referências
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.hist(refs_vals, bins=40, color=PALETTE[3], alpha=0.85, edgecolor="white")
    ax.axvline(np.median(refs_vals), color="red", linestyle="--",
               label=f"Mediana={np.median(refs_vals):.0f}")
    ax.set_title("Referências por documento"); ax.legend()
    fig.tight_layout(); save_chart(fig, "05_dist_referencias")

    return {"secoes_por_doc": describe(secs), "paras_por_doc": describe(paras),
            "deo_coverage": deo_cov, "refs_por_doc": describe(refs_vals)}


# ══════════════════════════════════════════════════════════════════════════════
# BLOCO 3 — Discurso
# ══════════════════════════════════════════════════════════════════════════════

def stats_discourse() -> dict:
    section("BLOCO 3 — Discurso: estatísticas da extração LLM")
    if not DISCOURSE_DIR.exists():
        print(f"  {DISCOURSE_DIR} não encontrado."); return {}

    docs = []
    for f in DISCOURSE_DIR.glob("*.json"):
        try: docs.append(json.loads(f.read_text(encoding="utf-8")))
        except: pass
    ok = [d for d in docs if d.get("status") == "ok"]
    print(f"  JSONs: {len(docs):,}  |  OK: {len(ok):,}")

    def cpd(field):
        return [sum(len(s.get(field,[])) for s in d.get("sections",[])) for d in ok]

    claims_pd  = cpd("claims"); limits_pd = cpd("limitations")
    fw_pd      = cpd("future_work"); cont_pd = cpd("contributions")

    describe(claims_pd,  "Claims por documento")
    describe(limits_pd,  "Limitações por documento")
    describe(fw_pd,      "Trabalhos futuros por documento")
    describe(cont_pd,    "Contribuições por documento")

    g = gini(claims_pd)
    print(f"\n  Gini (claims): {g:.3f}  "
          f"({'alta concentração' if g>0.6 else 'moderada' if g>0.4 else 'baixa'})")

    all_claims = [c for d in ok for s in d.get("sections",[])
                  for c in s.get("claims",[]) if isinstance(c,str)]
    all_limits = [l for d in ok for s in d.get("sections",[])
                  for l in s.get("limitations",[]) if isinstance(l,str)]
    describe([len(c) for c in all_claims], "Comprimento dos claims", "chars")
    describe([len(l) for l in all_limits], "Comprimento das limitações", "chars")

    rhet = Counter(s.get("rhetorical_type","?")
                   for d in ok for s in d.get("sections",[]))
    total_secs = sum(rhet.values())
    print(f"\n  Tipos retóricos LLM:")
    for t, n in rhet.most_common(8):
        print(f"    {t:<15} {n:>5} ({100*n/total_secs:.1f}%)")

    kw_all  = [kw.lower().strip() for d in ok for s in d.get("sections",[])
               for kw in s.get("keywords_inferred",[])
               if isinstance(kw,str) and len(kw)>3]
    kw_freq = Counter(kw_all)

    src_c = Counter(s.get("source","?") for d in ok for s in d.get("sections",[]))
    print(f"\n  Fonte das seções:")
    for src, n in src_c.most_common():
        print(f"    {src:<25} {n:>5} ({100*n/total_secs:.1f}%)")

    # Spearman tamanho × claims
    sec_len  = [s.get("text_length",0) for d in ok for s in d.get("sections",[])]
    sec_clms = [len(s.get("claims",[])) for d in ok for s in d.get("sections",[])]
    rho, p_rho = spearmanr(sec_len, sec_clms)
    print(f"\n  Correlação tamanho seção × claims: ρ={rho:.3f}  p={p_rho:.2e}")

    # Zipf
    freqs = np.sort(list(kw_freq.values()))[::-1]
    freqs = freqs[freqs > 0]
    ranks = np.arange(1, len(freqs)+1)
    slope, intercept, r_val, _, _ = linregress(np.log(ranks), np.log(freqs))

    # Gráfico 6 — Distribuição claims + boxplot
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    axes[0].hist(claims_pd, bins=35, color=PALETTE[0], alpha=0.85, edgecolor="white")
    axes[0].axvline(np.median(claims_pd), color="red", linestyle="--",
                    label=f"Mediana={np.median(claims_pd):.0f}")
    axes[0].set_title("Claims por documento"); axes[0].set_xlabel("Nº claims"); axes[0].legend()
    bp = axes[1].boxplot([claims_pd, limits_pd, fw_pd, cont_pd],
                          patch_artist=True, notch=False,
                          medianprops={"color":"red","linewidth":2})
    for patch, c in zip(bp["boxes"], PALETTE):
        patch.set_facecolor(c); patch.set_alpha(0.7)
    axes[1].set_xticklabels(["Claims","Limitações","Fut.Work","Contribs"])
    axes[1].set_title("Elementos de discurso por documento"); axes[1].set_ylabel("Itens")
    fig.tight_layout(); save_chart(fig, "06_dist_claims_boxplot")

    # Gráfico 7 — Tipos retóricos
    top_rh = rhet.most_common(6)
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.pie([n for _,n in top_rh], labels=[t for t,_ in top_rh],
           autopct="%1.1f%%", colors=PALETTE[:len(top_rh)], startangle=140)
    ax.set_title("Tipos retóricos identificados pelo LLM")
    save_chart(fig, "07_tipos_retoricos_llm")

    # Gráfico 8 — Zipf
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.scatter(np.log(ranks), np.log(freqs), s=4, alpha=0.4, color=PALETTE[0])
    ax.plot(np.log(ranks), slope*np.log(ranks)+intercept, "r--", linewidth=1.5,
            label=f"α={abs(slope):.2f}, R²={r_val**2:.2f}")
    ax.set_xlabel("log(rank)"); ax.set_ylabel("log(frequência)")
    ax.set_title("Distribuição de keywords — lei de Zipf"); ax.legend()
    fig.tight_layout(); save_chart(fig, "08_zipf_keywords")

    # Gráfico 9 — Correlação tamanho × claims
    n_s = min(3000, len(sec_len))
    idx = np.random.default_rng(42).choice(len(sec_len), n_s, replace=False)
    xs  = np.array(sec_len)[idx]; ys = np.array(sec_clms)[idx]
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.scatter(xs, ys, s=8, alpha=0.3, color=PALETTE[0])
    m, b = np.polyfit(xs, ys, 1)
    xr   = np.linspace(0, np.percentile(xs, 97), 100)
    ax.plot(xr, m*xr+b, "r--", linewidth=1.5, label=f"ρ={rho:.2f} (Spearman)")
    ax.set_xlim(0, np.percentile(xs, 97)); ax.set_ylim(-0.5, np.percentile(ys,97)+1)
    ax.set_xlabel("Tamanho da seção (chars)"); ax.set_ylabel("Claims extraídos")
    ax.set_title("Correlação: tamanho da seção × claims"); ax.legend()
    fig.tight_layout(); save_chart(fig, "09_correlacao_secao_claims")

    return {"n_ok": len(ok), "claims_pd": describe(claims_pd),
            "limits_pd": describe(limits_pd), "fw_pd": describe(fw_pd),
            "gini_claims": round(g,4),
            "rho_tamanho_claims": round(rho,3),
            "top_keywords": [{"kw":k,"freq":n} for k,n in kw_freq.most_common(20)],
            "zipf_alpha": round(abs(slope),3), "zipf_r2": round(r_val**2,3),
            "fontes_secoes": dict(src_c.most_common())}


# ══════════════════════════════════════════════════════════════════════════════
# BLOCO 4 — Por área (com DISTINCT)
# ══════════════════════════════════════════════════════════════════════════════

def stats_by_area() -> dict:
    section("BLOCO 4 — Análise por área CNPq")

    rows = sparql("""
SELECT ?area_label
  (COUNT(DISTINCT ?doc)   AS ?n_docs)
  (COUNT(DISTINCT ?claim) AS ?n_claims)
  (COUNT(DISTINCT ?lim)   AS ?n_lims)
  (COUNT(DISTINCT ?fw)    AS ?n_fw)
WHERE {
  ?doc a fabio:Work .
  ?doc dcterms:subject ?area .
  FILTER(STRSTARTS(STR(?area), "CNPQ::"))
  BIND(REPLACE(STR(?area), ".*::", "") AS ?area_label)
  OPTIONAL { ?doc discourse:hasClaim ?claim }
  OPTIONAL { ?doc discourse:hasLimitation ?lim }
  OPTIONAL { ?doc discourse:hasFutureWork ?fw }
}
GROUP BY ?area_label ORDER BY DESC(?n_docs) LIMIT 15
""")
    print(f"\n  {'Área':<45} {'docs':>5} {'claims/doc':>11} {'lims/doc':>9}")
    print(f"  {'-'*73}")
    area_stats = []
    for r in rows:
        area = r["area_label"][:43]; n = int(r["n_docs"])
        if n == 0: continue
        cpd = int(r["n_claims"])/n; lpd = int(r["n_lims"])/n; fpd = int(r["n_fw"])/n
        print(f"  {area:<45} {n:>5} {cpd:>11.2f} {lpd:>9.2f}")
        area_stats.append({"area": area, "n_docs": n,
                           "claims_per_doc": round(cpd,2), "lims_per_doc": round(lpd,2),
                           "fw_per_doc": round(fpd,2)})

    if area_stats:
        cpds = [a["claims_per_doc"] for a in area_stats]
        print(f"\n  Razão max/min claims/doc: {max(cpds)/max(min(cpds),0.01):.1f}×")

        # Gráfico 10
        areas_l = [a["area"][:28] for a in area_stats[:12]]
        cpd_l   = [a["claims_per_doc"] for a in area_stats[:12]]
        lpd_l   = [a["lims_per_doc"]   for a in area_stats[:12]]
        x = np.arange(len(areas_l)); w = 0.4
        fig, ax = plt.subplots(figsize=(12, 5))
        ax.bar(x-w/2, cpd_l, w, label="Claims/doc",    color=PALETTE[0], alpha=0.85)
        ax.bar(x+w/2, lpd_l, w, label="Limitações/doc",color=PALETTE[3], alpha=0.85)
        ax.set_xticks(x); ax.set_xticklabels(areas_l, rotation=35, ha="right", fontsize=8)
        ax.set_ylabel("Itens por documento")
        ax.set_title("Claims e limitações por documento — por área CNPq")
        ax.legend(); fig.tight_layout(); save_chart(fig, "10_claims_por_area")

    return {"por_area": area_stats}


# ══════════════════════════════════════════════════════════════════════════════
# BLOCO 5 — Evolução temporal (com DISTINCT)
# ══════════════════════════════════════════════════════════════════════════════

def stats_temporal() -> dict:
    section("BLOCO 5 — Evolução temporal")

    rows = sparql("""
SELECT ?ano
  (COUNT(DISTINCT ?doc)   AS ?n_docs)
  (COUNT(DISTINCT ?claim) AS ?n_claims)
  (COUNT(DISTINCT ?lim)   AS ?n_lims)
WHERE {
  ?doc a fabio:Work .
  ?doc dcterms:date ?date .
  BIND(SUBSTR(STR(?date),1,4) AS ?ano)
  FILTER(?ano >= "2017" && ?ano <= "2025")
  OPTIONAL { ?doc discourse:hasClaim ?claim }
  OPTIONAL { ?doc discourse:hasLimitation ?lim }
}
GROUP BY ?ano ORDER BY ?ano
""")
    print(f"\n  {'Ano':<6} {'Docs':>6} {'Claims/doc':>11} {'Lims/doc':>9}")
    print(f"  {'-'*36}")
    temporal = []
    for r in rows:
        n = int(r["n_docs"])
        if n == 0: continue
        ano = r["ano"]; cpd = int(r["n_claims"])/n; lpd = int(r["n_lims"])/n
        print(f"  {ano:<6} {n:>6} {cpd:>11.2f} {lpd:>9.2f}")
        temporal.append({"ano": ano, "n_docs": n,
                         "claims_per_doc": round(cpd,2), "lims_per_doc": round(lpd,2)})

    if not temporal:
        return {}
    anos_i = [int(t["ano"]) for t in temporal]
    cpds   = [t["claims_per_doc"] for t in temporal]
    lpds   = [t["lims_per_doc"]   for t in temporal]
    ndocs  = [t["n_docs"] for t in temporal]

    # Gráfico 11
    fig, ax1 = plt.subplots(figsize=(10, 5))
    ax2 = ax1.twinx()
    ax1.plot(anos_i, cpds, "o-", color=PALETTE[0], linewidth=2, label="Claims/doc")
    ax1.plot(anos_i, lpds, "s--", color=PALETTE[3], linewidth=1.5, label="Lims/doc")
    ax2.bar(anos_i, ndocs, alpha=0.18, color="gray", label="Nº docs")
    ax1.set_xlabel("Ano"); ax1.set_ylabel("Itens por documento")
    ax2.set_ylabel("Nº de documentos", color="gray")
    ax1.set_title("Evolução temporal: densidade de discurso e volume do corpus")
    l1, lb1 = ax1.get_legend_handles_labels(); l2, lb2 = ax2.get_legend_handles_labels()
    ax1.legend(l1+l2, lb1+lb2, loc="upper left")
    fig.tight_layout(); save_chart(fig, "11_evolucao_temporal")

    return {"por_ano": temporal}


# ══════════════════════════════════════════════════════════════════════════════
# BLOCO 6 — Análise de rede do grafo RDF
# ══════════════════════════════════════════════════════════════════════════════

def stats_network(n_ttl: int = 150) -> dict:
    section("BLOCO 6 — Análise de rede do grafo RDF (amostra)")

    ttl_files = sorted(RDF_DIR.glob("*.ttl"))[:n_ttl]
    if not ttl_files:
        print(f"  Nenhum TTL em {RDF_DIR}"); return {}
    print(f"  Construindo grafo a partir de {len(ttl_files)} TTLs...")

    G = nx.DiGraph(); node_types: dict[str,str] = {}

    for ttl_path in ttl_files:
        try:
            txt = ttl_path.read_text(encoding="utf-8", errors="replace")
            subj = None
            for line in txt.splitlines():
                line = line.strip()
                m_s = re.match(r'^(base:\S+)\s+a\s+(.+?)\s*[;.]', line)
                if m_s:
                    subj = m_s.group(1); tipos = m_s.group(2)
                    if   "DoctoralThesis"    in tipos: node_types[subj] = "Tese"
                    elif "MastersThesis"     in tipos: node_types[subj] = "Dissertação"
                    elif "ScientificClaim"   in tipos: node_types[subj] = "Claim"
                    elif "Limitation"        in tipos: node_types[subj] = "Limitação"
                    elif "FutureWork"        in tipos: node_types[subj] = "FutureWork"
                    elif "Paragraph"         in tipos: node_types[subj] = "Parágrafo"
                    elif "Section"           in tipos: node_types[subj] = "Seção"
                    elif "ListOfReferences"  in tipos: node_types[subj] = "Referências"
                    else:                              node_types[subj] = "Outro"
                    G.add_node(subj)
                if subj and re.search(r"(po:contains|discourse:has)", line):
                    obj_m = re.search(r'(base:\S+?)\s*[;,.]?\s*$', line)
                    if obj_m:
                        G.add_edge(subj, obj_m.group(1))
        except Exception:
            pass

    print(f"  Nós: {G.number_of_nodes():,}  |  Arestas: {G.number_of_edges():,}")
    if G.number_of_nodes() == 0:
        return {}

    in_vals  = list(dict(G.in_degree()).values())
    out_vals = list(dict(G.out_degree()).values())
    describe(in_vals,  "In-degree")
    describe(out_vals, "Out-degree")

    # Top nós por in-degree
    top_in = sorted(G.in_degree(), key=lambda x: -x[1])[:5]
    print(f"\n  Top nós por in-degree:")
    for node, deg in top_in:
        print(f"    {node:<50} in={deg}  tipo={node_types.get(node,'?')}")

    # Componentes
    comps = list(nx.connected_components(G.to_undirected()))
    sizes = sorted([len(c) for c in comps], reverse=True)
    print(f"\n  Componentes: {len(comps)}  |  Maior: {sizes[0]} nós ({100*sizes[0]/G.number_of_nodes():.1f}%)")

    tipo_counter = Counter(node_types.values())
    print(f"\n  Tipos de nós:")
    for t, n in tipo_counter.most_common(): print(f"    {t:<20} {n:>5}")

    # Gráfico 12 — Distribuição de grau
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    for ax, data, color, label in zip(axes,
        [in_vals, out_vals], [PALETTE[0], PALETTE[2]],
        ["In-degree","Out-degree"]):
        ax.hist([v for v in data if v>0], bins=30, color=color, alpha=0.8, edgecolor="white")
        ax.set_title(f"Distribuição {label} (log y)")
        ax.set_xlabel(label); ax.set_yscale("log")
    fig.tight_layout(); save_chart(fig, "12_degree_distribution")

    # Gráfico 13 — Tipos de nós
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.barh(list(tipo_counter.keys()), list(tipo_counter.values()),
            color=PALETTE[:len(tipo_counter)], alpha=0.85)
    ax.set_xlabel("Nº de nós"); ax.set_title("Tipos de nós no grafo RDF (amostra)")
    fig.tight_layout(); save_chart(fig, "13_tipos_nos_grafo")

    return {"n_nos": G.number_of_nodes(), "n_arestas": G.number_of_edges(),
            "n_componentes": len(comps),
            "maior_comp_pct": round(100*sizes[0]/G.number_of_nodes(),1) if comps else 0,
            "in_degree": describe(in_vals), "out_degree": describe(out_vals),
            "tipos_nos": dict(tipo_counter.most_common())}


# ══════════════════════════════════════════════════════════════════════════════
# BLOCO 7 — TEI
# ══════════════════════════════════════════════════════════════════════════════

def stats_tei(max_files: int = 400) -> dict:
    section("BLOCO 7 — TEI: estrutura bruta dos documentos")
    tei_files = sorted(TEI_DIR.glob("*.tei.xml"))[:max_files]
    if not tei_files:
        print(f"  Nenhum TEI em {TEI_DIR}"); return {}
    ns = {"tei": TEI_NS}
    n_secs, n_paras, body_lens, n_refs, depths = [], [], [], [], []
    print(f"  Analisando {len(tei_files)} TEIs...")
    for path in tei_files:
        try:
            root = ET.parse(path).getroot()
            body = root.find(".//tei:body", ns)
            if body is None: continue
            n_secs.append(len(body.findall(".//tei:div", ns)))
            n_paras.append(len(body.findall(".//tei:p", ns)))
            body_lens.append(len(" ".join(body.itertext())))
            n_refs.append(len(root.findall(".//tei:listBibl/tei:biblStruct", ns)))
            def max_depth(el, d=0):
                ch = el.findall("tei:div", ns)
                return d if not ch else max(max_depth(c,d+1) for c in ch)
            depths.append(max_depth(body))
        except Exception:
            pass
    describe(n_secs,   "Seções por TEI")
    describe(n_paras,  "Parágrafos por TEI")
    describe(body_lens,"Tamanho do body","chars")
    describe(n_refs,   "Referências por TEI")
    depth_c = Counter(depths)
    print(f"\n  Profundidade de aninhamento:")
    for d in sorted(depth_c): print(f"    {d} níveis : {depth_c[d]:>4} docs")

    # Gráfico 14
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.hist(body_lens, bins=35, color=PALETTE[5], alpha=0.85, edgecolor="white")
    ax.axvline(np.median(body_lens), color="red", linestyle="--",
               label=f"Mediana={np.median(body_lens)/1000:.0f}k chars")
    ax.set_xlabel("Tamanho do body (chars)")
    ax.set_title("Distribuição do tamanho dos documentos (TEI)")
    ax.legend(); fig.tight_layout(); save_chart(fig, "14_tei_body_size")

    return {"secoes": describe(n_secs), "paras": describe(n_paras),
            "body_chars": describe(body_lens), "refs": describe(n_refs),
            "profundidade": dict(depth_c)}


# ══════════════════════════════════════════════════════════════════════════════
# RELATÓRIO MARKDOWN
# ══════════════════════════════════════════════════════════════════════════════

def generate_markdown(results: dict) -> str:
    ts   = datetime.now().strftime("%d/%m/%Y %H:%M")
    man  = results.get("manifest", {})
    gr   = results.get("grafo", {})
    disc = results.get("discurso", {})
    net  = results.get("rede", {})
    tmp  = results.get("temporal", {})

    md = f"""# Análise Estatística do Corpus — Grafo de Conhecimento de Discurso Científico

**Projeto:** Busca e Mineração de Texto — PESC/COPPE/UFRJ  
**Gerado em:** {ts}

---

## 1. Corpus (metadados OAI-PMH)

| Métrica | Valor |
|---|---|
| Total de registros no manifest | {man.get('total','—'):,} |
| Teses de Doutorado | {man.get('tipos',{}).get('Tese','—')} |
| Dissertações de Mestrado | {man.get('tipos',{}).get('Dissertação','—')} |
| Documentos em português | {man.get('idiomas',{}).get('por','—')} |
| Documentos em inglês | {man.get('idiomas',{}).get('eng','—')} |
| Comprimento médio do título | {man.get('titulo_chars',{}).get('media','—')} chars (DP={man.get('titulo_chars',{}).get('dp','—')}) |
| Subjects CNPq por documento (mediana) | {man.get('n_subjects',{}).get('mediana','—')} |

![Distribuição temporal](charts/01_distribuicao_temporal.png)
![Tipos e idiomas](charts/02_tipos_idiomas.png)

---

## 2. Estrutura do Grafo (DoCO/DEO)

| Métrica | Média | Mediana | DP | P95 |
|---|---|---|---|---|
| Seções DoCO por documento | {gr.get('secoes_por_doc',{}).get('media','—')} | {gr.get('secoes_por_doc',{}).get('mediana','—')} | {gr.get('secoes_por_doc',{}).get('dp','—')} | {gr.get('secoes_por_doc',{}).get('p95','—')} |
| Parágrafos por documento | {gr.get('paras_por_doc',{}).get('media','—')} | {gr.get('paras_por_doc',{}).get('mediana','—')} | {gr.get('paras_por_doc',{}).get('dp','—')} | {gr.get('paras_por_doc',{}).get('p95','—')} |
| Referências por documento | {gr.get('refs_por_doc',{}).get('media','—')} | {gr.get('refs_por_doc',{}).get('mediana','—')} | {gr.get('refs_por_doc',{}).get('dp','—')} | {gr.get('refs_por_doc',{}).get('p95','—')} |

### Cobertura dos tipos retóricos DEO

| Tipo DEO | Documentos | % do corpus |
|---|---|---|
"""
    for tipo, v in gr.get("deo_coverage", {}).items():
        md += f"| `{tipo}` | {v['n_docs']:,} | {v['pct']}% |\n"

    md += f"""
![Distribuição seções e parágrafos](charts/03_dist_secoes_paragrafos.png)
![Cobertura DEO](charts/04_cobertura_deo.png)
![Distribuição de referências](charts/05_dist_referencias.png)

---

## 3. Discurso Científico (extração LLM)

| Elemento | Média/doc | Mediana | DP | P95 |
|---|---|---|---|---|
| Claims | {disc.get('claims_pd',{}).get('media','—')} | {disc.get('claims_pd',{}).get('mediana','—')} | {disc.get('claims_pd',{}).get('dp','—')} | {disc.get('claims_pd',{}).get('p95','—')} |
| Limitações | {disc.get('limits_pd',{}).get('media','—')} | {disc.get('limits_pd',{}).get('mediana','—')} | {disc.get('limits_pd',{}).get('dp','—')} | {disc.get('limits_pd',{}).get('p95','—')} |
| Trabalhos futuros | {disc.get('fw_pd',{}).get('media','—')} | {disc.get('fw_pd',{}).get('mediana','—')} | {disc.get('fw_pd',{}).get('dp','—')} | {disc.get('fw_pd',{}).get('p95','—')} |

### Concentração da extração

**Coeficiente de Gini (claims):** `{disc.get('gini_claims','—')}`

> O coeficiente de Gini mede concentração: 0 = distribuição uniforme, 1 = máxima concentração.
> Valor `{disc.get('gini_claims','—')}` indica {'alta concentração — poucos documentos concentram a maioria dos claims' if disc.get('gini_claims',0) > 0.6 else 'concentração moderada — distribuição heterogênea mas não extrema' if disc.get('gini_claims',0) > 0.4 else 'concentração baixa — distribuição relativamente uniforme'}.

### Correlação tamanho de seção × claims extraídos

**Spearman ρ = `{disc.get('rho_tamanho_claims','—')}`** — {'correlação positiva significativa: seções maiores produzem sistematicamente mais claims' if disc.get('rho_tamanho_claims',0) > 0.3 else 'correlação fraca'}.

### Distribuição de keywords — Lei de Zipf

**Expoente α = `{disc.get('zipf_alpha','—')}` (R² = `{disc.get('zipf_r2','—')}`)**

> A lei de Zipf clássica (vocabulário de língua natural) tem α ≈ 1. Expoente menor
> indica cauda mais longa — termos técnicos distribuem-se de forma menos concentrada
> que vocabulário geral, o que é esperado em um corpus científico especializado.

### Top 10 keywords inferidas pelo LLM

| # | Keyword | Frequência |
|---|---|---|
"""
    for i, kw in enumerate(disc.get("top_keywords", [])[:10], 1):
        md += f"| {i} | {kw['kw']} | {kw['freq']} |\n"

    md += f"""
![Distribuição claims](charts/06_dist_claims_boxplot.png)
![Tipos retóricos LLM](charts/07_tipos_retoricos_llm.png)
![Zipf keywords](charts/08_zipf_keywords.png)
![Correlação seção × claims](charts/09_correlacao_secao_claims.png)

---

## 4. Análise por Área CNPq

![Claims por área](charts/10_claims_por_area.png)

---

## 5. Evolução Temporal

| Ano | Documentos | Claims/doc | Limitações/doc |
|---|---|---|---|
"""
    for t in tmp.get("por_ano", []):
        md += f"| {t['ano']} | {t['n_docs']} | {t['claims_per_doc']} | {t['lims_per_doc']} |\n"

    md += f"""
![Evolução temporal](charts/11_evolucao_temporal.png)

---

## 6. Análise de Rede do Grafo RDF

A análise de rede examina o grafo RDF como uma estrutura de dados relacional,
revelando a topologia das conexões entre documentos, seções, parágrafos e elementos de discurso.

| Métrica | Valor |
|---|---|
| Nós no subgrafo analisado | {net.get('n_nos','—'):,} |
| Arestas (relações) | {net.get('n_arestas','—'):,} |
| Componentes conectados | {net.get('n_componentes','—')} |
| Maior componente | {net.get('maior_comp_pct','—')}% dos nós |
| In-degree médio | {net.get('in_degree',{}).get('media','—')} |
| In-degree máximo | {net.get('in_degree',{}).get('max','—')} |
| Out-degree médio | {net.get('out_degree',{}).get('media','—')} |

### Distribuição de tipos de nós

| Tipo | Nós |
|---|---|
"""
    for tipo, n in net.get("tipos_nos", {}).items():
        md += f"| {tipo} | {n:,} |\n"

    md += f"""
A distribuição de grau em escala logarítmica (gráfico abaixo) revela se o grafo
segue uma lei de potência (comum em grafos de conhecimento reais), onde poucos nós
concentram a maior parte das conexões.

![Distribuição de grau](charts/12_degree_distribution.png)
![Tipos de nós no grafo](charts/13_tipos_nos_grafo.png)

---

## 7. Estrutura Bruta dos Documentos (TEI)

![Tamanho dos documentos](charts/14_tei_body_size.png)

---

*Relatório gerado automaticamente por `corpus_statistics.py` — {ts}*
"""
    return md


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--export",   default=None)
    parser.add_argument("--skip-tei", action="store_true")
    args = parser.parse_args()

    try:
        r = requests.get(f"{FUSEKI_URL}/$/ping", auth=(FUSEKI_USER, FUSEKI_PASS), timeout=5)
        assert r.status_code == 200
        print("✓ Fuseki acessível")
    except Exception:
        print("✗ Fuseki não acessível"); sys.exit(1)

    CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Gráficos → {CHARTS_DIR}\n")

    results = {}
    results["manifest"]  = stats_manifest()
    results["grafo"]     = stats_graph_structure()
    results["discurso"]  = stats_discourse()
    results["por_area"]  = stats_by_area()
    results["temporal"]  = stats_temporal()
    results["rede"]      = stats_network(n_ttl=150)
    if not args.skip_tei:
        results["tei"]   = stats_tei()

    # Markdown
    md_path = _HERE / "data" / "corpus_analysis.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(generate_markdown(results), encoding="utf-8")
    n_charts = len(list(CHARTS_DIR.glob("*.png")))
    print(f"\n✓ Relatório: {md_path}")
    print(f"✓ Gráficos : {CHARTS_DIR}  ({n_charts} arquivos)")

    if args.export:
        Path(args.export).parent.mkdir(parents=True, exist_ok=True)
        with open(args.export, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2,
                      default=lambda x: None if isinstance(x, float)
                      and (x != x or abs(x) == float("inf")) else x)
        print(f"✓ JSON     : {args.export}")


if __name__ == "__main__":
    main()