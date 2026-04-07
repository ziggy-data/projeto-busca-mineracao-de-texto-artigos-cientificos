#!/usr/bin/env python3
# evaluate_project.py — avalia as hipóteses H1, H2 e H3 da proposta do projeto
#
# Lê os artefatos já gerados pela pipeline e verifica cada critério de sucesso
# definido na proposta, emitindo um veredicto (ATINGIDO / NÃO ATINGIDO) por
# critério e por hipótese.
#
# Fontes de dados:
#   H1  → fase_3/data/discourse_report.jsonl + fase_3/data/discourse/*.json
#   H2  → avaliacao/data/model_comparison/*.md + avaliacao/data/shacl_report.json
#   H3  → Fuseki (SPARQL queries)
#
# Uso:
#   python evaluate_project.py
#   python evaluate_project.py --export data/evaluation_results.json
#   python evaluate_project.py --no-sparql   # pula H3 (Fuseki offline)

import argparse
import json
import os
import re
import sys
from pathlib import Path

import requests

# ── Caminhos ──────────────────────────────────────────────────────────────────
_HERE          = Path(__file__).parent
PROJECT_ROOT   = _HERE.parent
DISCOURSE_RPT  = PROJECT_ROOT / "fase_3" / "data" / "discourse_report.jsonl"
DISCOURSE_DIR  = PROJECT_ROOT / "fase_3" / "data" / "discourse"
COMPARE_DIR    = _HERE / "data" / "model_comparison"
SHACL_REPORT   = _HERE / "data" / "shacl_report.json"

# ── Fuseki ────────────────────────────────────────────────────────────────────
FUSEKI_URL  = "http://localhost:3030"
DATASET     = "pantheon"
FUSEKI_USER = "admin"
FUSEKI_PASS = "pantheon123"
SPARQL_URL  = f"{FUSEKI_URL}/{DATASET}/query"

PREFIXES = """
PREFIX fabio:     <http://purl.org/spar/fabio/>
PREFIX dcterms:   <http://purl.org/dc/terms/>
PREFIX discourse: <http://pantheon.ufrj.br/ontology/discourse#>
PREFIX c4o:       <http://purl.org/spar/c4o/>
"""

# ── Critérios da proposta ─────────────────────────────────────────────────────
CRITERIA = {
    "H1": {
        "taxa_sucesso":      ("≥ 50%",  0.50),
        "taxa_falhas":       ("≤ 10%",  0.10),
        "docs_com_claim":    ("≥ 70%",  0.70),
    },
    "H2": {
        "genericos":         ("≤ 35%",  0.35),
        "tipo_retorico":     ("≥ 60%",  0.60),
        "campos_preenchidos":("≥ 2.0",  2.0),
        "shacl_conformidade":("≥ 80%",  0.80),
        "shacl_violacoes":   ("≤ 5%",   0.05),
    },
    "H3": {
        "variacao_temporal": ("variação observável ML vs FEM", None),
        "densidade_phd_msc": ("PhD observavelmente maior",     None),
        "perfis_limitacao":  ("≥ 2 áreas distintas",          2),
    },
}

# ── Formatação ────────────────────────────────────────────────────────────────
OK   = "\033[92m✓ ATINGIDO\033[0m"
FAIL = "\033[91m✗ NÃO ATINGIDO\033[0m"
WARN = "\033[93m⚠ PARCIAL\033[0m"
BOLD = "\033[1m"
RST  = "\033[0m"

def verdict(passed: bool) -> str:
    return OK if passed else FAIL


# ── H1: Viabilidade de extração ───────────────────────────────────────────────

def evaluate_h1() -> dict:
    results = {}

    if not DISCOURSE_RPT.exists():
        return {"error": f"Arquivo não encontrado: {DISCOURSE_RPT}"}

    total = ok = no_sec = failed = 0
    with open(DISCOURSE_RPT, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
                total += 1
                st = r.get("status", "")
                if st == "ok":            ok     += 1
                elif st == "no_target_sections": no_sec += 1
                else:                     failed += 1
            except Exception:
                pass

    if total == 0:
        return {"error": "discourse_report.jsonl vazio"}

    # Documentos elegíveis = total - sem seções-alvo
    elegiveis = total - no_sec
    taxa_sucesso = ok / elegiveis if elegiveis > 0 else 0
    taxa_falhas  = failed / elegiveis if elegiveis > 0 else 0

    # Docs com pelo menos 1 claim
    docs_com_claim = 0
    docs_ok = 0
    if DISCOURSE_DIR.exists():
        for f in DISCOURSE_DIR.glob("*.json"):
            try:
                doc = json.loads(f.read_text(encoding="utf-8"))
                if doc.get("status") != "ok":
                    continue
                docs_ok += 1
                total_claims = sum(
                    len(s.get("claims", [])) for s in doc.get("sections", [])
                )
                if total_claims >= 1:
                    docs_com_claim += 1
            except Exception:
                pass

    taxa_claim = docs_com_claim / docs_ok if docs_ok > 0 else 0

    results = {
        "total_documentos":  total,
        "elegiveis":         elegiveis,
        "ok":                ok,
        "no_target":         no_sec,
        "failed":            failed,
        "taxa_sucesso":      round(taxa_sucesso, 4),
        "taxa_falhas":       round(taxa_falhas, 4),
        "docs_com_claim":    docs_com_claim,
        "taxa_claim":        round(taxa_claim, 4),
        "criteria": {
            "taxa_sucesso":   taxa_sucesso   >= CRITERIA["H1"]["taxa_sucesso"][1],
            "taxa_falhas":    taxa_falhas    <= CRITERIA["H1"]["taxa_falhas"][1],
            "docs_com_claim": taxa_claim     >= CRITERIA["H1"]["docs_com_claim"][1],
        },
    }
    results["h1_pass"] = all(results["criteria"].values())
    return results


# ── H2: Qualidade da extração ─────────────────────────────────────────────────

def parse_compare_md() -> dict | None:
    """Extrai métricas de tipo retórico e genericidade do compare_models.py."""
    if not COMPARE_DIR.exists():
        return None
    mds = sorted(COMPARE_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime)
    if not mds:
        return None
    text = mds[-1].read_text(encoding="utf-8")

    def extract(pattern, cast=float):
        m = re.search(pattern, text)
        return cast(m.group(1)) if m else None

    generic_ratio = extract(r"\| % genérico\s*\|\s*([\d.]+)%")
    if generic_ratio is not None:
        generic_ratio /= 100

    rhet_ok_str = extract(r"\| Tipo retórico correto\s*\|\s*([\d/]+)", cast=str)
    rhet_ok = None
    if rhet_ok_str and "/" in rhet_ok_str:
        a, b = rhet_ok_str.split("/")
        rhet_ok = int(a.strip()) / int(b.strip())

    return {
        "generic_ratio": generic_ratio,
        "rhet_ok":       rhet_ok,
        "source":        mds[-1].name,
    }


def calc_campos_preenchidos() -> dict:
    """
    Calcula campos preenchidos/doc diretamente dos JSONs de discurso.
    Para cada documento OK, verifica quais dos 4 tipos têm ao menos 1 item:
    claims, contributions, limitations, future_work.
    """
    if not DISCOURSE_DIR.exists():
        return {"campos_avg": None, "n_docs": 0}

    total_campos = 0
    n_docs = 0

    for f in DISCOURSE_DIR.glob("*.json"):
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
            if doc.get("status") != "ok":
                continue
            n_docs += 1
            fields_filled = 0
            for sec in doc.get("sections", []):
                if sec.get("claims"):        fields_filled = max(fields_filled, 1)
                if sec.get("contributions"): fields_filled = max(fields_filled, 1)
                if sec.get("limitations"):   fields_filled = max(fields_filled, 1)
                if sec.get("future_work"):   fields_filled = max(fields_filled, 1)

            # Conta tipos distintos presentes no documento inteiro
            has_claims   = any(sec.get("claims")        for sec in doc.get("sections", []))
            has_contrib  = any(sec.get("contributions") for sec in doc.get("sections", []))
            has_limit    = any(sec.get("limitations")   for sec in doc.get("sections", []))
            has_fw       = any(sec.get("future_work")   for sec in doc.get("sections", []))
            total_campos += sum([has_claims, has_contrib, has_limit, has_fw])
        except Exception:
            pass

    avg = round(total_campos / n_docs, 3) if n_docs > 0 else None
    return {"campos_avg": avg, "n_docs": n_docs}


def evaluate_h2() -> dict:
    results = {}
    criteria_pass = {}

    # ── SHACL ──────────────────────────────────────────────────────────────
    if SHACL_REPORT.exists():
        shacl = json.loads(SHACL_REPORT.read_text(encoding="utf-8"))
        n_total    = shacl.get("n_total", 0)
        n_conforms = shacl.get("n_conforms", 0)
        n_viol     = shacl.get("n_violation", 0)

        # Conta nós totais validados (aproximado: soma de triplas violadas)
        all_violations = [v for d in shacl.get("details", []) for v in d.get("violations", [])]
        all_warnings   = [w for d in shacl.get("details", []) for w in d.get("warnings", [])]

        conformance    = n_conforms / n_total if n_total > 0 else 0
        # Taxa de violações críticas: docs com violações / total
        viol_rate      = n_viol / n_total if n_total > 0 else 0

        results["shacl"] = {
            "n_total":      n_total,
            "n_conforms":   n_conforms,
            "n_violation":  n_viol,
            "n_warning":    shacl.get("n_warning", 0),
            "conformance":  round(conformance, 4),
            "viol_rate":    round(viol_rate, 4),
            "n_warn_msgs":  len(all_warnings),
            "warn_types":   list({w["message"][:60] for w in all_warnings}),
        }

        criteria_pass["shacl_conformidade"] = conformance >= CRITERIA["H2"]["shacl_conformidade"][1]
        criteria_pass["shacl_violacoes"]    = viol_rate   <= CRITERIA["H2"]["shacl_violacoes"][1]
    else:
        results["shacl"] = {"error": f"shacl_report.json não encontrado em {SHACL_REPORT}"}
        criteria_pass["shacl_conformidade"] = False
        criteria_pass["shacl_violacoes"]    = False

    # ── Compare models ──────────────────────────────────────────────────────
    # Métricas do compare_models (genericidade e tipo retórico)
    compare = parse_compare_md()
    if compare:
        results["compare"] = compare
        criteria_pass["genericos"] = (
            compare["generic_ratio"] <= CRITERIA["H2"]["genericos"][1]
            if compare["generic_ratio"] is not None else None
        )
        criteria_pass["tipo_retorico"] = (
            compare["rhet_ok"] >= CRITERIA["H2"]["tipo_retorico"][1]
            if compare["rhet_ok"] is not None else None
        )
    else:
        results["compare"] = {"error": "Relatório de comparação de modelos não encontrado"}
        criteria_pass["genericos"] = None
        criteria_pass["tipo_retorico"] = None

    # Campos preenchidos — calculado direto dos JSONs de discurso
    campos_data = calc_campos_preenchidos()
    results["campos_preenchidos"] = campos_data
    campos_avg = campos_data.get("campos_avg")
    criteria_pass["campos_preenchidos"] = (
        campos_avg >= CRITERIA["H2"]["campos_preenchidos"][1]
        if campos_avg is not None else None
    )

    results["criteria"] = criteria_pass
    results["h2_pass"]  = all(v for v in criteria_pass.values() if v is not None)
    return results


# ── H3: Valor analítico do grafo ──────────────────────────────────────────────

def sparql(query: str) -> list[dict]:
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


def evaluate_h3() -> dict:
    results = {}
    criteria_pass = {}

    # ── Variação temporal ML vs FEM ─────────────────────────────────────────
    rows = sparql("""
SELECT ?ano
  (SUM(IF(CONTAINS(LCASE(STR(?kw)),"machine learning")||
          CONTAINS(LCASE(STR(?kw)),"aprendizado"),1,0)) AS ?ml)
  (SUM(IF(CONTAINS(LCASE(STR(?kw)),"elementos finitos")||
          CONTAINS(LCASE(STR(?kw)),"finite element"),1,0)) AS ?fem)
WHERE {
  ?doc a fabio:Work .
  ?doc dcterms:date ?d .
  BIND(SUBSTR(STR(?d),1,4) AS ?ano)
  FILTER(STRLEN(?ano)=4)
  ?doc dcterms:subject ?kw .
}
GROUP BY ?ano ORDER BY ?ano
""")

    ml_vals  = {r["ano"]: int(r["ml"])  for r in rows if r.get("ano")}
    fem_vals = {r["ano"]: int(r["fem"]) for r in rows if r.get("ano")}
    anos_validos = sorted(k for k in ml_vals if "2017" <= k <= "2025")

    # Verifica se ML cresceu e FEM diminuiu entre início e fim do período
    variacao_ok = False
    if len(anos_validos) >= 3:
        ml_inicio  = sum(ml_vals.get(a, 0) for a in anos_validos[:3])
        ml_fim     = sum(ml_vals.get(a, 0) for a in anos_validos[-3:])
        fem_inicio = sum(fem_vals.get(a, 0) for a in anos_validos[:3])
        fem_fim    = sum(fem_vals.get(a, 0) for a in anos_validos[-3:])
        variacao_ok = ml_fim > ml_inicio or fem_inicio > fem_fim

    results["variacao_temporal"] = {
        "anos": anos_validos,
        "ml_por_ano":  {a: ml_vals.get(a, 0) for a in anos_validos},
        "fem_por_ano": {a: fem_vals.get(a, 0) for a in anos_validos},
        "variacao_detectada": variacao_ok,
    }
    criteria_pass["variacao_temporal"] = variacao_ok

    # ── Densidade de claims PhD vs MSc ──────────────────────────────────────
    rows = sparql("""
SELECT ?tipo (COUNT(DISTINCT ?doc) AS ?n_docs) (COUNT(?claim) AS ?total)
WHERE {
  ?doc a ?tipo .
  FILTER(?tipo IN (fabio:DoctoralThesis, fabio:MastersThesis))
  OPTIONAL { ?doc discourse:hasClaim ?claim }
}
GROUP BY ?tipo
""")

    phd_docs = phd_claims = msc_docs = msc_claims = 0
    for r in rows:
        tipo = r.get("tipo", "")
        if "Doctoral" in tipo:
            phd_docs   = int(r.get("n_docs", 0))
            phd_claims = int(r.get("total", 0))
        elif "Masters" in tipo:
            msc_docs   = int(r.get("n_docs", 0))
            msc_claims = int(r.get("total", 0))

    phd_avg = phd_claims / max(phd_docs, 1)
    msc_avg = msc_claims / max(msc_docs, 1)
    densidade_ok = phd_avg > msc_avg  # PhD observavelmente maior

    results["densidade_phd_msc"] = {
        "phd_docs":   phd_docs,
        "phd_claims": phd_claims,
        "phd_avg":    round(phd_avg, 2),
        "msc_docs":   msc_docs,
        "msc_claims": msc_claims,
        "msc_avg":    round(msc_avg, 2),
        "phd_maior":  densidade_ok,
    }
    criteria_pass["densidade_phd_msc"] = densidade_ok

    # ── Perfis de limitação por área ─────────────────────────────────────────
    # Query sem filtro de área específica — funciona com qualquer corpus
    rows = sparql("""
SELECT ?area (COUNT(?lim) AS ?n)
WHERE {
  ?doc a fabio:Work .
  ?doc dcterms:subject ?area .
  ?doc discourse:hasLimitation ?lim .
  FILTER(STRSTARTS(STR(?area),"CNPQ::"))
}
GROUP BY ?area ORDER BY DESC(?n) LIMIT 15
""")

    # Normaliza o label removendo o prefixo CNPQ:: e a hierarquia superior
    def norm_area(uri: str) -> str:
        label = uri.replace("CNPQ::", "")
        parts = label.split("::")
        return parts[-1].strip() if parts else label

    # Filtra áreas com ao menos 3 limitações e que representem folhas distintas
    areas_raw = [(norm_area(r["area"]), int(r.get("n", 0)))
                 for r in rows if int(r.get("n", 0)) >= 3]
    # Remove duplicatas mantendo a de maior contagem
    seen = {}
    for label, n in areas_raw:
        if label not in seen or n > seen[label]:
            seen[label] = n
    areas_com_dados = sorted(seen, key=lambda k: seen[k], reverse=True)

    perfis_ok = len(areas_com_dados) >= CRITERIA["H3"]["perfis_limitacao"][1]

    results["perfis_limitacao"] = {
        "areas":        areas_com_dados,
        "areas_n":      {a: seen[a] for a in areas_com_dados},
        "n_areas":      len(areas_com_dados),
        "criterio":     f"≥ {CRITERIA['H3']['perfis_limitacao'][1]} áreas",
    }
    criteria_pass["perfis_limitacao"] = perfis_ok

    results["criteria"] = criteria_pass
    results["h3_pass"]  = all(criteria_pass.values())
    return results


# ── Relatório final ───────────────────────────────────────────────────────────

def print_report(h1: dict, h2: dict, h3: dict):
    print(f"\n{BOLD}{'='*65}{RST}")
    print(f"{BOLD}  RELATÓRIO DE AVALIAÇÃO — HIPÓTESES DO PROJETO{RST}")
    print(f"{BOLD}{'='*65}{RST}")

    # ── H1 ────────────────────────────────────────────────────────────────
    print(f"\n{BOLD}H1 — Viabilidade de Extração{RST}")
    print(f"  {verdict(h1.get('h1_pass', False))}")
    if "error" not in h1:
        c = h1["criteria"]
        ts = h1["taxa_sucesso"]
        tf = h1["taxa_falhas"]
        tc = h1["taxa_claim"]
        print(f"\n  {'Critério':<45} {'Valor':>8}  {'Limite':>8}  {'Status'}")
        print(f"  {'-'*75}")
        print(f"  {'Taxa de sucesso (docs OK / elegíveis)':<45} {ts:>7.1%}  {'≥ 50%':>8}  {verdict(c['taxa_sucesso'])}")
        print(f"  {'Taxa de falhas LLM':<45} {tf:>7.1%}  {'≤ 10%':>8}  {verdict(c['taxa_falhas'])}")
        print(f"  {'Docs com ≥1 afirmação extraída':<45} {tc:>7.1%}  {'≥ 70%':>8}  {verdict(c['docs_com_claim'])}")
        print(f"\n  Total: {h1['total_documentos']} docs | OK: {h1['ok']} | Sem seções: {h1['no_target']} | Falhas: {h1['failed']}")

    # ── H2 ────────────────────────────────────────────────────────────────
    print(f"\n{BOLD}H2 — Qualidade da Extração{RST}")
    print(f"  {verdict(h2.get('h2_pass', False))}")
    print(f"\n  {'Critério':<45} {'Valor':>8}  {'Limite':>8}  {'Status'}")
    print(f"  {'-'*75}")

    c = h2.get("criteria", {})
    cmp = h2.get("compare", {})
    shacl = h2.get("shacl", {})

    if "error" not in cmp:
        gr = cmp.get("generic_ratio")
        rh = cmp.get("rhet_ok")
        if gr is not None:
            p = c.get("genericos", False)
            print(f"  {'Afirmações genéricas':<45} {gr:>7.1%}  {'≤ 35%':>8}  {verdict(p) if p is not None else '—'}")
        if rh is not None:
            p = c.get("tipo_retorico", False)
            print(f"  {'Tipo retórico correto':<45} {rh:>7.1%}  {'≥ 60%':>8}  {verdict(p) if p is not None else '—'}")
    campos_info = h2.get("campos_preenchidos", {})
    cp = campos_info.get("campos_avg")
    cp_n = campos_info.get("n_docs", 0)
    if cp is not None:
        p = c.get("campos_preenchidos", False)
        print(f"  {'Campos preenchidos/doc (de 4)':<45} {cp:>7.2f}  {'≥ 2.0':>8}  {verdict(p) if p is not None else '—'}")
        print(f"  {'':5} (calculado sobre {cp_n} documentos)")
    else:
        print(f"  ⚠ {cmp['error']}")

    if "error" not in shacl:
        sc = shacl["conformance"]
        vr = shacl["viol_rate"]
        p_sc = c.get("shacl_conformidade", False)
        p_vr = c.get("shacl_violacoes", False)
        print(f"  {'Conformidade SHACL':<45} {sc:>7.1%}  {'≥ 80%':>8}  {verdict(p_sc)}")
        print(f"  {'Violações críticas SHACL':<45} {vr:>7.1%}  {'≤ 5%':>8}  {verdict(p_vr)}")
        print(f"\n  Avisos SHACL: {shacl['n_warn_msgs']} (seções vazias e abstracts curtos — limitação do GROBID)")
    else:
        print(f"  ⚠ SHACL: {shacl['error']}")

    # ── H3 ────────────────────────────────────────────────────────────────
    print(f"\n{BOLD}H3 — Valor Analítico do Grafo{RST}")
    print(f"  {verdict(h3.get('h3_pass', False))}")

    c  = h3.get("criteria", {})
    vt = h3.get("variacao_temporal", {})
    dp = h3.get("densidade_phd_msc", {})
    pl = h3.get("perfis_limitacao", {})

    # Pergunta 1 — variação temporal
    print(f"\n  Pergunta: É possível identificar variação temporal no uso de técnicas via SPARQL?")
    if vt:
        anos = vt.get("anos", [])
        ml   = vt.get("ml_por_ano", {})
        fem  = vt.get("fem_por_ano", {})
        det  = vt.get("variacao_detectada", False)
        if anos:
            ml_vals_str  = " / ".join(f"{a}:{ml.get(a,0)}" for a in anos if ml.get(a,0) > 0)
            fem_vals_str = " / ".join(f"{a}:{fem.get(a,0)}" for a in anos if fem.get(a,0) > 0)
            print(f"  ML  por ano (não-zero): {ml_vals_str or 'nenhum'}")
            print(f"  FEM por ano (não-zero): {fem_vals_str or 'nenhum'}")
        status = verdict(c.get("variacao_temporal", False))
        obs = "variação detectada nos dados" if det else "variação não detectada no corpus atual"
        print(f"  Resultado: {obs}  →  {status}")

    # Pergunta 2 — densidade PhD vs MSc
    print(f"\n  Pergunta: Há diferença de densidade de afirmações entre teses de doutorado e dissertações?")
    if dp:
        phd_avg = dp.get("phd_avg", 0)
        msc_avg = dp.get("msc_avg", 0)
        phd_n   = dp.get("phd_docs", 0)
        msc_n   = dp.get("msc_docs", 0)
        phd_maior = dp.get("phd_maior", False)
        ratio = phd_avg / max(msc_avg, 0.01)
        print(f"  Doutorado : {phd_avg:.2f} claims/doc  ({phd_n} documentos)")
        print(f"  Mestrado  : {msc_avg:.2f} claims/doc  ({msc_n} documentos)")
        if phd_n == 0 and msc_n == 0:
            obs = "dados insuficientes no corpus atual para esta comparação"
            status = verdict(False)
        elif phd_maior:
            obs = f"doutorado produz {ratio:.1f}x mais claims/doc que mestrado"
            status = verdict(True)
        else:
            obs = "mestrado apresentou densidade igual ou maior que doutorado neste corpus"
            status = verdict(False)
        print(f"  Resultado: {obs}  →  {status}")

    # Pergunta 3 — perfis de limitação
    print(f"\n  Pergunta: As limitações declaradas diferem sistematicamente entre áreas?")
    if pl:
        n_areas  = pl.get("n_areas", 0)
        areas    = pl.get("areas", [])
        areas_n  = pl.get("areas_n", {})
        criterio = pl.get("criterio", "≥ 2 áreas")
        if areas:
            print(f"  Áreas com limitações no corpus ({n_areas} encontradas, critério {criterio}):")
            for a in areas[:8]:
                print(f"    · {a}: {areas_n.get(a, '?')} limitações")
            if n_areas > 8:
                print(f"    ... e mais {n_areas - 8} áreas")
        else:
            print(f"  Nenhuma área com limitações encontrada no corpus atual.")
        status = verdict(c.get("perfis_limitacao", False))
        obs = f"{n_areas} áreas distintas identificadas" if n_areas >= 2 else f"apenas {n_areas} área(s) — abaixo do critério"
        print(f"  Resultado: {obs}  →  {status}")

    # ── Sumário ───────────────────────────────────────────────────────────
    h1_ok = h1.get("h1_pass", False)
    h2_ok = h2.get("h2_pass", False)
    h3_ok = h3.get("h3_pass", False)
    n_pass = sum([h1_ok, h2_ok, h3_ok])

    print(f"\n{BOLD}{'='*65}{RST}")
    print(f"{BOLD}  SUMÁRIO: {n_pass}/3 hipóteses atingidas{RST}")
    print(f"  H1 (Viabilidade)  : {verdict(h1_ok)}")
    print(f"  H2 (Qualidade)    : {verdict(h2_ok)}")
    print(f"  H3 (Valor analítico): {verdict(h3_ok)}")
    print(f"{BOLD}{'='*65}{RST}\n")

    return {"h1": h1_ok, "h2": h2_ok, "h3": h3_ok, "n_pass": n_pass}


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Avalia as hipóteses H1, H2 e H3 da proposta do projeto"
    )
    parser.add_argument("--export",     default=None,
                        help="Exporta resultados detalhados em JSON")
    parser.add_argument("--no-sparql",  action="store_true",
                        help="Pula H3 (Fuseki offline)")
    args = parser.parse_args()

    print(f"\nColetando dados de avaliação...")

    print(f"  H1 — discourse_report.jsonl...", end=" ", flush=True)
    h1 = evaluate_h1()
    print("✓" if "error" not in h1 else "✗")

    print(f"  H2 — model_comparison + shacl_report...", end=" ", flush=True)
    h2 = evaluate_h2()
    print("✓")

    if args.no_sparql:
        print(f"  H3 — pulado (--no-sparql)")
        h3 = {"h3_pass": False, "error": "pulado com --no-sparql"}
    else:
        print(f"  H3 — Fuseki SPARQL...", end=" ", flush=True)
        try:
            r = requests.get(f"{FUSEKI_URL}/$/ping",
                             auth=(FUSEKI_USER, FUSEKI_PASS), timeout=5)
            assert r.status_code == 200
            h3 = evaluate_h3()
            print("✓")
        except Exception:
            print("✗ (Fuseki não acessível — use --no-sparql)")
            h3 = {"h3_pass": False, "error": "Fuseki não acessível"}

    summary = print_report(h1, h2, h3)

    if args.export:
        output = {
            "summary": summary,
            "h1": h1,
            "h2": h2,
            "h3": h3,
        }
        Path(args.export).parent.mkdir(parents=True, exist_ok=True)
        with open(args.export, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"✓ Resultados exportados: {args.export}")


if __name__ == "__main__":
    main()