#!/usr/bin/env python3
# diagnose_find_thesis_sets.py
# Varre todos os sets e mostra quais têm Tese/Dissertação
# Útil para encontrar os sets corretos para o corpus
#
# Uso: python diagnose_find_thesis_sets.py
# Pode demorar ~2 min pois verifica cada set com uma amostra rápida

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from collections import Counter
from sickle import Sickle
import json

sickle = Sickle("https://pantheon.ufrj.br/oai/request", timeout=30)

THESIS_KEYWORDS = ["tese", "dissertação", "thesis", "dissertation"]

# Carrega todos os sets
print("Carregando lista de sets...", flush=True)
all_sets = [(s.setSpec, s.setName) for s in sickle.ListSets()]
print(f"Total de sets: {len(all_sets)}\n")

# Filtra sets que parecem relevantes pelo nome
RELEVANT_KEYWORDS = [
    "computação", "informação", "sistemas", "redes", "controle",
    "engenharia", "informática", "teses", "dissertações", "coppe",
]
candidate_sets = [
    (spec, name) for spec, name in all_sets
    if any(kw in name.lower() for kw in RELEVANT_KEYWORDS)
]
print(f"Sets candidatos por nome: {len(candidate_sets)}\n")

results = []

for spec, name in candidate_sets:
    type_counter = Counter()
    count = 0
    try:
        for rec in sickle.ListRecords(metadataPrefix="oai_dc", set=spec):
            if rec.deleted:
                continue
            tipos = [v.strip() for v in (rec.metadata.get("type") or []) if v.strip()]
            for t in tipos:
                type_counter[t] += 1
            count += 1
            if count >= 20:  # amostra de 20 registros por set
                break
    except Exception:
        continue

    has_thesis = any(
        any(kw in t.lower() for kw in THESIS_KEYWORDS)
        for t in type_counter
    )

    tipo_str = ", ".join(f"{t}({c})" for t, c in type_counter.most_common(3))
    mark = "✓ TESE/DISS" if has_thesis else "✗ outro"
    print(f"  [{mark}]  {spec:<22} {name[:40]:<40}  tipos: {tipo_str}")

    if has_thesis:
        results.append({"spec": spec, "name": name, "types": dict(type_counter)})

print(f"\n{'='*70}")
print(f"Sets com Tese/Dissertação encontrados: {len(results)}")
for r in results:
    print(f"  {r['spec']:<22} {r['name']}")

# Salva resultado
with open("data/thesis_sets.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print(f"\nResultado salvo em: data/thesis_sets.json")
