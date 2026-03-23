#!/usr/bin/env python3
# diagnose_llm.py — testa o LLM com um texto real e mostra a resposta bruta
#
# Uso: python diagnose_llm.py
#      python diagnose_llm.py --model llama3:latest

import argparse
import json
import re
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import requests

OLLAMA_URL = "http://localhost:11434"
TEI_NS     = "http://www.tei-c.org/ns/1.0"

SYSTEM_PROMPT = """You are an expert in scientific discourse analysis of academic theses.
Your task is to extract structured information from sections of academic papers.
Always respond with valid JSON only — no preamble, no markdown, no explanation.
The papers are primarily in Portuguese (Brazilian). Extract information as-is,
keeping the original language of the text."""


def get_sample_section(tei_dir: str) -> tuple[str, str, str] | None:
    """Pega uma seção de conclusão de um TEI real."""
    ns = {"tei": TEI_NS}
    target = ["conclus", "result", "discuss", "considera"]

    for tei in sorted(Path(tei_dir).glob("*.tei.xml"))[:50]:
        try:
            tree = ET.parse(tei)
            root = tree.getroot()
            title_el = root.find(".//tei:titleStmt/tei:title", ns)
            doc_title = " ".join(title_el.itertext()).strip() if title_el is not None else "Sem título"

            body = root.find(".//tei:body", ns)
            if body is None:
                continue

            for div in body.findall(".//tei:div", ns):
                head_el  = div.find("tei:head", ns)
                head_txt = " ".join(head_el.itertext()).strip() if head_el is not None else ""
                if not any(kw in head_txt.lower() for kw in target):
                    continue
                paras = [" ".join(p.itertext()).strip()
                         for p in div.findall("tei:p", ns) if p.text or list(p)]
                text = " ".join(paras)
                if len(text) > 200:
                    return doc_title, head_txt, text[:2000]
        except Exception:
            continue
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model",   default="llama3:latest")
    parser.add_argument("--tei-dir", default="../fase_2/data/tei")
    args = parser.parse_args()

    # Verifica ollama
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        models = [m["name"] for m in r.json().get("models", [])]
        print(f"Modelos disponíveis: {models}\n")
    except Exception:
        print("✗ ollama não acessível")
        sys.exit(1)

    # Pega seção real
    sample = get_sample_section(args.tei_dir)
    if not sample:
        print(f"✗ Nenhuma seção encontrada em: {args.tei_dir}")
        sys.exit(1)

    doc_title, sec_head, sec_text = sample
    print(f"Documento : {doc_title[:80]}")
    print(f"Seção     : {sec_head}")
    print(f"Texto     : {sec_text[:200]}...\n")

    prompt = f"""Analyze this section from an academic thesis titled: "{doc_title}"

Section title: "{sec_head}"
Section text:
{sec_text}

Extract the following and respond ONLY with a JSON object (no markdown):
{{
  "claims": ["list of 1-5 main factual claims or findings stated in this section"],
  "contributions": ["list of 1-3 specific contributions or innovations claimed"],
  "limitations": ["list of 0-3 limitations explicitly mentioned by the authors"],
  "future_work": ["list of 0-3 future work directions mentioned"],
  "keywords_inferred": ["list of 3-5 key technical concepts from this section"],
  "rhetorical_type": "one of: conclusion | results | discussion | contribution | mixed"
}}"""

    print(f"{'='*60}")
    print(f"Enviando para {args.model}...")
    print(f"{'='*60}\n")

    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model":  args.model,
                "prompt": prompt,
                "system": SYSTEM_PROMPT,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 800},
            },
            timeout=120,
        )
        raw = r.json().get("response", "")
        print("RESPOSTA BRUTA DO MODELO:")
        print("-" * 40)
        print(raw)
        print("-" * 40)

        # Tenta parsear
        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if json_match:
            try:
                parsed = json.loads(json_match.group())
                print("\n✓ JSON parseado com sucesso:")
                print(json.dumps(parsed, ensure_ascii=False, indent=2))
            except json.JSONDecodeError as e:
                print(f"\n✗ JSON inválido: {e}")
                print("  Trecho problemático:")
                print(f"  {json_match.group()[:300]}")
        else:
            print("\n✗ Nenhum JSON encontrado na resposta")
            print("  O modelo não seguiu a instrução de responder em JSON puro.")

    except Exception as e:
        print(f"✗ Erro: {e}")


if __name__ == "__main__":
    main()
