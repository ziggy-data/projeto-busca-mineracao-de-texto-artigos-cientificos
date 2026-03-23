#!/usr/bin/env python3
# check_discourse.py — verifica a qualidade dos dados de análise de discurso
#
# Uso: python check_discourse.py

import json
import os
from collections import Counter
from pathlib import Path

DISCOURSE_DIR = "data/discourse"
REPORT_FILE   = "data/discourse_report.jsonl"


def load_all() -> list[dict]:
    docs = []
    for f in Path(DISCOURSE_DIR).glob("*.json"):
        try:
            docs.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    return docs


def main():
    docs = load_all()
    if not docs:
        print(f"Nenhum arquivo encontrado em {DISCOURSE_DIR}")
        return

    ok_docs       = [d for d in docs if d.get("status") == "ok"]
    no_sec_docs   = [d for d in docs if d.get("status") == "no_target_sections"]
    failed_docs   = [d for d in docs if d.get("status") == "llm_failed"]

    print("=" * 60)
    print("RELATÓRIO DE QUALIDADE — ANÁLISE DE DISCURSO")
    print("=" * 60)

    print(f"\n── Cobertura ──────────────────────────────────────────")
    print(f"  Total de documentos     : {len(docs)}")
    print(f"  ✓ Analisados com sucesso: {len(ok_docs)} ({100*len(ok_docs)/len(docs):.1f}%)")
    print(f"  ⚠ Sem seções-alvo       : {len(no_sec_docs)} ({100*len(no_sec_docs)/len(docs):.1f}%)")
    print(f"  ✗ Falhas LLM            : {len(failed_docs)} ({100*len(failed_docs)/len(docs):.1f}%)")

    if not ok_docs:
        print("\nNenhum documento OK encontrado.")
        return

    # Coleta todas as seções
    all_sections = [sec for d in ok_docs for sec in d.get("sections", [])]

    print(f"\n── Seções analisadas ──────────────────────────────────")
    print(f"  Total de seções         : {len(all_sections)}")
    print(f"  Média por documento     : {len(all_sections)/len(ok_docs):.1f}")

    # Distribuição de tipos retóricos
    rhet_counter = Counter(s.get("rhetorical_type", "?") for s in all_sections)
    print(f"\n── Tipos retóricos (DEO) ──────────────────────────────")
    for rtype, count in rhet_counter.most_common():
        bar = "█" * min(count // 10, 40)
        print(f"  {rtype:<15} {count:4d}  {bar}")

    # Contagem de claims, limitações, etc.
    total_claims   = sum(len(s.get("claims", []))        for s in all_sections)
    total_contribs = sum(len(s.get("contributions", [])) for s in all_sections)
    total_limits   = sum(len(s.get("limitations", []))   for s in all_sections)
    total_fw       = sum(len(s.get("future_work", []))   for s in all_sections)
    total_kw       = sum(len(s.get("keywords_inferred",[])) for s in all_sections)

    print(f"\n── Extração de conteúdo ───────────────────────────────")
    print(f"  Claims extraídos        : {total_claims:,}  (média {total_claims/len(all_sections):.1f}/seção)")
    print(f"  Contribuições           : {total_contribs:,}  (média {total_contribs/len(all_sections):.1f}/seção)")
    print(f"  Limitações              : {total_limits:,}  (média {total_limits/len(all_sections):.1f}/seção)")
    print(f"  Trabalhos futuros       : {total_fw:,}  (média {total_fw/len(all_sections):.1f}/seção)")
    print(f"  Keywords inferidas      : {total_kw:,}  (média {total_kw/len(all_sections):.1f}/seção)")

    # Documentos com dados ricos vs pobres
    rich  = [d for d in ok_docs if sum(len(s.get("claims",[])) for s in d["sections"]) >= 3]
    empty = [d for d in ok_docs if sum(len(s.get("claims",[])) for s in d["sections"]) == 0]
    print(f"\n── Qualidade dos dados ────────────────────────────────")
    print(f"  Docs com 3+ claims      : {len(rich)} ({100*len(rich)/len(ok_docs):.1f}%)")
    print(f"  Docs sem claims         : {len(empty)} ({100*len(empty)/len(ok_docs):.1f}%)")

    # Top 20 keywords mais frequentes
    kw_counter = Counter()
    for s in all_sections:
        for kw in s.get("keywords_inferred", []):
            if kw and len(kw) > 3:
                kw_counter[kw.lower().strip()] += 1

    print(f"\n── Top 20 keywords inferidas pelo LLM ─────────────────")
    for kw, count in kw_counter.most_common(20):
        print(f"  {count:4d}x  {kw}")

    # Exemplos de claims reais
    print(f"\n── 5 exemplos de claims extraídos ─────────────────────")
    shown = 0
    for d in ok_docs:
        for sec in d.get("sections", []):
            for claim in sec.get("claims", [])[:1]:
                if claim and len(claim) > 30:
                    title = d.get("doc_title", "")[:60]
                    print(f"\n  [{title}]")
                    print(f"  Seção: {sec.get('section_head','')}")
                    print(f"  Claim: {claim[:200]}")
                    shown += 1
                    if shown >= 5:
                        break
            if shown >= 5:
                break
        if shown >= 5:
            break

    # Exemplos de limitações
    print(f"\n── 3 exemplos de limitações extraídas ─────────────────")
    shown = 0
    for d in ok_docs:
        for sec in d.get("sections", []):
            for lim in sec.get("limitations", [])[:1]:
                if lim and len(lim) > 20:
                    print(f"  → {lim[:200]}")
                    shown += 1
                    if shown >= 3:
                        break
            if shown >= 3:
                break
        if shown >= 3:
            break

    # Exemplos de trabalhos futuros
    print(f"\n── 3 exemplos de trabalhos futuros ────────────────────")
    shown = 0
    for d in ok_docs:
        for sec in d.get("sections", []):
            for fw in sec.get("future_work", [])[:1]:
                if fw and len(fw) > 20:
                    print(f"  → {fw[:200]}")
                    shown += 1
                    if shown >= 3:
                        break
            if shown >= 3:
                break
        if shown >= 3:
            break

    print(f"\n{'='*60}")
    print(f"Dados prontos para enriquecimento do grafo.")
    print(f"  Próximo: python enrich_graph.py --dry-run")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
