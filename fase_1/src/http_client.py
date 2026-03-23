# src/http_client.py
# Cliente HTTP robusto com retry exponencial e logging

import time
import logging
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import config

logger = logging.getLogger(__name__)


def build_session() -> requests.Session:
    """
    Cria uma Session requests com:
      - retry automático em falhas de rede e status codes de erro
      - backoff exponencial
      - timeout padrão
      - headers de identificação (boas práticas para crawlers acadêmicos)
    """
    session = requests.Session()

    retry_strategy = Retry(
        total=config.MAX_RETRIES,
        backoff_factor=config.RETRY_BACKOFF,
        status_forcelist=config.RETRY_STATUS_CODES,
        allowed_methods=["GET", "HEAD"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    session.headers.update({
        "User-Agent": (
            "PantheonMiner/1.0 "
            "(Projeto de mestrado - Busca e Mineração de Texto; "
            "contato: seu_email@ufrj.br)"
        ),
        "Accept": "application/json, text/xml, */*",
    })

    return session


def safe_get(session: requests.Session, url: str, **kwargs) -> requests.Response | None:
    """
    GET com timeout default e tratamento de exceção.
    Retorna None em caso de erro irrecuperável.
    """
    kwargs.setdefault("timeout", config.REQUEST_TIMEOUT)
    try:
        response = session.get(url, **kwargs)
        if response.status_code == 200:
            return response
        logger.warning("HTTP %s ao acessar: %s", response.status_code, url)
        return None
    except requests.exceptions.Timeout:
        logger.error("Timeout ao acessar: %s", url)
    except requests.exceptions.ConnectionError as e:
        logger.error("Erro de conexão em %s: %s", url, e)
    except requests.exceptions.RequestException as e:
        logger.error("Erro inesperado em %s: %s", url, e)
    return None
