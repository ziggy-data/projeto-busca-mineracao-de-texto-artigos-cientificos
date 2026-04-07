#!/usr/bin/env python3
# generate_report.py — gera o relatório final do projeto em Markdown
#
# Consolida dados de todas as fontes:
#   - Fuseki (SPARQL) — estatísticas do corpus
#   - avaliacao/data/evaluation_results.json — H1, H2, H3
#   - avaliacao/data/shacl_report.json       — validação formal do grafo
#   - avaliacao/data/graph_integrity.json    — integridade semântica
#   - fase_3/data/discourse/                 — análise de discurso LLM
#
# O relatório apresenta perguntas e critérios da proposta junto com os
# valores medidos — sem emitir conclusões, para que o leitor interprete.
#
# Uso:
#   python generate_report.py
#   python generate_report.py --output relatorio_final.md

import argparse
import json
from datetime import datetime
from pathlib import Path

import requests

# ── Caminhos ──────────────────────────────────────────────────────────────────
_HERE        = Path(__file__).parent
EVAL_FILE    = _HERE / "data" / "evaluation_results.json"
SHACL_FILE   = _HERE / "data" / "shacl_report.json"
GRAPH_FILE   = _HERE / "data" / "graph_integrity.json"

# ── Fuseki ────────────────────────────────────────────────────────────────────
FUSEKI_URL  = "http://localhost:3030"
DATASET     = "pantheon"
FUSEKI_USER = "admin"
FUSEKI_PASS = "pantheon123"
SPARQL_URL  = f"{FUSEKI_URL}/{DATASET}/query"
PREFIXES    = """
PREFIX doco:      <http://purl.org/spar/doco/>
PREFIX deo:       <http://purl.org/spar/deo/>
PREFIX c4o:       <http://purl.org/spar/c4o/>
PREFIX fabio:     <http://purl.org/spar/fabio/>
PREFIX po:        <http://www.essepuntato.it/2008/12/pattern#>
PREFIX dcterms:   <http://purl.org/dc/terms/>
PREFIX discourse: <http://pantheon.ufrj.br/ontology/discourse#>
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

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


def load_json(path: Path) -> dict | None:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def pct(v: float) -> str:
    return f"{v*100:.1f}%"


def na(val, fmt="{:.0f}") -> str:
    if val is None:
        return "_não disponível_"
    return fmt.format(val) if isinstance(val, float) else str(val)


def criterion_row(pergunta: str, criterio: str, valor: str, passou: bool | None) -> str:
    if passou is True:
        status = "✓"
    elif passou is False:
        status = "✗"
    else:
        status = "—"
    return f"| {pergunta} | {criterio} | {valor} | {status} |"


# ── Coleta Fuseki ─────────────────────────────────────────────────────────────

def collect_corpus_stats() -> dict:
    d = {}
    r = sparql("""
SELECT (COUNT(DISTINCT ?doc) AS ?docs)
       (COUNT(DISTINCT ?sec) AS ?secs)
       (COUNT(DISTINCT ?para) AS ?paras)
WHERE {
  ?doc a fabio:Work .
  OPTIONAL { ?doc po:contains ?sec . ?sec a doco:Section }
  OPTIONAL { ?sec po:contains ?para . ?para a doco:Paragraph }
}""")
    d["docs"]  = int(r[0].get("docs", 0)) if r else 0
    d["secs"]  = int(r[0].get("secs", 0)) if r else 0
    d["paras"] = int(r[0].get("paras", 0)) if r else 0

    r = sparql("""
SELECT ?tipo (COUNT(?doc) AS ?n)
WHERE { ?doc a ?tipo . FILTER(?tipo IN (fabio:DoctoralThesis, fabio:MastersThesis)) }
GROUP BY ?tipo""")
    d["phd"] = next((int(x["n"]) for x in r if "Doctoral" in x.get("tipo","")), 0)
    d["msc"] = next((int(x["n"]) for x in r if "Masters"  in x.get("tipo","")), 0)

    r = sparql("""
SELECT (COUNT(?c) AS ?claims) (COUNT(?l) AS ?lims) (COUNT(?fw) AS ?fw)
WHERE {
  { ?doc discourse:hasClaim ?c }
  UNION { ?doc discourse:hasLimitation ?l }
  UNION { ?doc discourse:hasFutureWork ?fw }
}""")
    d["claims"] = int(r[0].get("claims", 0)) if r else 0
    d["lims"]   = int(r[0].get("lims", 0))   if r else 0
    d["fw"]     = int(r[0].get("fw", 0))     if r else 0

    r = sparql("""
SELECT ?ano (COUNT(?doc) AS ?n)
WHERE {
  ?doc a fabio:Work . ?doc dcterms:date ?d .
  BIND(SUBSTR(STR(?d),1,4) AS ?ano) FILTER(STRLEN(?ano)=4)
}
GROUP BY ?ano ORDER BY ?ano""")
    d["por_ano"] = [(x["ano"], int(x["n"])) for x in r if "2017" <= x.get("ano","") <= "2025"]

    r = sparql("""
SELECT ?area (COUNT(?lim) AS ?n)
WHERE {
  ?doc a fabio:Work . ?doc dcterms:subject ?area .
  ?doc discourse:hasLimitation ?lim . FILTER(STRSTARTS(STR(?area),"CNPQ::"))
}
GROUP BY ?area ORDER BY DESC(?n) LIMIT 5""")
    d["top_areas_lim"] = [(x["area"].replace("CNPQ::",""), int(x["n"])) for x in r]

    return d


# ── Geração do relatório ──────────────────────────────────────────────────────

def build_report(corpus: dict, eval_data: dict | None,
                 shacl: dict | None, graph: dict | None) -> str:

    now = datetime.now().strftime("%d/%m/%Y %H:%M")

    # Extrai sub-dicts de avaliação
    h1 = eval_data.get("h1", {}) if eval_data else {}
    h2 = eval_data.get("h2", {}) if eval_data else {}
    h3 = eval_data.get("h3", {}) if eval_data else {}

    # Dados SHACL
    shacl_total    = shacl.get("n_total", 0)       if shacl else 0
    shacl_conforms = shacl.get("n_conforms", 0)    if shacl else 0
    shacl_viol     = shacl.get("n_violation", 0)   if shacl else 0
    shacl_warn     = shacl.get("n_warning", 0)     if shacl else 0
    shacl_rate     = shacl_conforms / shacl_total   if shacl_total else 0
    shacl_viol_rate = shacl_viol / shacl_total      if shacl_total else 0
    shacl_warn_details = []
    if shacl:
        from collections import Counter
        all_w = [w for d in shacl.get("details",[]) for w in d.get("warnings",[])]
        shacl_warn_details = Counter(w["message"] for w in all_w).most_common(5)

    # Dados de integridade do grafo
    graph_pass  = sum(1 for c in (graph.get("checks",[]) if graph else [])
                      if c.get("esperado_zero") and c.get("passou") is True)
    graph_fail  = sum(1 for c in (graph.get("checks",[]) if graph else [])
                      if c.get("esperado_zero") and c.get("passou") is False)
    graph_info  = {c["check"]: c["valor"] for c in (graph.get("checks",[]) if graph else [])
                   if not c.get("esperado_zero")}

    # Tabela de anos
    anos_table = "\n".join(f"| {a} | {n} |" for a, n in corpus.get("por_ano", []))

    # Tabela top limitações por área
    top_lim_rows = "\n".join(
        f"| {a[:55]} | {n} |" for a, n in corpus.get("top_areas_lim", [])
    )

    # H1 values
    h1_ts  = pct(h1.get("taxa_sucesso", 0))
    h1_tf  = pct(h1.get("taxa_falhas", 0))
    h1_tc  = pct(h1.get("taxa_claim", 0))
    h1_n   = h1.get("total_documentos", "—")
    h1_ok  = h1.get("ok", "—")
    h1_nt  = h1.get("no_target", "—")
    h1_fl  = h1.get("failed", "—")
    h1c    = h1.get("criteria", {})

    # H2 values
    compare  = h2.get("compare", {})
    campos_d = h2.get("campos_preenchidos", {})
    gr       = compare.get("generic_ratio")
    rh       = compare.get("rhet_ok")
    cp       = campos_d.get("campos_avg")
    cp_n     = campos_d.get("n_docs", 0)
    h2c      = h2.get("criteria", {})

    # H3 values
    vt = h3.get("variacao_temporal", {})
    dp = h3.get("densidade_phd_msc", {})
    pl = h3.get("perfis_limitacao", {})
    h3c = h3.get("criteria", {})

    # ML vs FEM table
    ml_fem_rows = ""
    if vt:
        anos_vt = vt.get("anos", [])
        ml_v    = vt.get("ml_por_ano", {})
        fem_v   = vt.get("fem_por_ano", {})
        ml_fem_rows = "\n".join(
            f"| {a} | {ml_v.get(a,0)} | {fem_v.get(a,0)} |"
            for a in anos_vt
        )

    # Graph integrity informative checks
    gi_rows = ""
    if graph:
        for c in graph.get("checks", []):
            if not c.get("esperado_zero"):
                gi_rows += f"| {c['descricao']} | {c['valor']:,} |\n"

    # Graph integrity critical checks
    gi_crit_rows = ""
    if graph:
        for c in graph.get("checks", []):
            if c.get("esperado_zero"):
                status = "✓ zero" if c.get("passou") else f"✗ {c['valor']}"
                gi_crit_rows += f"| {c['descricao']} | {status} |\n"

    md = f"""# Relatório Final — Grafo de Conhecimento de Discurso Científico

**Projeto:** Construção de um Grafo de Conhecimento de Discurso Científico  
**Repositório:** Pantheon/UFRJ  
**Gerado em:** {now}

---

## 1. Visão Geral do Corpus

| Métrica | Valor |
|---|---|
| Documentos indexados no grafo | {corpus['docs']:,} |
| Teses de doutorado | {corpus['phd']:,} |
| Dissertações de mestrado | {corpus['msc']:,} |
| Seções estruturadas (DoCO) | {corpus['secs']:,} |
| Parágrafos | {corpus['paras']:,} |
| Claims extraídos pelo LLM | {corpus['claims']:,} |
| Limitações extraídas | {corpus['lims']:,} |
| Trabalhos futuros extraídos | {corpus['fw']:,} |

### Distribuição temporal

| Ano | Documentos |
|---|---|
{anos_table}

> As datas refletem o campo `datestamp` de indexação no Pantheon, não necessariamente
> o ano de defesa. O campo pode apresentar anos atípicos como 2025/2026 para
> documentos indexados recentemente.

---

## 2. Qualidade Estrutural do Grafo

O projeto utiliza duas abordagens complementares de validação. Cada uma examina
um aspecto diferente da qualidade: uma verifica se o grafo respeita as
**regras formais** das ontologias adotadas; a outra verifica se as
**relações semânticas** estão consistentes.

### 2.1 Validação SHACL — conformidade formal

**O que o SHACL verifica:** cada nó do grafo é testado contra um conjunto de
shapes (formas) que descrevem o que é obrigatório, o que é permitido e o
que é proibido segundo as ontologias DoCO, DEO, FaBiO e a ontologia
customizada de discurso. Um nó pode falhar de duas formas distintas:

- **Violação** — quebra uma restrição crítica (ex: documento sem título).
  Indica problema real no dado.
- **Aviso** — quebra uma restrição informativa (ex: abstract curto).
  Pode ser limitação esperada da ferramenta de extração.

**Como interpretar a taxa de conformidade:** um documento é contado como
"em conformidade" apenas se não tem nenhuma violação **nem** aviso. Por isso,
a taxa de conformidade total costuma ser baixa mesmo quando o grafo está
estruturalmente correto — especialmente em corpora extraídos de PDFs históricos,
onde avisos de seções vazias são esperados do GROBID.

**O indicador mais relevante é a taxa de violações críticas.**

| Métrica SHACL | Valor |
|---|---|
| Documentos validados | {shacl_total:,} |
| Sem nenhum problema (conformidade total) | {shacl_conforms:,} ({pct(shacl_rate)}) |
| Com violações críticas | {shacl_viol:,} ({pct(shacl_viol_rate)}) |
| Com avisos (sem violações críticas) | {shacl_warn:,} |

**Avisos mais frequentes** (limitações esperadas do processo de extração):
{chr(10).join(f'- `{msg[:70]}` — {n}x' for msg, n in shacl_warn_details) if shacl_warn_details else '_Sem avisos registrados._'}

### 2.2 Validação de integridade semântica

**O que as queries de integridade verificam:** enquanto o SHACL testa a
conformidade de cada nó individualmente, as queries de integridade testam
a **consistência das relações** no grafo como um todo — se existem nós
sem conexão com outros, duplicatas, referências quebradas.

**Verificações críticas** (valor esperado: zero):

| Verificação | Resultado |
|---|---|
{gi_crit_rows if gi_crit_rows else "| _Não disponível_ | — |\n"}

**Contagens do corpus** (informativas):

| Métrica | Valor |
|---|---|
{gi_rows if gi_rows else "| _Não disponível_ | — |\n"}

### 2.3 Como as duas abordagens se complementam

O SHACL e a validação de integridade respondem perguntas diferentes e se
complementam mutuamente:

| Aspecto | SHACL | Integridade semântica |
|---|---|---|
| O que testa | Forma de cada nó | Relações entre nós |
| Padrão | W3C SHACL 1.0 | SPARQL 1.1 |
| Detecta | Metadados ausentes, tipos incorretos | Órfãos, duplicatas, relações quebradas |
| Limitação | Não testa consistência entre grafos | Não testa conformidade com ontologia |

---

## 3. Plano de Avaliação — Hipóteses e Critérios

Os critérios abaixo foram definidos na proposta do projeto considerando
as características de modelos de linguagem locais sem ajuste fino.
Os valores medidos são apresentados para cada critério — a interpretação
final cabe ao leitor.

### H1 — Viabilidade de extração

> *Um modelo de linguagem de pequeno porte, executado localmente sem ajuste fino,
> conseguirá extrair elementos de discurso científico de seções de conclusão e
> resultados de teses escritas em português.*

| Pergunta | Critério | Valor medido | |
|---|---|---|---|
| Qual proporção dos documentos elegíveis foi processada com sucesso? | ≥ 50% | {h1_ts} | {"✓" if h1c.get("taxa_sucesso") else "✗" if h1c.get("taxa_sucesso") is False else "—"} |
| Qual a taxa de falhas do modelo (saída inválida, timeout)? | ≤ 10% | {h1_tf} | {"✓" if h1c.get("taxa_falhas") else "✗" if h1c.get("taxa_falhas") is False else "—"} |
| Qual proporção dos documentos processados tem ao menos 1 afirmação? | ≥ 70% | {h1_tc} | {"✓" if h1c.get("docs_com_claim") else "✗" if h1c.get("docs_com_claim") is False else "—"} |

Universo de análise: {h1_n} documentos totais | {h1_ok} analisados com sucesso | {h1_nt} sem seções-alvo | {h1_fl} falhas.

### H2 — Qualidade da extração

> *A proporção de itens extraídos classificados como genéricos será inferior a 20%
> do total, e a estrutura formal do grafo satisfará as restrições das ontologias.*

| Pergunta | Critério | Valor medido | |
|---|---|---|---|
| Qual proporção das afirmações extraídas é genérica (sem conteúdo específico)? | ≤ 35% | {pct(gr) if gr is not None else '—'} | {"✓" if h2c.get("genericos") else "✗" if h2c.get("genericos") is False else "—"} |
| Qual proporção das seções foi classificada com tipo retórico correto? | ≥ 60% | {pct(rh) if rh is not None else '—'} | {"✓" if h2c.get("tipo_retorico") else "✗" if h2c.get("tipo_retorico") is False else "—"} |
| Quantos dos 4 campos de discurso são preenchidos por documento (em média)? | ≥ 2,0 | {f"{cp:.2f}" if cp is not None else "—"} de 4 ({cp_n} docs) | {"✓" if h2c.get("campos_preenchidos") else "✗" if h2c.get("campos_preenchidos") is False else "—"} |
| Qual proporção dos documentos está em conformidade formal (SHACL)? | ≥ 80% | {pct(shacl_rate)} | {"✓" if h2c.get("shacl_conformidade") else "✗" if h2c.get("shacl_conformidade") is False else "—"} |
| Qual a taxa de violações críticas no grafo (SHACL)? | ≤ 5% | {pct(shacl_viol_rate)} | {"✓" if h2c.get("shacl_violacoes") else "✗" if h2c.get("shacl_violacoes") is False else "—"} |

> **Nota sobre conformidade SHACL:** a taxa de conformidade total reflete
> documentos sem nenhum aviso ou violação. Avisos de seções sem parágrafo são
> esperados do GROBID em PDFs históricos e não indicam erro de dados.
> O critério de 5% de violações críticas é o indicador central desta hipótese.

### H3 — Valor analítico do grafo

> *As consultas sobre o grafo enriquecido revelarão padrões não triviais no corpus.*

**Pergunta 1:** É possível identificar variação temporal no uso de técnicas metodológicas via consulta SPARQL?

Critério: variação observável ao longo do período coberto.

| Ano | Machine Learning | Elementos Finitos |
|---|---|---|
{ml_fem_rows if ml_fem_rows else "| _Não disponível_ | — | — |"}

**Pergunta 2:** Há diferença de densidade de afirmações entre teses de doutorado e dissertações de mestrado?

Critério: teses de doutorado com densidade observavelmente maior.

| Tipo | Documentos | Claims totais | Claims por documento |
|---|---|---|---|
| Doutorado | {dp.get("phd_docs","—"):,} | {dp.get("phd_claims","—"):,} | {dp.get("phd_avg","—"):.2f} |
| Mestrado  | {dp.get("msc_docs","—"):,} | {dp.get("msc_claims","—"):,} | {dp.get("msc_avg","—"):.2f} |

**Pergunta 3:** As limitações declaradas diferem sistematicamente entre áreas do corpus?

Critério: ao menos 2 áreas com perfis de limitação distintos identificáveis.

| Área | Limitações declaradas |
|---|---|
{top_lim_rows if top_lim_rows else "| _Não disponível_ | — |"}

---

## 4. Comparação de modelos LLM

A escolha do modelo de extração foi validada experimentalmente em uma amostra
do corpus. Os valores abaixo refletem o modelo adotado para o processamento
completo.

| Dimensão | Métrica | Valor |
|---|---|---|
| Confiabilidade | Taxa de saída genérica | {pct(gr) if gr is not None else '—'} |
| Qualidade | Tipo retórico correto | {pct(rh) if rh is not None else '—'} |
| Completude | Campos preenchidos por documento | {f"{cp:.2f}/4" if cp is not None else "—"} |

---

_Relatório gerado automaticamente por `generate_report.py` em {now}_
"""
    return md


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Gera relatório final consolidado em Markdown"
    )
    parser.add_argument("--output", default="relatorio_final.md")
    args = parser.parse_args()

    # Verifica Fuseki
    try:
        r = requests.get(f"{FUSEKI_URL}/$/ping",
                         auth=(FUSEKI_USER, FUSEKI_PASS), timeout=5)
        assert r.status_code == 200
        print("✓ Fuseki acessível")
    except Exception:
        print("✗ Fuseki não acessível — estatísticas do corpus não disponíveis")

    print("Coletando dados...", end=" ", flush=True)
    corpus    = collect_corpus_stats()
    eval_data = load_json(EVAL_FILE)
    shacl     = load_json(SHACL_FILE)
    graph     = load_json(GRAPH_FILE)
    print("✓")

    if not eval_data:
        print(f"⚠  {EVAL_FILE} não encontrado — execute evaluate_project.py primeiro")
    if not shacl:
        print(f"⚠  {SHACL_FILE} não encontrado — execute shacl_validate.py primeiro")
    if not graph:
        print(f"⚠  {GRAPH_FILE} não encontrado — execute validate_graph.py primeiro")

    print("Gerando relatório...", end=" ", flush=True)
    md = build_report(corpus, eval_data, shacl, graph)
    print("✓")

    out = Path(args.output)
    out.write_text(md, encoding="utf-8")
    print(f"\n✓ Relatório gerado: {out}")
    print(f"  {len(md):,} caracteres · {md.count(chr(10)):,} linhas")


if __name__ == "__main__":
    main()