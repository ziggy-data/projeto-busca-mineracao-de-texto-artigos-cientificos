#!/usr/bin/env python3
# diagnose_llm.py — diagnóstico completo do ollama e GPU
#
# Uso: python diagnose_llm.py
#      python diagnose_llm.py --model llama3.1:8b

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from xml.etree import ElementTree as ET

import requests

OLLAMA_URL = "http://localhost:11434"
TEI_NS     = "http://www.tei-c.org/ns/1.0"


def check_gpu():
    """Verifica se o ollama está usando GPU."""
    print("=== Verificação de GPU ===")
    try:
        # Tenta nvidia-smi
        r = subprocess.run("nvidia-smi --query-gpu=name,memory.used,utilization.gpu --format=csv,noheader",
                           shell=True, capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            print(f"  GPU detectada: {r.stdout.strip()}")
        else:
            print("  nvidia-smi não disponível ou sem GPU NVIDIA")
    except Exception:
        print("  Não foi possível verificar GPU")

    # Verifica variáveis de ambiente do ollama
    try:
        r = subprocess.run("ollama ps", shell=True, capture_output=True, text=True, timeout=5)
        if r.stdout:
            print(f"\n  ollama ps:\n{r.stdout}")
        else:
            print("\n  ollama ps: sem modelos carregados (modelo será carregado no primeiro request)")
    except Exception:
        pass
    print()


def test_minimal_request(model: str) -> bool:
    """Testa o request mais simples possível."""
    print("=== Teste mínimo de request ===")
    print(f"  Enviando 'Say: OK' para {model}...")
    start = time.time()
    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model":  model,
                "prompt": "Say the word OK and nothing else.",
                "stream": False,
                "options": {"num_predict": 5, "temperature": 0},
            },
            timeout=60,
        )
        elapsed = time.time() - start
        if r.status_code == 200:
            resp = r.json().get("response", "").strip()
            print(f"  ✓ Resposta em {elapsed:.1f}s: '{resp}'")
            return True
        else:
            print(f"  ✗ HTTP {r.status_code}: {r.text[:200]}")
            return False
    except requests.exceptions.Timeout:
        print(f"  ✗ Timeout após {time.time()-start:.0f}s — modelo pode estar carregando")
        return False
    except Exception as e:
        print(f"  ✗ Erro: {e}")
        return False


def test_json_request(model: str) -> None:
    """Testa request com instrução de JSON."""
    print("\n=== Teste de JSON com texto científico curto ===")
    prompt = '''Analyze this conclusion: "This work presents a new algorithm for graph coloring. Results show 30% improvement over baseline. Future work includes extending to directed graphs."

Respond ONLY with this JSON (no other text):
{"claims":["fill here"],"limitations":[],"future_work":["fill here"],"rhetorical_type":"conclusion"}'''

    print(f"  Enviando prompt de JSON para {model}...")
    start = time.time()
    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model":  model,
                "prompt": prompt,
                "stream": False,
                "options": {"num_predict": 300, "temperature": 0.1},
            },
            timeout=120,
        )
        elapsed = time.time() - start
        raw = r.json().get("response", "")
        print(f"  Tempo: {elapsed:.1f}s")
        print(f"  Resposta bruta:\n{'-'*40}")
        print(raw[:500] if raw else "(VAZIO)")
        print('-'*40)

        if not raw:
            print("\n  ✗ RESPOSTA VAZIA — possíveis causas:")
            print("    1. Modelo sendo descarregado por falta de VRAM")
            print("    2. OLLAMA_NUM_PARALLEL > 1 causando conflito")
            print("    3. Context window muito curto")
            return

        # Tenta parsear
        clean = re.sub(r"```(?:json)?\s*", "", raw).strip().replace("```", "")
        j = clean.find("{")
        if j >= 0:
            try:
                parsed = json.loads(clean[j:])
                print(f"\n  ✓ JSON válido: {list(parsed.keys())}")
            except json.JSONDecodeError:
                # Tenta fechar JSON truncado
                text = clean[j:]
                text += ']' * max(text.count('[') - text.count(']'), 0)
                text += '}' * max(text.count('{') - text.count('}'), 0)
                try:
                    parsed = json.loads(text)
                    print(f"\n  ⚠ JSON truncado (reparado): {list(parsed.keys())}")
                except Exception:
                    print(f"\n  ✗ JSON inválido mesmo após reparo")
        else:
            print("\n  ✗ Nenhum { encontrado — modelo respondeu em texto livre")

    except requests.exceptions.Timeout:
        elapsed = time.time() - start
        print(f"  ✗ Timeout após {elapsed:.0f}s")


def test_real_section(model: str, tei_dir: str) -> None:
    """Testa com uma seção real do corpus."""
    print("\n=== Teste com seção real do corpus ===")
    ns = {"tei": TEI_NS}
    TARGET = ["conclus", "result", "discuss"]

    sample = None
    for tei in sorted(Path(tei_dir).glob("*.tei.xml"))[:30]:
        try:
            root = ET.parse(tei).getroot()
            body = root.find(".//tei:body", ns)
            if body is None:
                continue
            for div in body.findall(".//tei:div", ns):
                head_el = div.find("tei:head", ns)
                head = " ".join(head_el.itertext()).strip() if head_el is not None else ""
                if not any(kw in head.lower() for kw in TARGET):
                    continue
                paras = [" ".join(p.itertext()).strip() for p in div.findall("tei:p", ns)]
                text  = " ".join(paras)
                if len(text) > 200:
                    sample = (head, text[:1500])
                    break
            if sample:
                break
        except Exception:
            continue

    if not sample:
        print("  Nenhuma seção encontrada")
        return

    head, text = sample
    print(f"  Seção: '{head}'")
    print(f"  Texto: {text[:150]}...\n")

    prompt = f"""Section title: "{head}"
Text: {text}

Respond ONLY with JSON:
{{"claims":[],"contributions":[],"limitations":[],"future_work":[],"keywords_inferred":[],"rhetorical_type":""}}"""

    start = time.time()
    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": model, "prompt": prompt, "stream": False,
                "options": {"num_predict": 600, "temperature": 0.1},
            },
            timeout=180,
        )
        elapsed = time.time() - start
        raw = r.json().get("response", "")
        print(f"  Tempo: {elapsed:.1f}s")
        print(f"  Resposta:\n{'-'*40}")
        print(raw[:600] if raw else "(VAZIO)")
        print('-'*40)
    except Exception as e:
        print(f"  ✗ Erro: {e}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model",   default="llama3.1:8b")
    parser.add_argument("--tei-dir", default="../fase_2/data/tei")
    args = parser.parse_args()

    print(f"Modelo: {args.model}\n")
    check_gpu()
    ok = test_minimal_request(args.model)
    if ok:
        test_json_request(args.model)
        test_real_section(args.model, args.tei_dir)
    else:
        print("\n✗ Request mínimo falhou — resolva isso primeiro antes de continuar.")
        print("\nSugestões:")
        print("  1. Reinicie o ollama: feche o processo ollama e abra novamente")
        print("  2. Verifique VRAM: nvidia-smi (llama3.1:8b precisa de ~5GB)")
        print("  3. Tente um modelo menor: ollama pull llama3.2:3b")
        print("  4. Execute: ollama run llama3.1:8b e teste manualmente")

if __name__ == "__main__":
    main()
