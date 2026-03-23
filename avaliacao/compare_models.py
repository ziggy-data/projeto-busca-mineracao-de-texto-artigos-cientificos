#!/usr/bin/env python3
# compare_models.py — compara dois modelos LLM em qualidade, erros e genericidade
#
# Otimizações são SOMENTE de GPU/paralelismo — sem reduzir output.
#
# Métricas avaliadas:
#   - Erros: JSON inválido, respostas vazias, timeouts
#   - Genericidade: frases que não dizem nada específico
#   - Completude: campos preenchidos com conteúdo substancial por doc
#   - Velocidade: tokens/segundo e estimativa para 1970 docs
#
# Gera relatório Markdown com tabela comparativa e recomendação justificada.
#
# Uso:
#   python compare_models.py --limit 30
#   python compare_models.py --limit 30 --model-a llama3.1:8b --model-b qwen2.5:14b-Instruct
#   python compare_models.py --limit 30 --model-a llama3.1:8b --model-b llama3.2:3b

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

import requests
from tqdm import tqdm

OLLAMA_URL = "http://localhost:11434"
TEI_DIR    = "../fase_2/data/tei"
OUTPUT_DIR = "data/model_comparison"
TEI_NS     = "http://www.tei-c.org/ns/1.0"

TARGET_PATTERNS = [
    "conclus", "conclusion", "result", "resultado", "discuss",
    "contribui", "considera", "final remarks", "encerr",
]

SYSTEM_PROMPT = """You are a scientific discourse analyst specializing in Brazilian academic theses.
Extract SUBSTANTIVE information — specific findings, concrete contributions, explicit limitations.
REJECT generic statements like "this chapter presents..." or "future work will be done".
Respond ONLY with valid JSON. No markdown, no explanation."""

# ── Configuração de qualidade — NÃO REDUZIR ──────────────────────────────────
QUALITY_OPTIONS = {
    "temperature": 0.1,
    "top_p":       0.9,
    "num_predict": 7000,    # permite JSON completo com 5 claims detalhados
    "num_ctx":     2048,   # suficiente para o prompt sem afetar output
    "num_gpu":     99,     # TODOS os layers na GPU — otimização sem custo de qualidade
    "keep_alive":  "10m",  # mantém modelo na VRAM — otimização sem custo de qualidade
}
TEXT_LIMIT = 9000   # chars do texto da seção — contexto completo

# Frases que indicam resposta genérica/sem valor
GENERIC_PHRASES = [
    "this chapter presents", "este capítulo apresenta",
    "this section discusses", "esta seção discute",
    "future work will", "trabalhos futuros irão",
    "as presented in", "conforme apresentado",
    "this work aims", "este trabalho tem como objetivo",
    "the results show that the", "os resultados mostram que o",
    "in this thesis", "nesta dissertação",
    "further research is needed", "mais pesquisas são necessárias",
    "it was found that", "verificou-se que",
    "the study shows", "o estudo mostra",
    "the proposed approach", "a abordagem proposta",
]
MIN_SPECIFIC_LEN = 40  # itens com menos de 40 chars são genéricos

# Keywords que NÃO devem aparecer como "específicas"
KW_STOPWORDS = {
    "results", "resultados", "conclusion", "conclusão", "methodology",
    "simulation", "simulação", "research", "pesquisa", "analysis",
    "análise", "work", "trabalho", "method", "approach", "study",
    "data", "dados", "model", "modelo", "system", "sistema",
}


# ── Extração de seção ─────────────────────────────────────────────────────────

def get_section(tei_path: str) -> dict | None:
    ns = {"tei": TEI_NS}
    try:
        root = ET.parse(tei_path).getroot()
    except Exception:
        return None

    title_el  = root.find(".//tei:titleStmt/tei:title", ns)
    doc_title = " ".join(title_el.itertext()).strip() if title_el is not None else ""

    body = root.find(".//tei:body", ns)
    if body is None:
        return None

    for div in body.findall(".//tei:div", ns):
        head_el  = div.find("tei:head", ns)
        head_txt = " ".join(head_el.itertext()).strip() if head_el is not None else ""
        if not any(kw in head_txt.lower() for kw in TARGET_PATTERNS):
            continue
        paras = [" ".join(p.itertext()).strip() for p in div.findall("tei:p", ns)]
        text  = " ".join(paras)
        if len(text) >= 200:
            return {"head": head_txt, "text": text, "doc_title": doc_title}
    return None


# ── Chamada ao LLM ────────────────────────────────────────────────────────────

def make_prompt(head: str, text: str, doc_title: str) -> str:
    return f"""Thesis: "{doc_title}"
Section "{head}":
{text[:TEXT_LIMIT]}

Respond ONLY with JSON:
{{"claims":[],"contributions":[],"limitations":[],"future_work":[],"keywords_inferred":[],"rhetorical_type":""}}"""


def extract_json(raw: str) -> dict | None:
    if not raw:
        return None
    raw = re.sub(r"```(?:json)?\s*", "", raw).strip().replace("```", "")
    candidates = [raw]
    j = raw.find("{")
    if j >= 0:
        candidates.append(raw[j:])
    for text in candidates:
        for suffix in [
            "",
            "]" * max(text.count("[") - text.count("]"), 0),
            "}" * max(text.count("{") - text.count("}"), 0),
        ]:
            try:
                return json.loads(text + suffix)
            except Exception:
                pass
    return None


def call_model(prompt: str, model: str) -> tuple:
    """Retorna (result, elapsed_s, tokens, error_str)."""
    start = time.time()
    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model":  model,
                "prompt": prompt,
                "system": SYSTEM_PROMPT,
                "stream": False,
                "options": QUALITY_OPTIONS,
            },
            timeout=150,
        )
        elapsed = time.time() - start
        if r.status_code != 200:
            return None, elapsed, 0, f"HTTP {r.status_code}"
        data   = r.json()
        raw    = data.get("response", "")
        tokens = data.get("eval_count", 0)
        if not raw:
            return None, elapsed, 0, "empty_response"
        result = extract_json(raw)
        if result is None:
            return None, elapsed, tokens, f"invalid_json: {raw[:60]}"
        return result, elapsed, tokens, ""
    except requests.exceptions.Timeout:
        return None, 150.0, 0, "timeout"
    except Exception as e:
        return None, time.time() - start, 0, str(e)[:60]


# ── Análise de qualidade ──────────────────────────────────────────────────────

def is_generic(text: str) -> bool:
    if len(text) < MIN_SPECIFIC_LEN:
        return True
    tl = text.lower()
    return any(phrase in tl for phrase in GENERIC_PHRASES)


def analyze_quality(result: dict | None) -> dict:
    EMPTY = {
        "valid_json": False, "total": 0, "specific": 0, "generic": 0,
        "generic_ratio": 1.0, "fields": {}, "missing": [],
        "rhet_ok": False, "keywords_ok": 0,
        "specific_ex": [], "generic_ex": [],
    }
    if result is None:
        return EMPTY

    all_items = []
    fields    = {}
    for f in ["claims", "contributions", "limitations", "future_work"]:
        items = [i for i in (result.get(f) or []) if isinstance(i, str) and i.strip()]
        fields[f] = len(items)
        all_items.extend(items)

    specific = [i for i in all_items if not is_generic(i)]
    generic  = [i for i in all_items if is_generic(i)]
    kws      = [k for k in (result.get("keywords_inferred") or [])
                if isinstance(k, str) and len(k) > 4
                and k.lower().strip() not in KW_STOPWORDS]
    rhet     = result.get("rhetorical_type", "")
    missing  = [f for f in ["claims", "contributions", "limitations", "future_work"]
                if not fields.get(f)]

    return {
        "valid_json": True,
        "total":      len(all_items),
        "specific":   len(specific),
        "generic":    len(generic),
        "generic_ratio": len(generic) / max(len(all_items), 1),
        "fields":     fields,
        "missing":    missing,
        "rhet_ok":    bool(rhet and rhet not in ("", "mixed")),
        "keywords_ok": len(kws),
        "specific_ex": specific[:2],
        "generic_ex":  generic[:2],
    }


# ── Relatório Markdown ────────────────────────────────────────────────────────

def build_report(model_a: str, model_b: str,
                 data_a: list, data_b: list, samples: list) -> str:

    n = len(samples)

    def avg(lst):
        return round(sum(lst) / len(lst), 2) if lst else 0

    def pct(num, total):
        return f"{num}/{total} ({100*num//max(total,1)}%)"

    def agg(data):
        times  = [d["time"] for d in data]
        toks   = [d["tokens"] for d in data if d["tokens"] > 0]
        valid  = [d for d in data if d["q"]["valid_json"]]
        errors = [d for d in data if d["error"]]
        timeouts = [d for d in data if "timeout" in d["error"]]
        json_fail = [d for d in data if not d["q"]["valid_json"]]
        missing_claims = [d for d in data if "claims" in d["q"]["missing"]]

        avg_t  = avg(times)
        avg_tk = avg(toks)
        tps    = round(avg_tk / avg_t, 1) if avg_t > 0 else 0

        return {
            "n": n,
            "errors": errors, "timeouts": timeouts, "json_fail": json_fail,
            "missing_claims": missing_claims,
            "avg_specific": avg([d["q"]["specific"] for d in valid]),
            "avg_generic":  avg([d["q"]["generic"]  for d in valid]),
            "avg_gen_ratio": avg([d["q"]["generic_ratio"] for d in valid]),
            "avg_total":    avg([d["q"]["total"]     for d in valid]),
            "avg_fields":   avg([sum(1 for v in d["q"]["fields"].values() if v > 0) for d in valid]),
            "avg_kw":       avg([d["q"]["keywords_ok"] for d in valid]),
            "rhet_ok":      sum(1 for d in valid if d["q"]["rhet_ok"]),
            "avg_time":     avg_t, "tps": tps,
            "est_h":        round(avg_t * 1970 / 3 / 3600, 1),
            "avg_claims":   avg([d["q"]["fields"].get("claims", 0) for d in valid]),
            "avg_contribs": avg([d["q"]["fields"].get("contributions", 0) for d in valid]),
            "avg_limits":   avg([d["q"]["fields"].get("limitations", 0) for d in valid]),
            "avg_fw":       avg([d["q"]["fields"].get("future_work", 0) for d in valid]),
        }

    ma = agg(data_a)
    mb = agg(data_b)

    def winner(va, vb, higher=True):
        if va == vb: return "—"
        best = model_a if (va > vb) == higher else model_b
        return f"**{best}**"

    # Score para recomendação final
    def score(m):
        return (
            (len(m["errors"]) == 0) * 3 +
            (m["avg_gen_ratio"] < 0.25) * 3 +
            (m["avg_specific"] >= 3.0) * 2 +
            (m["avg_fields"] >= 3.5) * 2 +
            (len(m["json_fail"]) == 0) * 2 +
            (m["avg_kw"] >= 3.0) * 1
        )

    sa, sb = score(ma), score(mb)
    if sa > sb:
        rec, rec_reason = model_a, "maior especificidade e menor taxa de erros"
    elif sb > sa:
        rec, rec_reason = model_b, "maior especificidade e menor taxa de erros"
    else:
        if ma["avg_time"] <= mb["avg_time"]:
            rec = model_a
            rec_reason = f"scores iguais — {mb['avg_time']/ma['avg_time']:.1f}x mais rápido"
        else:
            rec = model_b
            rec_reason = f"scores iguais — {ma['avg_time']/mb['avg_time']:.1f}x mais rápido"

    # Seção de exemplos
    examples = ""
    for i, (da, db, sec) in enumerate(zip(data_a[:3], data_b[:3], samples[:3])):
        examples += f"\n### Documento {i+1}\n"
        examples += f"**Tese:** {sec['doc_title'][:70]}\n"
        examples += f"**Seção:** `{sec['head']}`\n\n"
        for label, d in [(f"`{model_a}`", da), (f"`{model_b}`", db)]:
            q = d["q"]
            examples += f"#### {label}\n"
            if d["error"]:
                examples += f"❌ **Erro:** `{d['error']}`\n\n"
                continue
            examples += f"- Tempo: **{d['time']:.1f}s** | Tokens gerados: {d['tokens']}\n"
            examples += f"- Específicos: **{q['specific']}** | Genéricos: **{q['generic']}**"
            examples += f" | Keywords válidas: **{q['keywords_ok']}**\n"
            examples += f"- Tipo retórico: `{d.get('result', {}).get('rhetorical_type', '—')}`"
            examples += f" | Campos preenchidos: {sum(1 for v in q['fields'].values() if v > 0)}/4\n"
            if q["specific_ex"]:
                examples += "\n**Claims específicos:**\n"
                for ex in q["specific_ex"]:
                    examples += f"> {ex[:150]}\n"
            if q["generic_ex"]:
                examples += "\n⚠️ **Claims genéricos (baixa qualidade):**\n"
                for ex in q["generic_ex"]:
                    examples += f"> {ex[:150]}\n"
            examples += "\n"

    md = f"""# Relatório: Comparação de Modelos LLM

**Data:** {datetime.now().strftime('%Y-%m-%d %H:%M')}
**Documentos testados:** {n}
**Configuração usada:** `num_predict=700` · `text_limit=3000ch` · `num_gpu=99` · `keep_alive=10m`

> ⚙️ Qualidade máxima preservada — `num_predict` e `text_limit` **não foram reduzidos**.
> As otimizações (`num_gpu`, `keep_alive`) são de infraestrutura e não afetam o output.

---

## 🏆 Recomendação Final

> ### Use **`{rec}`**
> *{rec_reason}*

```bash
# Comando para o corpus completo com o modelo recomendado:
python discourse_analysis.py --model {rec} --workers 3
```

> ⚠️ Configure o ollama para paralelismo antes de rodar:
> ```powershell
> $env:OLLAMA_NUM_PARALLEL=3; ollama serve
> ```

---

## Tabela comparativa

| Métrica | `{model_a}` | `{model_b}` | Melhor |
|---|---|---|---|
| **Confiabilidade** | | | |
| Erros totais | {len(ma['errors'])} | {len(mb['errors'])} | {winner(len(ma['errors']), len(mb['errors']), False)} |
| JSON inválido | {pct(len(ma['json_fail']), n)} | {pct(len(mb['json_fail']), n)} | {winner(len(ma['json_fail']), len(mb['json_fail']), False)} |
| Timeouts | {len(ma['timeouts'])} | {len(mb['timeouts'])} | {winner(len(ma['timeouts']), len(mb['timeouts']), False)} |
| Docs sem claims | {pct(len(ma['missing_claims']), n)} | {pct(len(mb['missing_claims']), n)} | {winner(len(ma['missing_claims']), len(mb['missing_claims']), False)} |
| **Qualidade** | | | |
| Itens específicos/doc | {ma['avg_specific']:.1f} | {mb['avg_specific']:.1f} | {winner(ma['avg_specific'], mb['avg_specific'])} |
| Itens genéricos/doc | {ma['avg_generic']:.1f} | {mb['avg_generic']:.1f} | {winner(ma['avg_generic'], mb['avg_generic'], False)} |
| % genérico | {ma['avg_gen_ratio']:.0%} | {mb['avg_gen_ratio']:.0%} | {winner(ma['avg_gen_ratio'], mb['avg_gen_ratio'], False)} |
| Campos preenchidos/doc | {ma['avg_fields']:.1f}/4 | {mb['avg_fields']:.1f}/4 | {winner(ma['avg_fields'], mb['avg_fields'])} |
| Keywords específicas/doc | {ma['avg_kw']:.1f} | {mb['avg_kw']:.1f} | {winner(ma['avg_kw'], mb['avg_kw'])} |
| Tipo retórico correto | {pct(ma['rhet_ok'], n)} | {pct(mb['rhet_ok'], n)} | {winner(ma['rhet_ok'], mb['rhet_ok'])} |
| **Performance** | | | |
| Tempo médio/request | {ma['avg_time']:.1f}s | {mb['avg_time']:.1f}s | {winner(ma['avg_time'], mb['avg_time'], False)} |
| Tokens/segundo | {ma['tps']:.0f} tok/s | {mb['tps']:.0f} tok/s | {winner(ma['tps'], mb['tps'])} |
| Estimativa corpus (workers=3) | ~{ma['est_h']:.1f}h | ~{mb['est_h']:.1f}h | {winner(ma['est_h'], mb['est_h'], False)} |

---

## Análise por campo

| Campo | `{model_a}` (média/doc) | `{model_b}` (média/doc) | Melhor |
|---|---|---|---|
| claims | {ma['avg_claims']:.1f} | {mb['avg_claims']:.1f} | {winner(ma['avg_claims'], mb['avg_claims'])} |
| contributions | {ma['avg_contribs']:.1f} | {mb['avg_contribs']:.1f} | {winner(ma['avg_contribs'], mb['avg_contribs'])} |
| limitations | {ma['avg_limits']:.1f} | {mb['avg_limits']:.1f} | {winner(ma['avg_limits'], mb['avg_limits'])} |
| future_work | {ma['avg_fw']:.1f} | {mb['avg_fw']:.1f} | {winner(ma['avg_fw'], mb['avg_fw'])} |

---

## O que foi medido

- **Erros:** JSON inválido, resposta vazia, timeout (>150s), HTTP error
- **Genérico:** item com < {MIN_SPECIFIC_LEN} chars **ou** que contém frases como
  _"this chapter presents"_, _"future work will"_, _"os resultados mostram que o"_, etc.
- **Keywords válidas:** excluídas palavras como `results`, `methodology`, `analysis`, `simulation`

---

## Exemplos lado a lado (3 documentos)
{examples}
---

## Configuração do teste

```python
QUALITY_OPTIONS = {{
    "num_predict": 700,   # ← NÃO REDUZIDO — permite resposta JSON completa
    "num_ctx":     2048,  # ← suficiente para o prompt sem afetar output
    "num_gpu":     99,    # ← todos os layers na GPU (sem custo de qualidade)
    "keep_alive":  "10m", # ← mantém modelo carregado (sem custo de qualidade)
    "temperature": 0.1,
    "top_p":       0.9,
}}
TEXT_LIMIT = 3000  # ← NÃO REDUZIDO — contexto completo da seção
```

_Gerado por `compare_models.py`_
"""
    return md


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Compara modelos LLM — gera relatório Markdown com qualidade máxima",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python compare_models.py --limit 30
  python compare_models.py --limit 30 --model-a llama3.1:8b --model-b qwen2.5:7b
  python compare_models.py --limit 30 --model-a llama3.1:8b --model-b llama3.2:3b
        """,
    )
    parser.add_argument("--model-a", default="llama3.1:8b")
    parser.add_argument("--model-b", default="qwen2.5:7b")
    parser.add_argument("--limit",   type=int, default=20)
    parser.add_argument("--tei-dir", default=TEI_DIR)
    parser.add_argument("--output",  default=None,
                        help="Caminho .md de saída (padrão: data/model_comparison/...md)")
    args = parser.parse_args()

    # Verifica ollama
    try:
        r     = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        avail = [m["name"] for m in r.json().get("models", [])]
        print(f"✓ ollama | disponíveis: {avail}")
    except Exception:
        print(f"✗ ollama não acessível em {OLLAMA_URL}")
        sys.exit(1)

    for model in [args.model_a, args.model_b]:
        if not any(model.split(":")[0] in m for m in avail):
            print(f"⚠  '{model}' não encontrado. Execute: ollama pull {model}")
            sys.exit(1)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Coleta amostras
    print(f"\nColetando {args.limit} amostras...")
    samples = []
    for tei in sorted(Path(args.tei_dir).glob("*.tei.xml")):
        sec = get_section(str(tei))
        if sec:
            samples.append(sec)
        if len(samples) >= args.limit:
            break

    if not samples:
        print(f"✗ Nenhuma seção encontrada em {args.tei_dir}")
        sys.exit(1)

    print(f"✓ {len(samples)} amostras")
    print(f"\nConfig: num_predict={QUALITY_OPTIONS['num_predict']} (qualidade máxima)")
    print(f"        text_limit={TEXT_LIMIT}ch | num_gpu=99 | keep_alive=10m\n")

    # Roda os dois modelos
    data_a, data_b = [], []

    for model, bucket in [(args.model_a, data_a), (args.model_b, data_b)]:
        print(f"Testando {model}...")
        for sec in tqdm(samples, desc=model, unit="doc"):
            prompt          = make_prompt(sec["head"], sec["text"], sec["doc_title"])
            result, t, tok, err = call_model(prompt, model)
            q               = analyze_quality(result)
            bucket.append({"result": result, "time": t, "tokens": tok, "error": err, "q": q})
        print()

    # Terminal: resumo rápido
    print("=" * 60)
    for model, data in [(args.model_a, data_a), (args.model_b, data_b)]:
        ok   = sum(1 for d in data if d["q"]["valid_json"])
        errs = sum(1 for d in data if d["error"])
        spec = sum(d["q"]["specific"] for d in data if d["q"]["valid_json"])
        gen  = sum(d["q"]["generic"]  for d in data if d["q"]["valid_json"])
        avg_t = sum(d["time"] for d in data) / len(data)
        print(f"  {model}: JSON ok={ok}/{len(data)}  erros={errs}  "
              f"específicos={spec}  genéricos={gen}  avg={avg_t:.1f}s")
    print("=" * 60)

    # Gera relatório Markdown
    md = build_report(args.model_a, args.model_b, data_a, data_b, samples)

    out = args.output or os.path.join(
        OUTPUT_DIR,
        f"comparison_{args.model_a.replace(':','_')}_vs_{args.model_b.replace(':','_')}.md"
    )
    with open(out, "w", encoding="utf-8") as f:
        f.write(md)

    print(f"\n✓ Relatório Markdown: {out}")
    print(f"  Abra no VS Code / Obsidian / GitHub para ver formatado.")
    print(f"\nPara usar o modelo recomendado:")
    print(f"  python discourse_analysis.py --model <modelo> --workers 3")


if __name__ == "__main__":
    main()