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