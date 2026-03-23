#!/usr/bin/env python3
# diagnose_discourse.py — diagnostica por que discourse_analysis retorna no_target_sections
#
# Execute na pasta fase_3/:
#   python diagnose_discourse.py               # testa primeiros 50
#   python diagnose_discourse.py --skip 1397   # testa o lote que discourse processaria
#   python diagnose_discourse.py --skip 1397 --limit 50

import argparse
import json
import os
import re
from pathlib import Path
from xml.etree import ElementTree as ET
from collections import Counter

TEI_DIR      = "../fase_2/data/tei"
TTL_DIR      = "../fase_2/data/rdf"
REPORT_FILE  = "data/discourse_report.jsonl"
TEI_NS       = "http://www.tei-c.org/ns/1.0"

TARGET_PATTERNS = [
    r"\bconclu[sz]",
    r"\bresult[ao]",
    r"\bdiscus[sz]",
    r"\bcontribu",
    r"\bconsider[ao]",
    r"\bfinal\s*(remarks?)?",
    r"\bsummar[yi]",
    r"\brecomend",
    r"\bencerr",
    r"^[IVX\d]+[\.\-\s]+.*\bconclu[sz]",
    r"^[IVX\d]+[\.\-\s]+.*\bresult[ao]",
    r"^[IVX\d]+[\.\-\s]+.*\bdiscus[sz]",
    r"^cap[íi]tulo\s+\d+.*\bconclu[sz]",
    r"^cap[íi]tulo\s+\d+.*\bresult[ao]",
]

def matches_target(text: str) -> bool:
    t = text.lower().strip()
    return any(re.search(p, t, re.IGNORECASE) for p in TARGET_PATTERNS)


def test_tei(tei_path: str) -> dict:
    try:
        root  = ET.parse(tei_path).getroot()
        ns    = {"tei": TEI_NS}
        body  = root.find(".//tei:body", ns)
        heads = []
        if body is not None:
            for div in body.findall(".//tei:div", ns):
                h = div.find("tei:head", ns)
                if h is not None:
                    txt = " ".join(h.itertext()).strip()
                    if txt:
                        heads.append(txt)
        matched = [h for h in heads if matches_target(h)]
        return {
            "ok":      len(matched) > 0,
            "heads":   heads[:8],
            "matched": matched,
            "n_heads": len(heads),
        }
    except Exception as e:
        return {"ok": False, "heads": [], "matched": [], "n_heads": 0, "error": str(e)}


def test_ttl(ttl_path: str) -> dict:
    if not os.path.exists(ttl_path):
        return {"ok": False, "reason": "TTL file not found"}

    with open(ttl_path, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    DISCOURSE_DEO = ["deo:Conclusion", "deo:Results", "deo:Discussion"]

    # Reconstrói índice de blocos por sujeito
    blocks: dict = {}
    current = None
    for line in lines:
        m = re.match(r'^(base:\S+)\s+', line)
        if m:
            current = m.group(1)
            blocks.setdefault(current, [])
        if current:
            blocks[current].append(line)

    block_str = {k: "".join(v) for k, v in blocks.items()}

    # Verifica se existe deo: nos blocos
    deo_in_file = any(
        any(t in blk for t in DISCOURSE_DEO)
        for blk in block_str.values()
    )
    if not deo_in_file:
        return {"ok": False, "reason": "no deo:Conclusion/Results/Discussion in TTL"}

    # Verifica se os parágrafos linkados têm conteúdo
    found_text = False
    found_secs = []
    for uri, blk in block_str.items():
        sec_type = next((t for t in DISCOURSE_DEO if t in blk), None)
        if not sec_type:
            continue
        para_uris = re.findall(r'base:(\S+_para_\d+)', blk)
        sec_texts = []
        for pu in para_uris:
            pb = block_str.get(f"base:{pu}", "")
            cm = re.search(r'c4o:hasContent "([^"]{10,})"', pb)
            if cm:
                sec_texts.append(cm.group(1)[:50])
                found_text = True
        if para_uris:
            found_secs.append({
                "type":    sec_type,
                "n_paras": len(para_uris),
                "n_with_content": len(sec_texts),
                "sample":  sec_texts[:2],
            })

    if not found_text:
        if found_secs:
            return {
                "ok": False,
                "reason": f"DEO seções existem ({len(found_secs)}) mas parágrafos sem c4o:hasContent",
                "secs": found_secs,
            }
        return {"ok": False, "reason": "DEO existe mas sem parágrafos linked"}

    return {"ok": True, "secs": found_secs}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=50,
                        help="Quantos TEIs testar (padrão: 50)")
    parser.add_argument("--skip",  type=int, default=0,
                        help="Pular os N primeiros TEIs (use --skip 1397 para testar o lote do discourse)")
    parser.add_argument("--same-as-discourse", action="store_true",
                        help="Testa exatamente os docs que discourse_analysis processaria agora")
    args = parser.parse_args()

    tei_files_all = sorted(Path(TEI_DIR).glob("*.tei.xml"))
    if not tei_files_all:
        print(f"✗ Nenhum TEI em {TEI_DIR} — rode na pasta fase_3/")
        return

    # Carrega handles já processados (igual ao discourse_analysis.py)
    done = set()
    if os.path.exists(REPORT_FILE):
        with open(REPORT_FILE, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                    if r.get("status") == "ok":
                        done.add(r["handle"])
                except Exception:
                    pass
        print(f"Já processados (status=ok): {len(done)}")

    if args.same_as_discourse:
        # Replica exatamente a lógica do discourse_analysis.py
        pending = [
            t for t in tei_files_all
            if t.name.replace(".tei.xml","").replace("_","/",1) not in done
        ]
        tei_files = pending[:args.limit]
        print(f"Modo --same-as-discourse: testando {len(tei_files)} próximos não processados\n")
    elif args.skip:
        tei_files = tei_files_all[args.skip : args.skip + args.limit]
        print(f"Pulando {args.skip}, testando {len(tei_files)} TEIs\n")
    else:
        tei_files = tei_files_all[:args.limit]
        print(f"Testando primeiros {len(tei_files)} TEIs\n")

    if not tei_files:
        print("Nenhum TEI para testar.")
        return

    stats    = Counter()
    failures = []
    tei_ok_heads  = []
    tei_fail_heads = []

    for tei_path in tei_files:
        stem   = tei_path.name.replace(".tei.xml", "")
        handle = stem.replace("_", "/", 1)

        tei = test_tei(str(tei_path))
        ttl = test_ttl(os.path.join(TTL_DIR, stem + ".ttl"))

        if tei["ok"]:
            stats["tei_ok"] += 1
            tei_ok_heads.extend(tei["matched"][:2])
        elif ttl["ok"]:
            stats["ttl_ok"] += 1
        else:
            stats["both_fail"] += 1
            failures.append({"handle": handle, "tei": tei, "ttl": ttl})
            if tei["heads"]:
                tei_fail_heads.extend(tei["heads"][:3])

    ok_total = stats["tei_ok"] + stats["ttl_ok"]
    print(f"{'='*60}")
    print(f"RESULTADO ({len(tei_files)} docs testados)")
    print(f"{'='*60}")
    print(f"  ✓ TEI ok          : {stats['tei_ok']:4d}")
    print(f"  ✓ TTL fallback ok : {stats['ttl_ok']:4d}")
    print(f"  ✗ Ambos falham    : {stats['both_fail']:4d}")
    print(f"  Taxa de sucesso   : {100*ok_total//len(tei_files)}%")
    print()

    reasons = Counter()
    for f in failures:
        if f["tei"]["n_heads"] == 0:
            reasons["TEI sem nenhuma seção com head"] += 1
        elif not f["tei"]["ok"]:
            reasons["TEI tem heads mas nenhum bate nos TARGET_PATTERNS"] += 1
        reasons[f["ttl"].get("reason", "ttl_unknown")] += 1

    print(f"MOTIVOS DE FALHA:")
    for reason, count in reasons.most_common():
        print(f"  {count:3d}x  {reason}")

    if tei_ok_heads:
        print(f"\nExemplos de heads que MATCHARAM:")
        for h in list(set(tei_ok_heads))[:6]:
            print(f"  ✓ '{h}'")

    if tei_fail_heads:
        print(f"\nExemplos de heads que NÃO matcharam:")
        for h in list(set(tei_fail_heads))[:10]:
            print(f"  ✗ '{h}'")

    if failures:
        print(f"\nPrimeiros casos de falha:")
        for f in failures[:5]:
            print(f"\n  {f['handle']}")
            print(f"    TEI heads ({f['tei']['n_heads']}): {f['tei']['heads'][:5]}")
            print(f"    TTL: {f['ttl'].get('reason','?')}")
            if f['ttl'].get('secs'):
                for s in f['ttl']['secs'][:2]:
                    print(f"      [{s['type']}] {s['n_paras']} parágrafos, {s['n_with_content']} com conteúdo")


if __name__ == "__main__":
    main()