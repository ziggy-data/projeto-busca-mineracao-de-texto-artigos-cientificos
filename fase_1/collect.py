#!/usr/bin/env python3
# collect.py  —  Ponto de entrada da pipeline de coleta do Pantheon/UFRJ
#
# Uso básico:
#   python collect.py                    # coleta tudo (metadados + PDFs)
#   python collect.py --only-metadata    # só metadados, sem baixar PDFs
#   python collect.py --list-sets        # lista as coleções disponíveis
#   python collect.py --limit 100        # coleta apenas 100 registros (teste)
#   python collect.py --reset            # ignora checkpoint, começa do zero

import argparse
import json
import os
import sys

# Adiciona o diretório raiz ao path para imports relativos funcionarem
sys.path.insert(0, os.path.dirname(__file__))

import config
from src import logger_setup
from src.oai_harvester import harvest, list_sets
from src.pdf_downloader import download_batch, save_download_report


def parse_args():
    parser = argparse.ArgumentParser(
        description="Pipeline de coleta de artigos científicos do Pantheon/UFRJ",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python collect.py --limit 50                  # teste rápido com 50 registros
  python collect.py --set com_11422_2           # só a coleção da COPPE
  python collect.py --from 2018-01-01           # artigos a partir de 2018
  python collect.py --only-metadata --limit 500 # 500 metadados sem PDFs
        """,
    )
    parser.add_argument("--list-sets",      action="store_true",
                        help="Lista todas as coleções disponíveis e sai")
    parser.add_argument("--only-metadata",  action="store_true",
                        help="Não baixa PDFs, só coleta metadados")
    parser.add_argument("--limit",          type=int, default=None,
                        help="Limita o número de registros coletados")
    parser.add_argument("--set",            type=str, default=None,
                        help="Filtra por set OAI-PMH (ex: com_11422_2)")
    parser.add_argument("--from",           type=str, default=None,
                        dest="from_date",
                        help="Data de início (YYYY-MM-DD)")
    parser.add_argument("--until",          type=str, default=None,
                        dest="until_date",
                        help="Data de fim (YYYY-MM-DD)")
    parser.add_argument("--reset",          action="store_true",
                        help="Ignora checkpoint existente e começa do zero")
    return parser.parse_args()


def apply_args_to_config(args):
    """Aplica argumentos CLI às configurações em tempo de execução."""
    if args.limit:
        config.MAX_RECORDS = args.limit
    if args.set:
        config.OAI_SET_FILTER = args.set
    if args.from_date:
        config.OAI_FROM_DATE = args.from_date
    if args.until_date:
        config.OAI_UNTIL_DATE = args.until_date
    if args.only_metadata:
        config.DOWNLOAD_PDFS = False


def main():
    args = parse_args()
    logger = logger_setup.setup("pantheon")

    # ── Modo: listar sets ─────────────────────────────────────────────────────
    if args.list_sets:
        sets = list_sets()
        print(f"\n{'setSpec':<30} {'Nome'}")
        print("-" * 70)
        for s in sets:
            print(f"{s['setSpec']:<30} {s['setName']}")
        print(f"\nTotal: {len(sets)} coleções")
        return

    apply_args_to_config(args)

    # ── Reset de checkpoint ───────────────────────────────────────────────────
    if args.reset and os.path.exists(config.CHECKPOINT_FILE):
        os.remove(config.CHECKPOINT_FILE)
        logger.info("Checkpoint removido. Iniciando coleta do zero.")

    # ── Garante estrutura de diretórios ───────────────────────────────────────
    for d in [config.METADATA_DIR, config.PDF_DIR, config.LOG_DIR]:
        os.makedirs(d, exist_ok=True)

    logger.info("=" * 60)
    logger.info("PANTHEON MINER — Iniciando coleta")
    logger.info("  Endpoint OAI-PMH : %s", config.PANTHEON_OAI_URL)
    logger.info("  Filtro de set    : %s", config.OAI_SET_FILTER or "todos")
    logger.info("  Tipos aceitos    : %s", config.ACCEPTED_TYPES or "todos")
    logger.info("  Limite           : %s", config.MAX_RECORDS or "sem limite")
    logger.info("  Baixar PDFs      : %s", config.DOWNLOAD_PDFS)
    logger.info("=" * 60)

    # ── Fase 1: Coleta de metadados via OAI-PMH ───────────────────────────────
    logger.info("FASE 1 — Coleta de metadados OAI-PMH")
    records = []

    for record in harvest():
        records.append(record)

        # Salva JSON individual por artigo (fácil de inspecionar)
        safe_handle = record["handle"].replace("/", "_")
        meta_path = os.path.join(config.METADATA_DIR, f"{safe_handle}.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)

    logger.info("Fase 1 concluída: %d registros coletados.", len(records))

    # ── Fase 2: Download de PDFs ──────────────────────────────────────────────
    if config.DOWNLOAD_PDFS and records:
        logger.info("FASE 2 — Download de PDFs (%d registros)", len(records))
        results = download_batch(records)
        save_download_report(results)

        # Resumo final
        ok      = sum(1 for r in results if r["status"] in ("ok", "already_exists"))
        no_pdf  = sum(1 for r in results if r["status"] == "no_pdf_url")
        failed  = len(results) - ok - no_pdf
        total_mb = sum(r["size_bytes"] for r in results) / 1e6

        logger.info("=" * 60)
        logger.info("RESUMO FINAL")
        logger.info("  Metadados coletados : %d", len(records))
        logger.info("  PDFs baixados       : %d", ok)
        logger.info("  Sem PDF disponível  : %d", no_pdf)
        logger.info("  Falhas              : %d", failed)
        logger.info("  Volume total        : %.1f MB", total_mb)
        logger.info("  Manifest            : %s", config.MANIFEST_FILE)
        logger.info("  PDFs em             : %s", config.PDF_DIR)
        logger.info("=" * 60)
    else:
        logger.info("Download de PDFs desativado. Coleta encerrada.")
        logger.info("Manifest salvo em: %s", config.MANIFEST_FILE)


if __name__ == "__main__":
    main()
