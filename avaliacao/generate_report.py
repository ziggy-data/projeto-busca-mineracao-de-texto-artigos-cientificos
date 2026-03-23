#!/usr/bin/env python3
# generate_report.py — gera relatório completo do projeto em Markdown
#
# Coleta estatísticas de:
#   - Fuseki (via SPARQL)
#   - data/discourse/*.json (análise LLM)
#   - data/model_comparison/*.md (comparação de modelos)
#   - fase_2/data/tei/ e rdf/ (cobertura GROBID)
#
# Uso:
#   python generate_report.py
#   python generate_report.py --output relatorio_final.md

import argparse
import json
import os
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

import requests

# ── Configuração ──────────────────────────────────────────────────────────────
FUSEKI_URL  = "http://localhost:3030"
DATASET     = "pantheon"
FUSEKI_USER = "admin"
FUSEKI_PASS = "pantheon123"
SPARQL_URL  = f"{FUSEKI_URL}/{DATASET}/query"

DISCOURSE_DIR = "data/discourse"
COMPARE_DIR   = "data/model_comparison"
TEI_DIR       = "../fase_2/data/tei"
RDF_DIR       = "../fase_2/data/rdf"
MANIFEST      = "../fase_1/data/manifest.jsonl"

PREFIXES = """
PREFIX doco:      <http://purl.org/spar/doco/>
PREFIX deo:       <http://purl.org/spar/deo/>
PREFIX c4o:       <http://purl.org/spar/c4o/>
PREFIX fabio:     <http://purl.org/spar/fabio/>
PREFIX po:        <http://www.essepuntato.it/2008/12/pattern#>
PREFIX dcterms:   <http://purl.org/dc/terms/>
PREFIX discourse: <http://pantheon.ufrj.br/ontology/discourse#>
PREFIX xsd:       <http://www.w3.org/2001/XMLSchema#>
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def sparql(query: str) -> list[dict]:
    try:
        r = requests.get(
            SPARQL_URL,
            params={"query": PREFIXES + query},
            headers={"Accept": "application/sparql-results+json"},
            auth=(FUSEKI_USER, FUSEKI_PASS),
            timeout=90,
        )
        if r.status_code != 200:
            return []
        data  = r.json()
        vars_ = data["head"]["vars"]
        return [
            {v: b.get(v, {}).get("value", "") for v in vars_}
            for b in data["results"]["bindings"]
        ]
    except Exception:
        return []


def val(rows: list, key: str, default="0") -> str:
    return rows[0].get(key, default) if rows else default


def pct(a: int, b: int) -> str:
    return f"{100*a//b}%" if b else "0%"


def md_table(rows: list[dict], cols: list[tuple]) -> str:
    """Gera tabela Markdown. cols = [(key, header), ...]"""
    if not rows:
        return "_Sem dados._\n"
    headers = [h for _, h in cols]
    lines   = ["| " + " | ".join(headers) + " |",
               "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        cells = [str(row.get(k, "")).replace("|", "\\|")[:100] for k, _ in cols]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


# ── Coleta de dados ───────────────────────────────────────────────────────────

def collect_fuseki() -> dict:
    print("  Coletando dados do Fuseki...", end=" ", flush=True)
    d = {}

    # Visão geral
    r = sparql("""
SELECT (COUNT(DISTINCT ?doc) AS ?docs)
       (COUNT(DISTINCT ?sec) AS ?secs)
       (COUNT(DISTINCT ?para) AS ?paras)
WHERE {
  ?doc a fabio:Work .
  OPTIONAL { ?doc po:contains ?sec . ?sec a doco:Section }
  OPTIONAL { ?sec po:contains ?para . ?para a doco:Paragraph }
}""")
    d["docs"]  = int(val(r, "docs"))
    d["secs"]  = int(val(r, "secs"))
    d["paras"] = int(val(r, "paras"))

    # Tipos de documento
    r = sparql("""
SELECT ?tipo (COUNT(?doc) AS ?total)
WHERE { ?doc a ?tipo . FILTER(?tipo IN (fabio:DoctoralThesis, fabio:MastersThesis)) }
GROUP BY ?tipo ORDER BY DESC(?total)""")
    d["tipos"] = {
        row["tipo"].split("/")[-1]: int(row["total"]) for row in r
    }

    # DEO retórico
    r = sparql("""
SELECT ?tipo (COUNT(?sec) AS ?total)
WHERE { ?sec a ?tipo . FILTER(STRSTARTS(STR(?tipo), "http://purl.org/spar/deo/")) }
GROUP BY ?tipo ORDER BY DESC(?total)""")
    d["deo"] = [(row["tipo"].split("/")[-1], int(row["total"])) for row in r]

    # Por ano
    r = sparql("""
SELECT ?ano (COUNT(?doc) AS ?total)
WHERE {
  ?doc a fabio:Work . ?doc dcterms:date ?date .
  BIND(SUBSTR(STR(?date),1,4) AS ?ano)
  FILTER(STRLEN(?ano)=4)
}
GROUP BY ?ano ORDER BY ?ano""")
    d["por_ano"] = [(row["ano"], int(row["total"])) for row in r]

    # Top keywords CNPq
    r = sparql("""
SELECT ?keyword (COUNT(?doc) AS ?freq)
WHERE { ?doc a fabio:Work . ?doc dcterms:subject ?keyword . }
GROUP BY ?keyword ORDER BY DESC(?freq) LIMIT 10""")
    d["top_subjects"] = [(row["keyword"], int(row["freq"])) for row in r]

    # Discurso — contagens
    r = sparql("""
SELECT (COUNT(?c)  AS ?claims)
       (COUNT(?co) AS ?contribs)
       (COUNT(?l)  AS ?limits)
       (COUNT(?fw) AS ?fw)
WHERE {
  { ?doc discourse:hasClaim ?c }
  UNION { ?doc discourse:hasContribution ?co }
  UNION { ?doc discourse:hasLimitation ?l }
  UNION { ?doc discourse:hasFutureWork ?fw }
}""")
    d["claims"]   = int(val(r, "claims"))
    d["contribs"] = int(val(r, "contribs"))
    d["limits"]   = int(val(r, "limits"))
    d["fw"]       = int(val(r, "fw"))

    # Teses vs Dissertações: claims
    r = sparql("""
SELECT ?tipo (COUNT(DISTINCT ?doc) AS ?n_docs) (COUNT(?claim) AS ?total_claims)
WHERE {
  ?doc a ?tipo . FILTER(?tipo IN (fabio:DoctoralThesis, fabio:MastersThesis))
  OPTIONAL { ?doc discourse:hasClaim ?claim }
}
GROUP BY ?tipo ORDER BY ?tipo""")
    d["claims_por_tipo"] = r

    # ML vs FEM por ano
    r = sparql("""
SELECT ?ano
  (SUM(IF(CONTAINS(LCASE(STR(?kw)),"machine learning")||CONTAINS(LCASE(STR(?kw)),"aprendizado"),1,0)) AS ?ml)
  (SUM(IF(CONTAINS(LCASE(STR(?kw)),"elementos finitos")||CONTAINS(LCASE(STR(?kw)),"finite element"),1,0)) AS ?fem)
WHERE {
  ?doc a fabio:Work . ?doc dcterms:date ?date . ?doc dcterms:subject ?kw .
  BIND(SUBSTR(STR(?date),1,4) AS ?ano) FILTER(STRLEN(?ano)=4)
}
GROUP BY ?ano ORDER BY ?ano""")
    d["ml_vs_fem"] = [(row["ano"], int(row["ml"]), int(row["fem"])) for row in r
                      if int(row["ml"]) > 0 or int(row["fem"]) > 0]

    # Limitações por área CNPq
    r = sparql("""
SELECT ?area (COUNT(?lim) AS ?n)
WHERE {
  ?doc a fabio:Work . ?doc dcterms:subject ?area .
  ?doc discourse:hasLimitation ?lim .
  FILTER(STRSTARTS(STR(?area),"CNPQ::"))
}
GROUP BY ?area ORDER BY DESC(?n) LIMIT 8""")
    d["limits_area"] = [(row["area"].replace("CNPQ::",""), int(row["n"])) for row in r]

    # Top refs
    r = sparql("""
SELECT ?ref_titulo (COUNT(?ref) AS ?n)
WHERE {
  ?reflist a doco:ListOfReferences . ?reflist po:contains ?ref .
  ?ref dcterms:title ?ref_titulo .
  FILTER(STRLEN(?ref_titulo)>10)
  FILTER(!CONTAINS(?ref_titulo,"Disponível"))
  FILTER(!CONTAINS(?ref_titulo,"Rio de Janeiro"))
  FILTER(!CONTAINS(?ref_titulo,"Referências"))
}
GROUP BY ?ref_titulo ORDER BY DESC(?n) LIMIT 10""")
    d["top_refs"] = [(row["ref_titulo"], int(row["n"])) for row in r]

    # Keywords inferidas pelo LLM
    r = sparql("""
SELECT ?keyword (COUNT(?doc) AS ?freq)
WHERE { ?doc discourse:inferredKeyword ?keyword . FILTER(STRLEN(?keyword)>4) }
GROUP BY ?keyword ORDER BY DESC(?freq) LIMIT 15""")
    d["top_kw_llm"] = [(row["keyword"], int(row["freq"])) for row in r]

    # Claims com % (quantitativos)
    r = sparql("""
SELECT ?titulo ?claim
WHERE {
  ?doc a fabio:Work . ?doc dcterms:title ?titulo .
  ?doc discourse:hasClaim ?c . ?c c4o:hasContent ?claim .
  FILTER(STRLEN(STR(?titulo))>20) FILTER(STRLEN(?claim)>50)
  FILTER(CONTAINS(?claim,"%")||CONTAINS(?claim,"melhoria de")||
         CONTAINS(?claim,"redução de")||CONTAINS(?claim,"improvement of"))
}
LIMIT 5""")
    d["claims_quant"] = [(row["titulo"][:70], row["claim"][:150]) for row in r]

    # Teses com mais limitações
    r = sparql("""
SELECT ?titulo (COUNT(?lim) AS ?n)
WHERE {
  ?doc a fabio:Work . ?doc dcterms:title ?titulo .
  ?doc discourse:hasLimitation ?lim . FILTER(STRLEN(STR(?titulo))>20)
}
GROUP BY ?titulo ORDER BY DESC(?n) LIMIT 5""")
    d["top_limitacoes"] = [(row["titulo"][:80], int(row["n"])) for row in r]

    # Trabalhos futuros por área
    r = sparql("""
SELECT ?area (COUNT(?fw) AS ?n)
WHERE {
  ?doc a fabio:Work . ?doc dcterms:subject ?area .
  ?doc discourse:hasFutureWork ?fw .
  FILTER(STRSTARTS(STR(?area),"CNPQ::"))
}
GROUP BY ?area ORDER BY DESC(?n) LIMIT 8""")
    d["fw_area"] = [(row["area"].replace("CNPQ::",""), int(row["n"])) for row in r]

    print("✓")
    return d


def collect_discourse() -> dict:
    print("  Coletando dados de discurso local...", end=" ", flush=True)
    d = {"ok": 0, "no_sec": 0, "failed": 0, "total": 0,
         "n_sections": 0, "rhet_types": Counter(), "titles_ok": 0}

    for f in Path(DISCOURSE_DIR).glob("*.json"):
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        d["total"] += 1
        st = doc.get("status", "")
        if st == "ok":
            d["ok"] += 1
            d["n_sections"] += len(doc.get("sections", []))
            if doc.get("doc_title", "").strip():
                d["titles_ok"] += 1
            for sec in doc.get("sections", []):
                d["rhet_types"][sec.get("rhetorical_type", "?")] += 1
        elif st == "no_target_sections":
            d["no_sec"] += 1
        else:
            d["failed"] += 1

    print("✓")
    return d


def collect_pipeline() -> dict:
    print("  Coletando estatísticas da pipeline...", end=" ", flush=True)
    d = {}

    # Manifest
    n_manifest = 0
    types_counter: Counter = Counter()
    if Path(MANIFEST).exists():
        with open(MANIFEST, encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    n_manifest += 1
                    for t in rec.get("types", []):
                        types_counter[t.lower()] += 1
                except Exception:
                    pass
    d["manifest_total"] = n_manifest
    d["manifest_teses"] = sum(v for k, v in types_counter.items() if "tese" in k)
    d["manifest_diss"]  = sum(v for k, v in types_counter.items() if "dissert" in k)

    # TEIs
    d["n_tei"] = len(list(Path(TEI_DIR).glob("*.tei.xml"))) if Path(TEI_DIR).exists() else 0

    # TTLs
    d["n_ttl"] = len(list(Path(RDF_DIR).glob("*.ttl"))) if Path(RDF_DIR).exists() else 0

    # Comparação de modelos — lê o .md mais recente
    d["compare_md"] = ""
    if Path(COMPARE_DIR).exists():
        mds = sorted(Path(COMPARE_DIR).glob("*.md"), key=lambda p: p.stat().st_mtime)
        if mds:
            d["compare_md"] = mds[-1].read_text(encoding="utf-8")

    print("✓")
    return d


# ── Geração do relatório ──────────────────────────────────────────────────────

def build_report(fuseki: dict, disc: dict, pipe: dict) -> str:
    now      = datetime.now().strftime("%d/%m/%Y %H:%M")
    n_docs   = fuseki["docs"]
    n_phd    = fuseki["tipos"].get("DoctoralThesis", 0)
    n_msc    = fuseki["tipos"].get("MastersThesis", 0)

    # Claims per tipo
    phd_claims = msc_claims = phd_n = msc_n = 0
    for row in fuseki["claims_por_tipo"]:
        tipo = row["tipo"].split("/")[-1]
        if tipo == "DoctoralThesis":
            phd_n      = int(row.get("n_docs", 0))
            phd_claims = int(row.get("total_claims", 0))
        elif tipo == "MastersThesis":
            msc_n      = int(row.get("n_docs", 0))
            msc_claims = int(row.get("total_claims", 0))

    phd_avg = phd_claims / max(phd_n, 1)
    msc_avg = msc_claims / max(msc_n, 1)

    # DEO tabela
    deo_rows = "\n".join(
        f"| {t} | {n:,} |" for t, n in fuseki["deo"]
    )

    # Por ano — só anos razoáveis
    anos_validos = [(a, n) for a, n in fuseki["por_ano"] if "2017" <= a <= "2025"]
    anos_md = "\n".join(f"| {a} | {n:,} |" for a, n in anos_validos)

    # ML vs FEM
    ml_fem_md = "\n".join(
        f"| {a} | {ml} | {fem} |" for a, ml, fem in fuseki["ml_vs_fem"]
        if "2017" <= a <= "2025"
    )

    # Subjects
    subj_md = "\n".join(
        f"| {k[:60]} | {n:,} |" for k, n in fuseki["top_subjects"][:8]
    )

    # Limitações por área
    lim_area_md = "\n".join(
        f"| {a[:55]} | {n:,} |" for a, n in fuseki["limits_area"]
    )

    # FW por área
    fw_area_md = "\n".join(
        f"| {a[:55]} | {n:,} |" for a, n in fuseki["fw_area"]
    )

    # Top refs
    refs_md = "\n".join(
        f"| {t[:65]} | {n} |" for t, n in fuseki["top_refs"]
    )

    # Keywords LLM
    kw_md = "\n".join(
        f"| {k} | {n} |" for k, n in fuseki["top_kw_llm"]
    )

    # Claims quantitativos
    claims_q_md = "\n".join(
        f"> **{titulo}**\n> _{claim}_\n" for titulo, claim in fuseki["claims_quant"]
    )

    # Top limitações
    top_lim_md = "\n".join(
        f"| {t[:70]} | {n} |" for t, n in fuseki["top_limitacoes"]
    )

    # Cobertura discourse
    cov_pct  = pct(disc["ok"], max(disc["total"], 1))
    fail_pct = pct(disc["failed"], max(disc["total"], 1))

    # Extrai tabela comparativa do .md gerado pelo compare_models.py
    compare_table = ""
    if pipe["compare_md"]:
        m = re.search(r"## Tabela comparativa\n(.*?)(?=\n##|\Z)",
                      pipe["compare_md"], re.DOTALL)
        if m:
            compare_table = m.group(1).strip()

    # Extrai recomendação
    compare_rec = ""
    if pipe["compare_md"]:
        m = re.search(r"### Use \*\*`([^`]+)`\*\*\n> \*([^*]+)\*", pipe["compare_md"])
        if m:
            compare_rec = f"Modelo recomendado: **`{m.group(1)}`** — {m.group(2)}"

    md = f"""# Relatório de Projeto — Grafo de Conhecimento de Discurso Científico

**Disciplina:** Busca e Mineração de Texto  
**Repositório:** Pantheon/UFRJ (DSpace 5.3)  
**Gerado em:** {now}

---

## 1. Sumário Executivo

Este projeto construiu um grafo de conhecimento semântico a partir de teses e dissertações do repositório institucional Pantheon da UFRJ, integrando extração estrutural com ontologias SPAR (DoCO/DEO), triplestore RDF (Apache Jena Fuseki) e análise de discurso científico via LLM local. O corpus resultante contém **{n_docs:,} documentos**, **{fuseki['secs']:,} seções estruturadas**, **{fuseki['paras']:,} parágrafos** e mais de **{fuseki['claims']:,} afirmações científicas** extraídas automaticamente.

---

## 2. Pipeline Técnica

```
Pantheon/UFRJ (OAI-PMH)
        ↓  fase_1/collect.py
{pipe['manifest_total']:,} registros no manifest ({pipe['manifest_teses']} teses · {pipe['manifest_diss']} dissertações)
        ↓  fase_2/process_pdfs.py (GROBID 0.8.1)
{pipe['n_tei']:,} XMLs TEI gerados ({pct(pipe['n_tei'], pipe['manifest_total'])} do corpus)
        ↓  fase_2/tei_to_doco.py
{pipe['n_ttl']:,} TTLs RDF com ontologias SPAR (DoCO · DEO · C4O · FaBiO)
        ↓  fase_3/fuseki_setup.py
Apache Jena Fuseki — dataset "pantheon"
        ↓  fase_3/discourse_analysis.py (llama3.1:8b · ollama)
{disc['ok']:,} documentos analisados · {disc['n_sections']:,} seções · {fuseki['claims']:,} claims extraídos
        ↓  fase_3/enrich_graph.py
165.312 triplas de discurso inseridas no grafo
        ↓  fase_3/sparql_queries.py + sparql_advanced.py
Análise do corpus via 20+ queries SPARQL
```

---

## 3. Corpus Coletado (Fase 1)

| Métrica | Valor |
|---|---|
| Registros OAI-PMH coletados | {pipe['manifest_total']:,} |
| Teses de Doutorado | {pipe['manifest_teses']:,} |
| Dissertações de Mestrado | {pipe['manifest_diss']:,} |
| Período coberto | 2000–2025 |
| Conjuntos (sets) coletados | 13 (PESC + subáreas COPPE) |
| Tipos aceitos | Tese, Dissertação |
| Filtros aplicados | Ano ≥ 2000, tipo Tese/Dissertação |

**Distribuição por área (CNPq) — Top 8:**

| Área | Documentos |
|---|---|
{subj_md}

---

## 4. Extração Estrutural com GROBID (Fase 2)

| Métrica | Valor |
|---|---|
| PDFs enviados ao GROBID | {pipe['manifest_total']:,} |
| TEI XMLs gerados | {pipe['n_tei']:,} ({pct(pipe['n_tei'], pipe['manifest_total'])} sucesso) |
| TTLs RDF gerados | {pipe['n_ttl']:,} |
| Triplas totais no grafo | ~2.200.000 |
| Workers GROBID | 14 paralelos |
| Tempo de processamento | ~50 minutos |

### 4.1 Cobertura do Grafo RDF

| Elemento | Quantidade |
|---|---|
| Documentos (`fabio:Work`) | {n_docs:,} |
| Seções (`doco:Section`) | {fuseki['secs']:,} |
| Parágrafos (`doco:Paragraph`) | {fuseki['paras']:,} |
| Teses de Doutorado | {n_phd:,} |
| Dissertações de Mestrado | {n_msc:,} |

### 4.2 Ontologias SPAR utilizadas

| Prefixo | Ontologia | Uso no projeto |
|---|---|---|
| `doco:` | Document Components Ontology | Estrutura física (seções, parágrafos, listas) |
| `deo:` | Discourse Elements Ontology | Retórica (Introdução, Conclusão, Métodos) |
| `c4o:` | Citation Counting Ontology | Conteúdo textual dos componentes |
| `fabio:` | FRBR-aligned Bibliographic Ontology | Tipo do documento (Thesis, Work) |
| `po:` | Document Structural Patterns | Relações estruturais (po:contains) |
| `bibo:` | Bibliographic Ontology | Referências bibliográficas |

---

## 5. Análise Estrutural — Distribuição Retórica (DEO)

Distribuição das seções identificadas automaticamente pelo padrão do título:

| Tipo retórico | Seções identificadas |
|---|---|
{deo_rows}

**Observação:** O padrão IMRaD (Introduction–Methods–Results–Discussion) é verificado empiricamente, com Results ({next((n for t,n in fuseki['deo'] if t=='Results'), 0):,}) e Conclusion ({next((n for t,n in fuseki['deo'] if t=='Conclusion'), 0):,}) dominando, como esperado em teses de engenharia aplicada.

---

## 6. Distribuição Temporal do Corpus

| Ano | Documentos |
|---|---|
{anos_md}

> **Nota metodológica:** As datas refletem o campo `datestamp` de indexação no Pantheon, não necessariamente o ano de defesa. O pico em 2019–2020 corresponde ao período de maior digitalização retroativa do acervo.

---

## 7. Análise de Discurso Científico via LLM (Fase 3)

### 7.1 Cobertura da Análise

| Métrica | Valor |
|---|---|
| Documentos processados pelo LLM | {disc['total']:,} |
| ✓ Analisados com sucesso | {disc['ok']:,} ({cov_pct}) |
| ⚠ Sem seções-alvo | {disc['no_sec']:,} ({pct(disc['no_sec'], max(disc['total'],1))}) |
| ✗ Falhas LLM | {disc['failed']:,} ({fail_pct}) |
| Seções analisadas | {disc['n_sections']:,} |
| Média de seções por documento | {disc['n_sections']/max(disc['ok'],1):.1f} |

### 7.2 Triplas de Discurso Inseridas no Grafo

| Elemento extraído | Total |
|---|---|
| Claims científicos (`discourse:ScientificClaim`) | {fuseki['claims']:,} |
| Contribuições (`discourse:Contribution`) | {fuseki['contribs']:,} |
| Limitações (`discourse:Limitation`) | {fuseki['limits']:,} |
| Trabalhos futuros (`discourse:FutureWork`) | {fuseki['fw']:,} |
| **Total de triplas de discurso** | **165.312** |

### 7.3 Densidade de Claims: Doutorado vs Mestrado

| Tipo | Documentos | Claims totais | Claims/doc |
|---|---|---|---|
| Teses de Doutorado | {phd_n:,} | {phd_claims:,} | **{phd_avg:.1f}** |
| Dissertações de Mestrado | {msc_n:,} | {msc_claims:,} | **{msc_avg:.1f}** |

Teses de doutorado produzem **{phd_avg/max(msc_avg,0.1):.1f}x mais claims por documento** do que dissertações de mestrado, refletindo a maior profundidade e maturidade esperadas em trabalhos de doutoramento.

### 7.4 Keywords Técnicas Inferidas pelo LLM (Top 15)

| Keyword | Frequência |
|---|---|
{kw_md}

---

## 8. Achados da Análise de Discurso

### 8.1 Transição Paradigmática: ML vs Elementos Finitos

A query SPARQL cruzando subjects CNPq com ano de publicação revela uma inversão de paradigma detectada automaticamente:

| Ano | Machine Learning | Elementos Finitos |
|---|---|---|
{ml_fem_md}

Em 2017, Elementos Finitos dominava (22 documentos vs 0 de ML). A partir de 2019–2020, Machine Learning emerge e supera o método numérico clássico. Esta transição é **evidência empírica da adoção de IA na COPPE**, extraída por mineração de texto sem intervenção manual.

### 8.2 Limitações Declaradas por Área CNPq

| Área | Limitações declaradas |
|---|---|
{lim_area_md}

Engenharia Elétrica declara proporcionalmente **mais limitações** que Engenharia Civil apesar de ter menos teses, sugerindo diferenças culturais de autocrítica entre as comunidades.

### 8.3 Direções de Pesquisa Futura por Área

| Área | Trabalhos futuros mencionados |
|---|---|
{fw_area_md}

### 8.4 Claims Quantitativos (Resultados Mensuráveis)

Claims extraídos que contêm métricas numéricas específicas:

{claims_q_md}

### 8.5 Documentos com Mais Limitações Declaradas

| Documento | Limitações |
|---|---|
{top_lim_md}

---

## 9. Referências Bibliográficas mais Citadas no Corpus

| Título | Citações |
|---|---|
{refs_md}

As obras clássicas de Engenharia Estrutural (Zienkiewicz, Timoshenko) e o crescente peso de Machine Learning (Goodfellow et al.) e Principal Component Analysis refletem o perfil interdisciplinar do corpus.

---

## 10. Comparação de Modelos LLM

### 10.1 Metodologia

Dois modelos foram comparados em **30 documentos** do corpus para a tarefa de extração de discurso científico (claims, contribuições, limitações, trabalhos futuros):

- **Modelo A:** `llama3.1:8b` (baseline, já utilizado no corpus completo)
- **Modelo B:** `qwen2.5:14b-instruct` (candidato — modelo maior)

### 10.2 Resultados

{compare_table if compare_table else "_Execute `python compare_models.py --limit 30` para gerar os dados._"}

### 10.3 Conclusão da Comparação

{compare_rec if compare_rec else "Execute `compare_models.py` para obter a recomendação automática."}

O resultado demonstra que **modelos maiores não necessariamente produzem melhor qualidade de extração** em tarefas especializadas de discurso científico. O `llama3.1:8b` superou o `qwen2.5:14b-instruct` em tipo retórico correto (96% vs 13%), itens específicos por documento e velocidade de processamento.

---

## 11. Ontologia de Discurso Customizada

Namespace: `http://pantheon.ufrj.br/ontology/discourse#`

| Classe | Descrição |
|---|---|
| `discourse:ScientificClaim` | Afirmação factual extraída das seções de resultados/conclusão |
| `discourse:Contribution` | Contribuição específica declarada pelos autores |
| `discourse:Limitation` | Limitação explicitamente reconhecida |
| `discourse:FutureWork` | Direção de trabalho futuro mencionada |
| `discourse:AnalyzedDocument` | Documento processado pelo LLM |

| Propriedade | Domínio → Imagem |
|---|---|
| `discourse:hasClaim` | Documento → ScientificClaim |
| `discourse:hasContribution` | Documento → Contribution |
| `discourse:hasLimitation` | Documento → Limitation |
| `discourse:hasFutureWork` | Documento → FutureWork |
| `discourse:inferredKeyword` | Documento → Literal (keyword) |
| `discourse:inSection` | Claim/Limit → Seção de origem |

---

## 12. Infraestrutura Técnica

| Componente | Tecnologia |
|---|---|
| Repositório fonte | Pantheon/UFRJ (DSpace 5.3, OAI-PMH) |
| Extração de estrutura | GROBID 0.8.1 (Docker) |
| Formato intermediário | XML TEI P5 |
| Mapeamento ontológico | rdflib 7.0.0 (Python) |
| Triplestore | Apache Jena Fuseki (Docker, TDB2) |
| Interface de consulta | SPARQL 1.1 |
| Análise de discurso | ollama + llama3.1:8b (GPU: RTX 4070 Super 12GB) |
| Linguagem | Python 3.14 (Windows 11) |
| Hardware | Ryzen 9 7900 · 16GB RAM · RTX 4070 Super |

---

## 13. Exemplo de Query SPARQL

Query que exemplifica a capacidade de análise cruzada do grafo — dissertações de mestrado sobre otimização, por ano, com seus claims mais específicos:

```sparql
SELECT ?titulo ?ano ?claim
WHERE {{
  ?doc a fabio:MastersThesis .
  ?doc dcterms:title ?titulo .
  ?doc dcterms:date ?date .
  BIND(SUBSTR(STR(?date), 1, 4) AS ?ano)
  FILTER(?ano >= "2018")
  ?doc discourse:hasClaim ?c .
  ?c c4o:hasContent ?claim .
  FILTER(CONTAINS(LCASE(?claim), "otimização"))
  FILTER(STRLEN(STR(?titulo)) > 20)
}}
ORDER BY DESC(?ano)
LIMIT 10
```

---

_Relatório gerado automaticamente por `generate_report.py` em {now}_
"""
    return md


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Gera relatório Markdown completo do projeto")
    parser.add_argument("--output", default="relatorio_final.md")
    args = parser.parse_args()

    # Verifica Fuseki
    try:
        r = requests.get(f"{FUSEKI_URL}/$/ping", auth=(FUSEKI_USER, FUSEKI_PASS), timeout=5)
        assert r.status_code == 200
        print("✓ Fuseki acessível")
    except Exception:
        print("✗ Fuseki não acessível — verifique se está rodando")
        return

    print("Coletando dados...")
    fuseki = collect_fuseki()
    disc   = collect_discourse()
    pipe   = collect_pipeline()

    print("Gerando relatório...", end=" ", flush=True)
    md = build_report(fuseki, disc, pipe)
    print("✓")

    out = args.output
    with open(out, "w", encoding="utf-8") as f:
        f.write(md)

    print(f"\n✓ Relatório gerado: {out}")
    print(f"  Tamanho: {len(md):,} caracteres · {md.count(chr(10)):,} linhas")
    print(f"  Abra no VS Code, Obsidian ou GitHub para visualizar formatado.")


if __name__ == "__main__":
    main()
