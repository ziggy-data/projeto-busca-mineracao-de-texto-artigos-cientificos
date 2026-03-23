#!/usr/bin/env python3
# diagnose.py — testa o endpoint OAI-PMH diretamente sem o Sickle
# Roda antes de tudo para descobrir qual URL/verbo funciona

import requests
import sys

BASE_URLS = [
    "https://pantheon.ufrj.br/oai",
    "https://pantheon.ufrj.br/oai/request",
    "https://pantheon.ufrj.br/oai-pmh/request",
]

VERBS = [
    ("Identify",            {}),
    ("ListMetadataFormats", {}),
    ("ListSets",            {}),
    ("ListRecords",         {"metadataPrefix": "oai_dc"}),
    ("ListRecords",         {"metadataPrefix": "xoai"}),
    ("ListRecords",         {"metadataPrefix": "dim"}),
]

HEADERS = {
    "User-Agent": "DiagnosticBot/1.0 (mestrado UFRJ; contato: aluno@ufrj.br)",
    "Accept": "text/xml, application/xml, */*",
}

def test(url, verb, extra_params):
    params = {"verb": verb, **extra_params}
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=20)
        ct = r.headers.get("Content-Type", "")
        snippet = r.text[:300].replace("\n", " ").strip()
        print(f"  [{r.status_code}] {r.url}")
        print(f"         Content-Type: {ct}")
        print(f"         Resposta    : {snippet}")
        return r.status_code == 200
    except Exception as e:
        print(f"  [ERRO] {url}?verb={verb} → {e}")
        return False

print("=" * 70)
print("DIAGNÓSTICO DO ENDPOINT OAI-PMH — PANTHEON/UFRJ")
print("=" * 70)

working = []

for base in BASE_URLS:
    print(f"\n── Base URL: {base}")
    for verb, extra in VERBS:
        label = verb + (f" (prefix={extra.get('metadataPrefix','')})") if extra else verb
        print(f"\n  >> {label}")
        ok = test(base, verb, extra)
        if ok:
            working.append((base, verb, extra))

print("\n" + "=" * 70)
if working:
    print("FUNCIONOU:")
    for base, verb, extra in working:
        params = "&".join(f"{k}={v}" for k, v in {"verb": verb, **extra}.items())
        print(f"  {base}?{params}")
else:
    print("NENHUMA COMBINAÇÃO FUNCIONOU — verifique conexão ou URL do repositório")
print("=" * 70)
