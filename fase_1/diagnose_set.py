#!/usr/bin/env python3
# diagnose_set.py — inspeciona os primeiros N registros de um set
# e mostra exatamente quais valores de 'type' e 'date' existem
#
# Uso: python diagnose_set.py col_11422_5817
#      python diagnose_set.py col_11422_96

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from collections import Counter
from sickle import Sickle

SET = sys.argv[1] if len(sys.argv) > 1 else "col_11422_5817"
LIMIT = int(sys.argv[2]) if len(sys.argv) > 2 else 50

sickle = Sickle("https://pantheon.ufrj.br/oai/request", timeout=30)

print(f"Inspecionando set: {SET} (primeiros {LIMIT} registros)\n")

type_counter  = Counter()
date_samples  = []
year_counter  = Counter()
records_seen  = 0

try:
    for rec in sickle.ListRecords(metadataPrefix="oai_dc", set=SET):
        if rec.deleted:
            continue
        meta = rec.metadata

        tipos = [v.strip() for v in (meta.get("type") or []) if v.strip()]
        dates = [v.strip() for v in (meta.get("date") or []) if v.strip()]

        for t in tipos:
            type_counter[t] += 1

        for d in dates:
            year = d[:4] if d else ""
            year_counter[year] += 1
            if len(date_samples) < 10:
                date_samples.append(d)

        records_seen += 1
        if records_seen >= LIMIT:
            break

except Exception as e:
    print(f"Erro: {e}")

print(f"Registros analisados: {records_seen}\n")

print("=== VALORES DE dc:type ===")
for t, c in type_counter.most_common():
    print(f"  {c:4d}x  '{t}'")

print("\n=== ANOS (dc:date[:4]) ===")
for y, c in sorted(year_counter.items()):
    bar = "█" * min(c, 40)
    print(f"  {y or '(vazio)'}  {c:4d}  {bar}")

print(f"\n=== AMOSTRAS DE dc:date ===")
for d in date_samples:
    print(f"  '{d}'")
