#!/usr/bin/env python3
# process_pdfs.py — envia PDFs ao GROBID com máximo paralelismo
#
# Uso:
#   python process_pdfs.py                  # processa tudo
#   python process_pdfs.py --limit 20       # teste rápido
#   python process_pdfs.py --workers 10     # força número de workers
#   python process_pdfs.py --reprocess      # reprocessa mesmo os já feitos
#   python process_pdfs.py --fast           # pula PDFs > 20MB (mais rápido)

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from tqdm import tqdm

# ── Configuração ──────────────────────────────────────────────────────────────
GROBID_URL      = "http://localhost:8070"
PDF_DIR         = "../fase_1/data/pdfs"
MANIFEST_FILE   = "../fase_1/data/manifest.jsonl"
TEI_DIR         = "data/tei"
PROCESS_REPORT  = "data/grobid_report.jsonl"
ENDPOINT       = f"{GROBID_URL}/api/processFulltextDocument"

# Workers Python = deve ser >= workers do GROBID para saturá-lo
# Com 8 workers no GROBID, use 10-12 aqui (tem overhead de I/O)
DEFAULT_WORKERS = 14
TIMEOUT         = 90    # segundos — reduzido para não travar em PDFs ruins
MAX_RETRIES     = 2     # reduzido — falhou 2x, pula e segue
FAST_SIZE_MB    = 20    # --fast: pula PDFs maiores que isso


def load_done(report_file: str) -> set[str]:
    done = set()
    if not os.path.exists(report_file):
        return done
    with open(report_file, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
                if r.get("status") == "ok":
                    done.add(r["handle"])
            except Exception:
                pass
    return done


def handle_from_filename(filename: str) -> str:
    stem = Path(filename).stem
    parts = stem.split("_", 1)
    return "/".join(parts) if len(parts) == 2 else stem


def process_one(pdf_path: str, handle: str) -> dict:
    tei_path = os.path.join(TEI_DIR, handle.replace("/", "_") + ".tei.xml")
    result = {
        "handle":     handle,
        "pdf_path":   pdf_path,
        "tei_path":   tei_path,
        "status":     "pending",
        "error":      None,
        "size_bytes": os.path.getsize(pdf_path),
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with open(pdf_path, "rb") as f:
                resp = requests.post(
                    ENDPOINT,
                    files={"input": (os.path.basename(pdf_path), f, "application/pdf")},
                    data={
                        "consolidateHeader":      "1",
                        "consolidateCitations":   "0",  # desativado — muito lento
                        "includeRawCitations":    "1",
                        "includeRawAffiliations": "1",
                    },
                    timeout=TIMEOUT,
                )

            if resp.status_code == 200:
                os.makedirs(os.path.dirname(tei_path), exist_ok=True)
                with open(tei_path, "w", encoding="utf-8") as out:
                    out.write(resp.text)
                result["status"] = "ok"
                return result

            elif resp.status_code == 503:
                # GROBID sobrecarregado — backoff curto
                time.sleep(2 * attempt)
                continue
            else:
                result.update(status=f"http_{resp.status_code}",
                               error=resp.text[:150])
                return result

        except requests.exceptions.Timeout:
            if attempt == MAX_RETRIES:
                result.update(status="timeout",
                               error=f"Timeout {TIMEOUT}s após {attempt} tentativas")
                return result
            time.sleep(2)

        except Exception as e:
            result.update(status="error", error=str(e))
            return result

    return result


def estimate_time(n_tasks: int, workers: int) -> str:
    """Estima tempo baseado em benchmark empírico do GROBID (~8s/PDF com 8 workers)."""
    secs_per_pdf = 8  # estimativa conservadora com workers adequados
    total_secs = (n_tasks * secs_per_pdf) / workers
    h, m = divmod(int(total_secs), 3600)
    m //= 60
    return f"~{h}h{m:02d}min" if h else f"~{m}min"


def main():
    parser = argparse.ArgumentParser(description="Processa PDFs com GROBID em paralelo")
    parser.add_argument("--limit",     type=int, default=None)
    parser.add_argument("--workers",   type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--reprocess", action="store_true")
    parser.add_argument("--fast",      action="store_true",
                        help=f"Pula PDFs > {FAST_SIZE_MB}MB para acelerar")
    args = parser.parse_args()

    # Verifica GROBID
    try:
        r = requests.get(f"{GROBID_URL}/api/isalive", timeout=5)
        assert r.status_code == 200
        print(f"✓ GROBID respondendo em {GROBID_URL}")
    except Exception:
        print(f"✗ GROBID não acessível em {GROBID_URL}")
        print("  Execute: python grobid_setup.py")
        sys.exit(1)

    # Verifica número de workers do GROBID
    try:
        info = requests.get(f"{GROBID_URL}/api/version", timeout=5).text
    except Exception:
        info = ""

    os.makedirs(TEI_DIR, exist_ok=True)

    done  = set() if args.reprocess else load_done(PROCESS_REPORT)
    pdfs  = sorted(Path(PDF_DIR).glob("*.pdf"))
    tasks = []

    skipped_done  = 0
    skipped_large = 0

    for pdf in pdfs:
        handle = handle_from_filename(pdf.name)
        if handle in done:
            skipped_done += 1
            continue
        size_mb = pdf.stat().st_size / 1e6
        if args.fast and size_mb > FAST_SIZE_MB:
            skipped_large += 1
            continue
        tasks.append((str(pdf), handle, size_mb))

    # Ordena do menor para o maior — PDFs pequenos primeiro acelera o início
    tasks.sort(key=lambda x: x[2])

    if args.limit:
        tasks = tasks[:args.limit]

    print(f"\n{'='*55}")
    print(f"PDFs encontrados  : {len(pdfs)}")
    print(f"Já processados    : {skipped_done}")
    if skipped_large:
        print(f"Pulados (> {FAST_SIZE_MB}MB) : {skipped_large}")
    print(f"A processar agora : {len(tasks)}")
    print(f"Workers           : {args.workers}")
    print(f"Estimativa        : {estimate_time(len(tasks), args.workers)}")
    print(f"{'='*55}\n")

    if not tasks:
        print("Nada a processar.")
        return

    stats = {"ok": 0, "timeout": 0, "error": 0}
    report = open(PROCESS_REPORT, "a", encoding="utf-8")
    start_time = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(process_one, pdf_path, handle): handle
            for pdf_path, handle, _ in tasks
        }

        with tqdm(total=len(futures), desc="GROBID",
                  unit="pdf", dynamic_ncols=True) as pbar:
            for future in as_completed(futures):
                res = future.result()
                report.write(json.dumps(res, ensure_ascii=False) + "\n")
                report.flush()

                st = res["status"]
                if st == "ok":
                    stats["ok"] += 1
                elif st == "timeout":
                    stats["timeout"] += 1
                else:
                    stats["error"] += 1

                # Estimativa de tempo restante real
                elapsed = time.time() - start_time
                done_n  = sum(stats.values())
                if done_n > 0:
                    eta_secs = (elapsed / done_n) * (len(tasks) - done_n)
                    h, rem   = divmod(int(eta_secs), 3600)
                    eta_str  = f"{h}h{rem//60:02d}m" if h else f"{rem//60}m{rem%60:02d}s"
                else:
                    eta_str = "?"

                pbar.set_postfix({**stats, "ETA": eta_str}, refresh=False)
                pbar.update(1)

    report.close()
    elapsed_total = time.time() - start_time
    h, rem = divmod(int(elapsed_total), 3600)

    print(f"\n{'='*55}")
    print(f"GROBID concluído em {h}h{rem//60:02d}m")
    print(f"  ✓ OK      : {stats['ok']}")
    print(f"  ⏱ Timeout : {stats['timeout']}")
    print(f"  ✗ Erros   : {stats['error']}")
    print(f"  TEI em    : {TEI_DIR}/")
    print(f"\nPróximo: python tei_to_doco.py")


if __name__ == "__main__":
    main()