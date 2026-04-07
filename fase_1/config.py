# config.py
# Configurações centrais da pipeline de coleta do Pantheon/UFRJ

# ── Endpoints ────────────────────────────────────────────────────────────────
PANTHEON_OAI_URL  = "https://pantheon.ufrj.br/oai/request"
PANTHEON_REST_URL = "https://pantheon.ufrj.br/rest"
PANTHEON_BASE_URL = "https://pantheon.ufrj.br"

# ── Coleta OAI-PMH ───────────────────────────────────────────────────────────
# Sets de Computação/Engenharia de Sistemas da COPPE/UFRJ
# Execute um set por vez trocando OAI_SET_FILTER, ou None para todos.
# Após coletar cada set, o manifest.jsonl acumula (modo "a" de append).
#
# Sets sugeridos para o corpus:
#   col_11422_96    Engenharia de Sistemas e Computação   (PESC)
#   col_11422_5817  Engenharia de Computação e Informação (PESC complementar)
#   col_11422_5524  Ciência da Computação
#   col_11422_3006  Gerência de Redes e Tecnologia Internet
#   col_11422_5819  Engenharia de Controle e Automação
#
OAI_SET_FILTER      = "col_11422_5819"  # ← troque para cada set novo
OAI_METADATA_PREFIX = "oai_dc"
OAI_FROM_DATE       = None
OAI_UNTIL_DATE      = None

# ── Filtros de tipo e ano ─────────────────────────────────────────────────────
ACCEPTED_TYPES = [
    "Tese",
    "Dissertação",
]

# Filtra por ano do documento (campo dc:date). None = sem limite.
# Documentos anteriores a 2000 costumam ser manuscritos ou scans de baixa
# qualidade — OCR não funciona bem e a extração de texto falha.
MIN_YEAR = 2000
MAX_YEAR = None   # None = sem limite superior

# ── Download de PDFs ─────────────────────────────────────────────────────────
DOWNLOAD_PDFS        = True
MAX_PDF_SIZE_MB      = 80
PDF_DOWNLOAD_WORKERS = 3

# ── Controle de volume ────────────────────────────────────────────────────────
MAX_RECORDS = None

# ── Resiliência ───────────────────────────────────────────────────────────────
REQUEST_TIMEOUT    = 60
MAX_RETRIES        = 5
RETRY_BACKOFF      = 3.0
RETRY_STATUS_CODES = [429, 500, 502, 503, 504]

# ── Paths ─────────────────────────────────────────────────────────────────────
DATA_DIR        = "data"
METADATA_DIR    = "data/metadata"
PDF_DIR         = "data/pdfs"
LOG_DIR         = "data/logs"
CHECKPOINT_FILE = "data/checkpoint.json"
MANIFEST_FILE   = "data/manifest.jsonl"

# ── Organização por tópico/ano ────────────────────────────────────────────────
# Quando True, os PDFs são salvos em:
#   data/pdfs/{AREA}/{ANO}/{handle}.pdf
# A área vem do set OAI-PMH coletado; o ano vem do campo dc:date.
ORGANIZE_BY_TOPIC = True

# Mapeamento set OAI-PMH → nome de pasta (slug legível, sem acentos)
SET_AREA_SLUG = {
    "col_11422_96":    "Engenharia_de_Sistemas",
    "col_11422_90":    "Engenharia_Eletrica",
    "col_11422_88":    "Engenharia_de_Producao",
    "col_11422_91":    "Engenharia_Mecanica",
    "col_11422_86":    "Engenharia_Civil",
    "col_11422_95":    "Engenharia_Quimica",
    "col_11422_92":    "Engenharia_Metalurgica",
    "col_11422_93":    "Engenharia_Nuclear",
    "col_11422_94":    "Engenharia_Oceanica",
    "col_11422_89":    "Engenharia_de_Transportes",
    "col_11422_85":    "Engenharia_Biomedica",
    "col_11422_7616":  "Engenharia_de_Nanotecnologia",
    "col_11422_17052": "Engenharia_Urbana",
    # Adicione novos sets aqui ao expandir o corpus
}


def get_pdf_dir(record: dict, base_dir: str = PDF_DIR) -> str:
    """
    Retorna o diretório onde o PDF deste record deve ser salvo.

    Se ORGANIZE_BY_TOPIC=True:
        base_dir/{AREA}/{ANO}/
    Caso contrário:
        base_dir/

    A área é determinada pelo campo "_area_slug" injetado em collect_all_sets.py,
    com fallback para extração dos subjects CNPq.
    O ano vem do campo "date" do record.
    """
    import os, re

    if not ORGANIZE_BY_TOPIC:
        return base_dir

    # ── Área ──────────────────────────────────────────────────────────────────
    area = record.get("_area_slug", "")

    # Fallback: tenta extrair do primeiro subject CNPq
    if not area:
        for subj in record.get("subjects", []):
            if "CNPQ::" in subj.upper():
                parts = [p.strip() for p in subj.split("::") if p.strip()
                         and p.upper() not in ("CNPQ", "")]
                if parts:
                    slug = parts[-1].upper()
                    slug = re.sub(r"[^A-Z0-9\s]", "", slug)
                    slug = re.sub(r"\s+", "_", slug.strip())
                    area = slug[:40]
                    break

    if not area:
        area = "Sem_Area"

    # ── Ano ───────────────────────────────────────────────────────────────────
    date_str = record.get("date", "") or record.get("datestamp", "")
    if isinstance(date_str, list):
        date_str = date_str[0] if date_str else ""
    m = re.search(r"\b(19|20)\d{2}\b", str(date_str))
    year = m.group() if m and 1970 <= int(m.group()) <= 2030 else "Desconhecido"

    return os.path.join(base_dir, area, year)