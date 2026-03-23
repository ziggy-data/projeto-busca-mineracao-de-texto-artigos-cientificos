#!/usr/bin/env python3
# fix_titles.py — corrige títulos errados direto no Fuseki via SPARQL UPDATE
#
# Estratégia:
#   1. Lê o manifest.jsonl (fonte autoritativa)
#   2. Para cada documento, verifica se o título no Fuseki é um "título ruim"
#      (Lista de Figuras, Resumo da Dissertação, Orientadores, etc.)
#   3. Se for ruim, substitui pelo título do manifest via SPARQL UPDATE
#   4. Gera relatório de quantos foram corrigidos
#
# Uso:
#   python fix_titles.py                    # corrige tudo
#   python fix_titles.py --dry-run          # mostra o que seria corrigido, sem alterar
#   python fix_titles.py --manifest caminho\para\manifest.jsonl

import argparse
import json
import re
import sys
from pathlib import Path

import requests
from tqdm import tqdm

FUSEKI_URL   = "http://localhost:3030"
DATASET      = "pantheon"
FUSEKI_USER  = "admin"
FUSEKI_PASS  = "pantheon123"
UPDATE_URL   = f"{FUSEKI_URL}/{DATASET}/update"
QUERY_URL    = f"{FUSEKI_URL}/{DATASET}/query"

DEFAULT_MANIFEST = "../fase_1/data/manifest.jsonl"

PREFIXES = """
PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX fabio:   <http://purl.org/spar/fabio/>
PREFIX base:    <http://pantheon.ufrj.br/resource/>
"""

# Títulos que o GROBID costuma extrair erroneamente como título do documento
# Estes padrões detectam seções estruturais, agradecimentos e ruído OCR
BAD_TITLE_PATTERNS = [
    # Listas e índices (estrutura do documento)
    r"^lista\s+de\s+(figura|tabela|quadro|abreviatura|símbolo|sigla|algoritmo)",
    r"^list\s+of\s+(figure|table|algorithm|abbreviation|symbol)",
    r"^(sumário|índice|contents?|table\s+of\s+contents?)$",
    # Agradecimentos e dedicatórias
    r"^(agradecimento|acknowledgement|dedicatória|dedico\s)",
    r"^(à|ao|aos|às)\s+\w",      # "À minha família...", "Ao professor..."
    r"^orientador",
    # Resumos mal extraídos
    r"^resumo\s+da\s+(dissertação|tese)",
    r"^(abstract|resumo)\s*$",
    # Capítulos e seções
    r"^capítulo\s+[ivxlcd\d]",
    r"^chapter\s+[ivxlcd\d]",
    # Fragmentos de texto (indicam extração errada)
    r"\b(ufrj|coppe)\b.*\bparte\s+dos\s+requisitos",
    r"pela\s+orientação|pelo\s+estímulo",
    r"^(conclus|result|discuss|introduç|métod|referênc)",  # títulos de seções
    # Strings muito curtas ou muito genéricas
    r"^(introdução|conclusion|results?|discussion|methods?)$",
    # Caracteres de OCR ruim
    r"[•|]{3,}",
    r"\.{5,}",
]

BAD_TITLE_COMPILED = [re.compile(p, re.IGNORECASE) for p in BAD_TITLE_PATTERNS]

MAX_TITLE_LEN = 250
MIN_TITLE_LEN = 5


def is_bad_title(title: str) -> bool:
    """Retorna True se o título parece ser ruído, não o título real do documento."""
    if not title:
        return True
    t = title.strip()
    if len(t) < MIN_TITLE_LEN or len(t) > MAX_TITLE_LEN:
        return True
    # Verifica proporção de caracteres alfabéticos (OCR ruim tem muitos símbolos)
    alpha = sum(c.isalpha() for c in t)
    if alpha / max(len(t), 1) < 0.4:
        return True
    return any(p.search(t) for p in BAD_TITLE_COMPILED)


def get_current_title(handle: str) -> str | None:
    """Busca o título atual do documento no Fuseki."""
    safe = handle.replace("/", "_")
    query = f"""
{PREFIXES}
SELECT ?title WHERE {{
  base:{safe} dcterms:title ?title .
}}
LIMIT 1
"""
    try:
        r = requests.get(
            QUERY_URL,
            params={"query": query},
            headers={"Accept": "application/sparql-results+json"},
            auth=(FUSEKI_USER, FUSEKI_PASS),
            timeout=10,
        )
        bindings = r.json()["results"]["bindings"]
        return bindings[0]["title"]["value"] if bindings else None
    except Exception:
        return None


def update_title(handle: str, new_title: str) -> bool:
    """Substitui o título no Fuseki."""
    safe      = handle.replace("/", "_")
    escaped   = new_title.replace('\\', '\\\\').replace('"', '\\"')
    update    = f"""
{PREFIXES}
DELETE {{ base:{safe} dcterms:title ?old }}
INSERT {{ base:{safe} dcterms:title "{escaped}" }}
WHERE  {{ OPTIONAL {{ base:{safe} dcterms:title ?old }} }}
"""
    try:
        r = requests.post(
            UPDATE_URL,
            data={"update": update},
            auth=(FUSEKI_USER, FUSEKI_PASS),
            timeout=15,
        )
        return r.status_code in (200, 204)
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser(description="Corrige títulos errados no Fuseki")
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST)
    parser.add_argument("--dry-run",  action="store_true",
                        help="Mostra o que seria corrigido sem alterar o Fuseki")
    args = parser.parse_args()

    # Verifica Fuseki
    try:
        r = requests.get(f"{FUSEKI_URL}/$/ping", auth=(FUSEKI_USER, FUSEKI_PASS), timeout=5)
        assert r.status_code == 200
        print(f"✓ Fuseki acessível em {FUSEKI_URL}")
    except Exception:
        print("✗ Fuseki não acessível")
        sys.exit(1)

    # Carrega manifest
    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        print(f"✗ Manifest não encontrado: {manifest_path.resolve()}")
        sys.exit(1)

    records = {}
    with open(manifest_path, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
                if r.get("handle") and r.get("title"):
                    records[r["handle"]] = r["title"].strip()
            except Exception:
                pass

    print(f"✓ {len(records)} registros com título no manifest\n")

    if args.dry_run:
        print("MODO DRY-RUN — nenhuma alteração será feita\n")

    stats = {"verificados": 0, "ruins_sem_manifest": 0, "corrigidos": 0,
             "ja_ok": 0, "erro": 0}
    corrections = []

    for handle, manifest_title in tqdm(records.items(), desc="Verificando títulos"):
        current = get_current_title(handle)
        stats["verificados"] += 1

        # Título atual está bom → pula
        if current and not is_bad_title(current):
            stats["ja_ok"] += 1
            continue

        # Título ruim mas manifest também não tem nada útil
        if is_bad_title(manifest_title):
            stats["ruins_sem_manifest"] += 1
            continue

        # Título ruim → substitui pelo do manifest
        corrections.append({
            "handle":       handle,
            "titulo_ruim":  current or "(vazio)",
            "titulo_novo":  manifest_title,
        })

        if not args.dry_run:
            ok = update_title(handle, manifest_title)
            if ok:
                stats["corrigidos"] += 1
            else:
                stats["erro"] += 1
        else:
            stats["corrigidos"] += 1

    print(f"\n{'='*60}")
    print(f"{'SIMULAÇÃO' if args.dry_run else 'RESULTADO'} DA CORREÇÃO DE TÍTULOS")
    print(f"{'='*60}")
    print(f"  Documentos verificados       : {stats['verificados']}")
    print(f"  Títulos já corretos          : {stats['ja_ok']}")
    print(f"  Títulos ruins (sem fallback) : {stats['ruins_sem_manifest']}")
    print(f"  {'Seriam' if args.dry_run else 'Foram'} corrigidos : {stats['corrigidos']}")
    if stats["erro"]:
        print(f"  Erros                        : {stats['erro']}")

    if corrections:
        print(f"\n── Primeiros 10 exemplos de correção ──────────────────")
        for c in corrections[:10]:
            print(f"  [{c['handle']}]")
            print(f"    ANTES : {c['titulo_ruim'][:80]}")
            print(f"    DEPOIS: {c['titulo_novo'][:80]}")
            print()

    if args.dry_run and corrections:
        print(f"Para aplicar as {len(corrections)} correções, rode sem --dry-run:")
        print(f"  python fix_titles.py")


if __name__ == "__main__":
    main()