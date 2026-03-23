# src/pdf_downloader.py
# Download paralelo de PDFs com validação de tamanho e integridade

import hashlib
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from tqdm import tqdm

import config
from src.dspace_client import resolve_pdf_url
from src.http_client import build_session, safe_get

logger = logging.getLogger(__name__)

MAX_BYTES = config.MAX_PDF_SIZE_MB * 1024 * 1024


def _sanitize_filename(handle: str) -> str:
    """Converte '11422/12345' em '11422_12345.pdf'"""
    return handle.replace("/", "_") + ".pdf"


def _md5_of_file(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _download_one(record: dict, session, pdf_dir: str) -> dict:
    """
    Baixa o PDF de um registro.

    Returns:
        dict com resultado: handle, status, path, size_bytes, md5
    """
    handle   = record["handle"]
    filename = _sanitize_filename(handle)
    dest     = os.path.join(pdf_dir, filename)

    result = {
        "handle":     handle,
        "title":      record.get("title", ""),
        "filename":   filename,
        "pdf_path":   None,
        "status":     "pending",
        "size_bytes": 0,
        "md5":        None,
        "error":      None,
    }

    # Já baixado? Pula (idempotência)
    if os.path.exists(dest) and os.path.getsize(dest) > 1024:
        result.update(status="already_exists", pdf_path=dest,
                      size_bytes=os.path.getsize(dest))
        return result

    # Resolve URL
    pdf_url = resolve_pdf_url(handle, record.get("pdf_url_oai"))
    if not pdf_url:
        result.update(status="no_pdf_url")
        return result

    # HEAD request pra checar tamanho antes de baixar
    try:
        head = session.head(pdf_url, timeout=config.REQUEST_TIMEOUT,
                            allow_redirects=True)
        content_length = int(head.headers.get("Content-Length", 0))
        if content_length > MAX_BYTES:
            result.update(
                status="skipped_too_large",
                size_bytes=content_length,
                error=f"Tamanho {content_length/1e6:.1f}MB > limite {config.MAX_PDF_SIZE_MB}MB",
            )
            return result
    except Exception:
        pass  # Se HEAD falhar, tenta baixar mesmo assim

    # Download com streaming
    resp = safe_get(session, pdf_url, stream=True)
    if resp is None:
        result.update(status="download_failed", error="safe_get retornou None")
        return result

    # Verifica content-type
    ct = resp.headers.get("Content-Type", "")
    if "pdf" not in ct.lower() and not pdf_url.lower().endswith(".pdf"):
        # Pode ser uma página de login/bloqueio, não um PDF
        result.update(status="not_pdf", error=f"Content-Type: {ct}")
        return result

    # Grava em disco com verificação de tamanho
    downloaded = 0
    try:
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    downloaded += len(chunk)
                    if downloaded > MAX_BYTES:
                        f.close()
                        os.remove(dest)
                        result.update(
                            status="skipped_too_large",
                            size_bytes=downloaded,
                            error=f"Excedeu {config.MAX_PDF_SIZE_MB}MB durante download",
                        )
                        return result
                    f.write(chunk)
    except Exception as e:
        result.update(status="write_error", error=str(e))
        if os.path.exists(dest):
            os.remove(dest)
        return result

    # Valida que é realmente um PDF (magic bytes)
    with open(dest, "rb") as f:
        magic = f.read(5)
    if magic != b"%PDF-":
        os.remove(dest)
        result.update(status="invalid_pdf", error="Arquivo não começa com %PDF-")
        return result

    result.update(
        status="ok",
        pdf_path=dest,
        size_bytes=downloaded,
        md5=_md5_of_file(dest),
    )
    return result


def download_batch(records: list[dict], pdf_dir: str = config.PDF_DIR) -> list[dict]:
    """
    Baixa PDFs em paralelo para uma lista de registros.

    Args:
        records:  lista de dicts de metadados (output do oai_harvester)
        pdf_dir:  diretório de destino dos PDFs

    Returns:
        lista de dicts com resultado de cada download
    """
    os.makedirs(pdf_dir, exist_ok=True)
    results = []
    session = build_session()

    stats = {"ok": 0, "already_exists": 0, "no_pdf_url": 0,
             "skipped_too_large": 0, "failed": 0}

    with ThreadPoolExecutor(max_workers=config.PDF_DOWNLOAD_WORKERS) as executor:
        futures = {
            executor.submit(_download_one, rec, session, pdf_dir): rec
            for rec in records
        }

        with tqdm(total=len(futures), desc="Baixando PDFs", unit="pdf") as pbar:
            for future in as_completed(futures):
                res = future.result()
                results.append(res)

                st = res["status"]
                if st in ("ok", "already_exists"):
                    stats[st] += 1
                elif st == "no_pdf_url":
                    stats["no_pdf_url"] += 1
                elif "large" in st:
                    stats["skipped_too_large"] += 1
                else:
                    stats["failed"] += 1
                    logger.warning(
                        "[FALHA] %s — %s: %s",
                        res["handle"], st, res.get("error", ""),
                    )

                pbar.set_postfix(stats, refresh=False)
                pbar.update(1)

    logger.info(
        "Download concluído: %d ok | %d já existiam | "
        "%d sem URL | %d muito grandes | %d falhas",
        stats["ok"], stats["already_exists"],
        stats["no_pdf_url"], stats["skipped_too_large"], stats["failed"],
    )
    return results


def save_download_report(results: list[dict], path: str = "data/download_report.jsonl"):
    """Salva o relatório de downloads em JSONL."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    logger.info("Relatório de downloads salvo em: %s", path)
