# src/oai_harvester.py
# Coleta de metadados via protocolo OAI-PMH do Pantheon

import json
import logging
import os
from datetime import datetime
from typing import Iterator

from sickle import Sickle
from sickle.oaiexceptions import NoRecordsMatch

import config

logger = logging.getLogger(__name__)


def _build_sickle() -> Sickle:
    """
    Instancia o cliente OAI-PMH.
    NÃO passamos 'iterator' aqui — o iterador padrão do Sickle funciona
    para todos os verbos (ListSets, ListRecords, Identify, etc.).
    O OAIItemIterator é específico para ListRecords e causaria erro em outros verbos.
    """
    return Sickle(
        config.PANTHEON_OAI_URL,
        max_retries=config.MAX_RETRIES,
        default_retry_after=10,
        timeout=config.REQUEST_TIMEOUT,
    )


def list_sets() -> list[dict]:
    """
    Lista todas as coleções (sets) disponíveis no repositório.
    Útil para descobrir quais áreas/departamentos existem.
    """
    sickle = _build_sickle()
    sets = []
    logger.info("Listando sets disponíveis em %s ...", config.PANTHEON_OAI_URL)
    try:
        for s in sickle.ListSets():
            sets.append({"setSpec": s.setSpec, "setName": s.setName})
            logger.debug("  Set: %s -> %s", s.setSpec, s.setName)
    except Exception as e:
        logger.error("Erro ao listar sets: %s", e)
        raise
    logger.info("Total de sets encontrados: %d", len(sets))
    return sets


def _parse_record(record) -> dict | None:
    """
    Converte um registro OAI-PMH (Dublin Core) num dicionário limpo.
    Retorna None se o registro estiver deletado ou não passar nos filtros.
    """
    if record.deleted:
        return None

    meta = record.metadata  # dict com listas de valores

    def first(key: str) -> str:
        return (meta.get(key) or [""])[0].strip()

    def all_vals(key: str) -> list[str]:
        return [v.strip() for v in (meta.get(key) or []) if v.strip()]

    identifier = record.header.identifier
    handle = identifier.replace("oai:pantheon.ufrj.br:", "")

    tipos = all_vals("type")
    if config.ACCEPTED_TYPES:
        if not any(
            any(aceito.lower() in t.lower() for aceito in config.ACCEPTED_TYPES)
            for t in tipos
        ):
            return None

    # Filtro de ano — extrai o ano do campo dc:date (ex: "2005-03-15" ou "2005")
    raw_date = (meta.get("date") or [""])[0].strip()
    doc_year = None
    if raw_date:
        try:
            doc_year = int(raw_date[:4])
        except (ValueError, IndexError):
            pass

    if config.MIN_YEAR and doc_year and doc_year < config.MIN_YEAR:
        return None
    if config.MAX_YEAR and doc_year and doc_year > config.MAX_YEAR:
        return None

    urls = all_vals("identifier")
    pdf_url = None
    handle_url = None
    for url in urls:
        if url.startswith("http") and "handle" in url:
            handle_url = url
        if url.lower().endswith(".pdf"):
            pdf_url = url

    return {
        "oai_identifier": identifier,
        "handle": handle,
        "handle_url": handle_url or f"https://pantheon.ufrj.br/handle/{handle}",
        "title": first("title"),
        "creators": all_vals("creator"),
        "subjects": all_vals("subject"),
        "description": first("description"),
        "publisher": first("publisher"),
        "date": first("date"),
        "types": tipos,
        "language": first("language"),
        "rights": first("rights"),
        "relations": all_vals("relation"),
        "pdf_url_oai": pdf_url,
        "datestamp": record.header.datestamp,
        "sets": list(record.header.setSpecs),
        "collected_at": datetime.utcnow().isoformat(),
    }


def harvest(
    checkpoint_file: str = config.CHECKPOINT_FILE,
    manifest_file: str = config.MANIFEST_FILE,
) -> Iterator[dict]:
    """
    Gerador principal de coleta OAI-PMH com suporte a checkpoint/retomada.
    """
    os.makedirs(os.path.dirname(checkpoint_file), exist_ok=True)

    resumption_token = None
    total_seen = 0
    total_saved = 0

    if os.path.exists(checkpoint_file):
        with open(checkpoint_file) as f:
            chk = json.load(f)
        resumption_token = chk.get("resumption_token")
        total_seen = chk.get("total_seen", 0)
        total_saved = chk.get("total_saved", 0)
        if resumption_token:
            logger.info(
                "Retomando coleta do checkpoint (ja vistos: %d, salvos: %d)",
                total_seen, total_saved,
            )

    sickle = _build_sickle()

    # Checkpoint é por set — cada set tem o seu arquivo de progresso
    # Isso evita que uma coleta retome o token errado de um set anterior
    if config.OAI_SET_FILTER:
        set_slug = config.OAI_SET_FILTER.replace("/", "_")
        checkpoint_file = checkpoint_file.replace(
            "checkpoint.json", f"checkpoint_{set_slug}.json"
        )

    params: dict = {"metadataPrefix": config.OAI_METADATA_PREFIX}

    if resumption_token:
        params = {"resumptionToken": resumption_token}
    else:
        if config.OAI_SET_FILTER:
            params["set"] = config.OAI_SET_FILTER
        if config.OAI_FROM_DATE:
            params["from"] = config.OAI_FROM_DATE
        if config.OAI_UNTIL_DATE:
            params["until"] = config.OAI_UNTIL_DATE

    try:
        records_iter = sickle.ListRecords(**params)
    except NoRecordsMatch:
        logger.warning("Nenhum registro encontrado com os filtros configurados.")
        return

    os.makedirs(os.path.dirname(manifest_file), exist_ok=True)

    # Carrega handles já coletados para evitar duplicatas no manifest
    already_collected: set[str] = set()
    if os.path.exists(manifest_file):
        with open(manifest_file, encoding="utf-8") as mf:
            for line in mf:
                try:
                    already_collected.add(json.loads(line)["handle"])
                except Exception:
                    pass
        if already_collected:
            logger.info(
                "Deduplicação: %d handles já no manifest, serão ignorados.",
                len(already_collected),
            )

    manifest = open(manifest_file, "a", encoding="utf-8")

    try:
        for raw_record in records_iter:
            total_seen += 1

            if total_seen % 100 == 0:
                token = _get_token(records_iter)
                _save_checkpoint(checkpoint_file, token, total_seen, total_saved)
                logger.info("Progresso: %d vistos / %d aceitos", total_seen, total_saved)

            record = _parse_record(raw_record)
            if record is None:
                continue

            # Pula handles já presentes no manifest (deduplicação cross-set)
            if record["handle"] in already_collected:
                continue

            already_collected.add(record["handle"])
            total_saved += 1
            manifest.write(json.dumps(record, ensure_ascii=False) + "\n")
            manifest.flush()

            yield record

            if config.MAX_RECORDS and total_saved >= config.MAX_RECORDS:
                logger.info("Limite de %d registros atingido.", config.MAX_RECORDS)
                break

    except KeyboardInterrupt:
        logger.warning("Coleta interrompida pelo usuario.")
    finally:
        manifest.close()
        token = _get_token(records_iter)
        _save_checkpoint(checkpoint_file, token, total_seen, total_saved)
        logger.info("Coleta encerrada. Total: %d vistos, %d aceitos.", total_seen, total_saved)


def _get_token(iterator) -> str | None:
    try:
        rt = getattr(iterator, "resumption_token", None)
        return rt.token if rt else None
    except Exception:
        return None


def _save_checkpoint(path: str, token, seen: int, saved: int):
    with open(path, "w") as f:
        json.dump(
            {
                "resumption_token": token,
                "total_seen": seen,
                "total_saved": saved,
                "updated_at": datetime.utcnow().isoformat(),
            },
            f,
            indent=2,
        )