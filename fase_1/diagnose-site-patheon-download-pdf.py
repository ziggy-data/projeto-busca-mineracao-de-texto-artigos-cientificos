#!/usr/bin/env python3
# diagnose_pdf.py — inspeciona a página de um item do Pantheon
# e mostra todos os links encontrados para entender o padrão do PDF
#
# Uso: python diagnose-site-patheon-download-pdf.py 11422/3693

##

import sys
import requests

PANTHEON_BASE = "https://pantheon.ufrj.br"

handle = sys.argv[1] if len(sys.argv) > 1 else "11422/3693"
url = f"{PANTHEON_BASE}/handle/{handle}"

print(f"Testando: {url}\n")

headers = {"User-Agent": "Mozilla/5.0 (diagnose script)"}
try:
    r = requests.get(url, headers=headers, timeout=30)
    print(f"Status: {r.status_code}")
    print(f"Content-Type: {r.headers.get('Content-Type','')}")
    print(f"Encoding detectado: {r.apparent_encoding}\n")
except Exception as e:
    print(f"ERRO na requisição: {e}")
    sys.exit(1)

# Tenta com BeautifulSoup se disponível
try:
    from bs4 import BeautifulSoup
    r.encoding = r.apparent_encoding
    soup = BeautifulSoup(r.text, "html.parser")

    print("=== TODOS OS LINKS COM 'bitstream' ou 'pdf' ===")
    encontrou = False
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True)[:60]
        if any(kw in href.lower() for kw in ["bitstream", ".pdf", "sequence", "download"]):
            print(f"  HREF : {href}")
            print(f"  TEXTO: {text}")
            print()
            encontrou = True

    if not encontrou:
        print("  Nenhum link com 'bitstream' ou 'pdf' encontrado!\n")
        print("=== PRIMEIROS 50 LINKS DA PÁGINA ===")
        for i, a in enumerate(soup.find_all("a", href=True)[:50]):
            print(f"  {a['href'][:100]}")

except ImportError:
    print("BeautifulSoup NÃO está instalado!")
    print("Rode: pip install beautifulsoup4")
    print()
    print("=== TRECHO DO HTML (busca manual por 'bitstream') ===")
    r.encoding = r.apparent_encoding
    for i, line in enumerate(r.text.splitlines()):
        if any(kw in line.lower() for kw in ["bitstream", ".pdf", "sequence"]):
            print(f"  linha {i}: {line.strip()[:150]}")            