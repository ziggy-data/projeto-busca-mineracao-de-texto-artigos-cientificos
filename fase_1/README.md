# Pantheon Miner — Fase 1: Coleta

Pipeline de coleta de artigos científicos do repositório Pantheon/UFRJ,
preparada para alimentar as fases seguintes de extração estrutural (GROBID + DoCO)
e análise de discurso científico.

---

## Estrutura do projeto

```
pantheon_pipeline/
├── collect.py          # ponto de entrada principal
├── config.py           # todas as configurações em um lugar só
├── requirements.txt
├── src/
│   ├── oai_harvester.py   # coleta via protocolo OAI-PMH
│   ├── dspace_client.py   # resolve URLs de PDF via REST API do DSpace
│   ├── pdf_downloader.py  # download paralelo com validação
│   ├── http_client.py     # sessão HTTP robusta com retry
│   └── logger_setup.py    # logging colorido + arquivo
└── data/
    ├── metadata/          # JSON individual por artigo
    ├── pdfs/              # PDFs baixados
    ├── logs/              # logs de execução
    ├── manifest.jsonl     # todos os metadados em um arquivo JSONL
    ├── checkpoint.json    # progresso salvo (permite retomar)
    └── download_report.jsonl
```

---

## Setup

```bash
# Crie e ative um ambiente virtual
python -m venv .venv
source .venv/bin/activate       # Linux/macOS
.venv\Scripts\activate          # Windows

# Instale as dependências
pip install -r requirements.txt
```

---

## Como usar

### 1. Descobrir as coleções disponíveis
```bash
python collect.py --list-sets
```
Isso vai listar todos os sets do Pantheon (departamentos, programas de pós-graduação, etc.)
com seus códigos (ex: `com_11422_2`).

### 2. Teste rápido (50 registros, sem PDFs)
```bash
python collect.py --limit 50 --only-metadata
```

### 3. Coleta de uma área específica
```bash
python collect.py --set com_11422_2 --from 2015-01-01
```

### 4. Coleta completa
```bash
python collect.py
```
Se a coleta for interrompida (Ctrl+C, queda de energia, etc.), basta rodar de novo —
ela retoma do checkpoint automaticamente.

### 5. Recomeçar do zero
```bash
python collect.py --reset
```

---

## O que cada metadado contém

Cada registro em `data/manifest.jsonl` tem a estrutura:

```json
{
  "oai_identifier": "oai:pantheon.ufrj.br:11422/12345",
  "handle": "11422/12345",
  "handle_url": "https://pantheon.ufrj.br/handle/11422/12345",
  "title": "Título do artigo",
  "creators": ["Autor 1", "Autor 2"],
  "subjects": ["palavra-chave 1", "palavra-chave 2"],
  "description": "Texto do abstract...",
  "publisher": "UFRJ",
  "date": "2021-03-15",
  "types": ["Tese"],
  "language": "pt",
  "rights": "...",
  "relations": [],
  "pdf_url_oai": "https://pantheon.ufrj.br/bitstream/...",
  "datestamp": "2021-03-16",
  "sets": ["com_11422_2"],
  "collected_at": "2024-01-10T14:23:00"
}
```

---

## Próximos passos (Fases seguintes)

```
Fase 2 — Extração estrutural
  GROBID → XML TEI → mapeamento DoCO → RDF/Turtle

Fase 3 — Análise de discurso
  Llama 3.1 8B (ollama) → claims, limitações, contribuições → triplas RDF

Fase 4 — Triplestore + SPARQL
  Apache Jena Fuseki → consultas semânticas sobre o grafo
```

---

## Configurações importantes (`config.py`)

| Parâmetro | Padrão | Descrição |
|---|---|---|
| `MAX_RECORDS` | None | Limite de registros (None = tudo) |
| `DOWNLOAD_PDFS` | True | Baixar PDFs? |
| `MAX_PDF_SIZE_MB` | 50 | Ignora PDFs maiores que isso |
| `PDF_DOWNLOAD_WORKERS` | 4 | Downloads em paralelo |
| `ACCEPTED_TYPES` | lista | Filtra por tipo de documento |
| `OAI_SET_FILTER` | None | Filtra por coleção |
| `OAI_FROM_DATE` | None | Data de início (YYYY-MM-DD) |

---

## Coleta do corpus PESC

O projeto está configurado para coletar o corpus completo de teses e dissertações
do PESC (Programa de Engenharia de Sistemas e Computação — col_11422_96).

### Antes de começar a coleta real, limpe os dados do teste:

```bash
# Remove o manifest e checkpoint do teste anterior
del data\manifest.jsonl
del data\checkpoint.json
del /s /q data\metadata\*
```

### Depois, rode a coleta completa:

```bash
python collect.py
```

A coleta do PESC completo deve levar entre 30min e 2h dependendo da
velocidade da sua conexão e do tamanho dos PDFs. O progresso é salvo
a cada 100 registros — se cair, só rodar novamente que retoma.

### Estimativa de volume esperado:
O PESC tem histórico desde os anos 1970 e é um dos maiores programas
da COPPE. Estimativa: 2.000–4.000 teses e dissertações no total.