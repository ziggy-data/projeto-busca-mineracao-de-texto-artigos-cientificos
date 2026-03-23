#!/usr/bin/env python3
# collect_all_sets.py — coleta todos os sets configurados em sequência
#
# Uso: python collect_all_sets.py
#
# Deduplicação automática por handle: se um registro já está no manifest,
# ele é ignorado mesmo que apareça em múltiplos sets.

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import config
from src import logger_setup
from src.oai_harvester import harvest
from src.pdf_downloader import download_batch

# ── Corpus de Teses e Dissertações ───────────────────────────────────────────
# Todos os sets confirmados como contendo Tese/Dissertação pelo diagnóstico.
# Ordenados: COPPE primeiro (área mais relevante), depois outras engenharias,
# depois outras áreas da UFRJ para expandir se necessário.

SETS_TO_COLLECT = [
    # ── COPPE — Engenharias (sets individuais, sem os sets pai) ──────────────
    ("col_11422_96",   "PESC — Engenharia de Sistemas e Computação"),
    ("col_11422_90",   "COPPE — Engenharia Elétrica"),
    ("col_11422_88",   "COPPE — Engenharia de Produção"),
    ("col_11422_91",   "COPPE — Engenharia Mecânica"),
    ("col_11422_86",   "COPPE — Engenharia Civil"),
    ("col_11422_95",   "COPPE — Engenharia Química"),
    ("col_11422_92",   "COPPE — Engenharia Metalúrgica e de Materiais"),
    ("col_11422_93",   "COPPE — Engenharia Nuclear"),
    ("col_11422_94",   "COPPE — Engenharia Oceânica"),
    ("col_11422_89",   "COPPE — Engenharia de Transportes"),
    ("col_11422_85",   "COPPE — Engenharia Biomédica"),
    ("col_11422_7616", "COPPE — Engenharia de Nanotecnologia"),
    ("col_11422_17052","COPPE — Engenharia Urbana"),
    # ── Outras áreas da UFRJ ─────────────────────────────────────────────────
    # Descomente para expandir o corpus além da COPPE:
    # ("col_11422_76",   "IBICT — Ciência da Informação"),
]


def run_set(set_spec: str, set_name: str, logger) -> tuple[int, int]:
    logger.info("─" * 60)
    logger.info("▶  %s", set_name)
    logger.info("   setSpec: %s", set_spec)

    config.OAI_SET_FILTER = set_spec

    records = []
    for record in harvest():
        records.append(record)
        safe_handle = record["handle"].replace("/", "_")
        meta_path = os.path.join(config.METADATA_DIR, f"{safe_handle}.json")
        os.makedirs(config.METADATA_DIR, exist_ok=True)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)

    if not records:
        logger.info("   → Sem registros novos (já coletados ou set vazio)")
        return 0, 0

    logger.info("   → %d novos metadados coletados", len(records))

    if not config.DOWNLOAD_PDFS:
        return len(records), 0

    results = download_batch(records)
    ok = sum(1 for r in results if r["status"] in ("ok", "already_exists"))
    failed = sum(1 for r in results if r["status"] not in ("ok", "already_exists", "no_pdf_url"))
    logger.info("   → PDFs: %d ok, %d sem URL, %d falhas",
                ok,
                sum(1 for r in results if r["status"] == "no_pdf_url"),
                failed)
    return len(records), ok


def main():
    logger = logger_setup.setup("collect_all")

    for d in [config.METADATA_DIR, config.PDF_DIR, config.LOG_DIR]:
        os.makedirs(d, exist_ok=True)

    # Conta o que já existe no manifest
    existing = 0
    if os.path.exists(config.MANIFEST_FILE):
        with open(config.MANIFEST_FILE, encoding="utf-8") as f:
            existing = sum(1 for line in f if line.strip())

    logger.info("=" * 60)
    logger.info("COLETA MULTI-SET — TESES E DISSERTAÇÕES UFRJ/COPPE")
    logger.info("  Sets planejados   : %d", len(SETS_TO_COLLECT))
    logger.info("  Já no manifest    : %d documentos", existing)
    logger.info("  Filtro de ano     : >= %s", config.MIN_YEAR or "sem limite")
    logger.info("  Baixar PDFs       : %s", config.DOWNLOAD_PDFS)
    logger.info("=" * 60)

    total_meta = 0
    total_pdfs = 0

    for set_spec, set_name in SETS_TO_COLLECT:
        meta, pdfs = run_set(set_spec, set_name, logger)
        total_meta += meta
        total_pdfs += pdfs

    # Conta total final no manifest
    final_count = 0
    if os.path.exists(config.MANIFEST_FILE):
        with open(config.MANIFEST_FILE, encoding="utf-8") as f:
            final_count = sum(1 for line in f if line.strip())

    logger.info("=" * 60)
    logger.info("COLETA COMPLETA")
    logger.info("  Novos nesta sessão : %d metadados, %d PDFs", total_meta, total_pdfs)
    logger.info("  Total no corpus    : %d documentos", final_count)
    logger.info("  Manifest           : %s", config.MANIFEST_FILE)
    logger.info("  PDFs em            : %s", config.PDF_DIR)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
