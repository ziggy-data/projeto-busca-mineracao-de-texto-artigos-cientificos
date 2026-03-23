# src/dspace_client.py
# Resolve URLs de download de PDF para handles do Pantheon/UFRJ
#
# Estratégia em cascata (da mais rápida para a mais lenta):
#   1. URL já veio do OAI-PMH → usa direto
#   2. Scraping da página HTML do handle → rápido, confiável no DSpace 5.x
#   3. REST API do DSpace → fallback se o HTML não funcionar

import logging
import re

import requests
from bs4 import BeautifulSoup

import config
from src.http_client import build_session, safe_get

logger = logging.getLogger(__name__)
_session = build_session()
_bitstream_cache: dict[str, str | None] = {}


def _scrape_handle_page(handle: str) -> str | None:
    """
    Raspa a página HTML do item no Pantheon para encontrar o link de download do PDF.

    No DSpace 5.x, o link do bitstream aparece como:
      <a href="/bitstream/handle/11422/XXXX/arquivo.pdf?sequence=1">
    ou como botão de download com classe específica.
    """
    handle_url = f"{config.PANTHEON_BASE_URL}/handle/{handle}"
    resp = safe_get(_session, handle_url, timeout=config.REQUEST_TIMEOUT)
    if resp is None:
        return None

    try:
        # O Pantheon usa ISO-8859-1 em algumas páginas — deixa o requests detectar
        resp.encoding = resp.apparent_encoding
        soup = BeautifulSoup(resp.text, "html.parser")

        # Padrão 1: links com "/bitstream/handle/" que terminam em .pdf
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/bitstream/" in href and href.lower().endswith(".pdf"):
                if href.startswith("http"):
                    return href
                return config.PANTHEON_BASE_URL + href

        # Padrão 2: links de download com parâmetro sequence
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "sequence=" in href and "/bitstream/" in href:
                if href.startswith("http"):
                    return href
                return config.PANTHEON_BASE_URL + href

    except Exception as e:
        logger.debug("Falha ao raspar handle page %s: %s", handle_url, e)

    return None


def _rest_api_pdf_url(handle: str) -> str | None:
    """
    Fallback: usa a REST API do DSpace para buscar o bitstream PDF.
    Mais lento, usado apenas se o scraping falhar.
    """
    url = f"{config.PANTHEON_REST_URL}/handle/{handle}"
    resp = safe_get(_session, url, params={"expand": "none"},
                    timeout=config.REQUEST_TIMEOUT)
    if resp is None:
        return None

    try:
        data = resp.json()
        item_id = str(data.get("id") or data.get("uuid") or "")
        if not item_id:
            return None
    except Exception:
        return None

    bs_url = f"{config.PANTHEON_REST_URL}/items/{item_id}/bitstreams"
    resp2 = safe_get(_session, bs_url, params={"expand": "none", "limit": 20},
                     timeout=config.REQUEST_TIMEOUT)
    if resp2 is None:
        return None

    try:
        bitstreams = resp2.json()
    except Exception:
        return None

    for bs in bitstreams:
        if bs.get("bundleName") != "ORIGINAL":
            continue
        name = bs.get("name", "").lower()
        mime = bs.get("mimeType", "").lower()
        if "pdf" not in mime and not name.endswith(".pdf"):
            continue
        link = bs.get("retrieveLink") or bs.get("link", "")
        if link:
            return link if link.startswith("http") else config.PANTHEON_BASE_URL + link

    return None


def resolve_pdf_url(handle: str, pdf_url_oai: str | None = None) -> str | None:
    """
    Resolve a URL de download do PDF para um handle.

    Ordem de tentativas:
      1. URL direta do OAI-PMH (se existir)
      2. Scraping da página HTML do handle (rápido)
      3. REST API do DSpace (fallback lento)
    """
    if handle in _bitstream_cache:
        return _bitstream_cache[handle]

    # 1. OAI já trouxe a URL
    if pdf_url_oai:
        _bitstream_cache[handle] = pdf_url_oai
        return pdf_url_oai

    # 2. Scraping da página do handle (método principal)
    pdf_url = _scrape_handle_page(handle)
    if pdf_url:
        logger.debug("PDF encontrado via scraping: %s → %s", handle, pdf_url)
        _bitstream_cache[handle] = pdf_url
        return pdf_url

    # 3. REST API como último recurso
    logger.debug("Scraping falhou, tentando REST API para: %s", handle)
    pdf_url = _rest_api_pdf_url(handle)
    if pdf_url:
        logger.debug("PDF encontrado via REST API: %s → %s", handle, pdf_url)
    else:
        logger.debug("Nenhum PDF encontrado para: %s", handle)

    _bitstream_cache[handle] = pdf_url
    return pdf_url