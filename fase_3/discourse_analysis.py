#!/usr/bin/env python3
# discourse_analysis.py — extrai claims, limitações e contribuições via LLM local
#
# v3 — otimizações de performance:
#   - num_predict: 700 → 400 (JSON típico usa 200-350 tokens)
#   - num_ctx: padrão → 2048 (menor = mais rápido, suficiente para o prompt)
#   - text input: 3000 → 1500 chars (≈375 tokens, mantém informação essencial)
#   - workers padrão: 2 → 3 (RTX 4070 Super suporta 3 requests paralelos)
#   - num_gpu: 99 explícito (garante que todos os layers ficam na GPU)
#   - Retry com backoff exponencial em vez de timeout fixo
#   - Estimativa de tempo real baseada em ETA dinâmico
#
# Velocidade esperada vs v2:
#   llama3.1:8b: 16h → ~6-8h  (2-2.5x mais rápido)
#   qwen2.5:7b : estimado ~4-5h se score similar ao llama
#
# Uso:
#   python discourse_analysis.py                   # processa tudo
#   python discourse_analysis.py --limit 50        # teste rápido
#   python discourse_analysis.py --reprocess       # reprocessa tudo
#   python discourse_analysis.py --model qwen2.5:7b --workers 3

import argparse
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from xml.etree import ElementTree as ET

import requests
from tqdm import tqdm

# ── Configuração ──────────────────────────────────────────────────────────────
OLLAMA_URL    = "http://localhost:11434"
DEFAULT_MODEL = "llama3.1:8b"
TEI_DIR       = "../fase_2/data/tei"
TTL_DIR       = "../fase_2/data/rdf"     # fallback para seções via RDF
DISCOURSE_DIR = "data/discourse"
REPORT_FILE   = "data/discourse_report.jsonl"
TEI_NS        = "http://www.tei-c.org/ns/1.0"

# ── Padrões de seções-alvo ────────────────────────────────────────────────────
# Cobre: "conclus", "VII - CONCLUSÕES", "Capítulo 5 Conclusão", "7. Conclusion", etc.
TARGET_PATTERNS = [
    r"\bconclu[sz]",          # conclus, conclusion, conclusões, concluding
    r"\bresult[ao]",          # resultado, results
    r"\bdiscus[sz]",          # discuss, discussão
    r"\bcontribu",            # contribuição, contributions
    r"\bconsider[ao]",        # considerações, considerations
    r"\bfinal\s*(remarks?)?", # final, final remarks
    r"\bsummar[yi]",          # summary, summarize
    r"\brecomend",            # recomendações
    r"\bencerr",              # encerramento
    r"\bfinal\s+chapter",
    # Padrões com prefixo numérico/romano
    r"^[IVX\d]+[\.\-\s]+.*\bconclu[sz]",
    r"^[IVX\d]+[\.\-\s]+.*\bresult[ao]",
    r"^[IVX\d]+[\.\-\s]+.*\bdiscus[sz]",
    r"^cap[íi]tulo\s+\d+.*\bconclu[sz]",
    r"^cap[íi]tulo\s+\d+.*\bresult[ao]",
]

SYSTEM_PROMPT = """You are an expert in scientific discourse analysis of academic theses.
Your task is to extract structured information from sections of academic papers.
Always respond with valid JSON only — no preamble, no markdown, no explanation.
The papers are primarily in Portuguese (Brazilian). Extract information as-is,
keeping the original language of the text."""


# Frases no CONTEÚDO que indicam parágrafo de conclusão/resultados
# Usado quando o título da seção não tem keyword retórica (OCR garbage, títulos genéricos)
CONCLUSION_CONTENT_PHRASES = [
    r"\bconclui-se\s+que\b",
    r"\bpode-se\s+concluir\b",
    r"\bneste\s+(trabalho|estudo|artigo)[^.]{0,40}(apresentou|propôs|desenvolveu|demonstrou|foi|foram)\b",
    r"\bnesta\s+(dissertação|tese)[^.]{0,40}(foi|foram|apresentou|propôs)\b",
    r"\bos\s+resultados\s+(obtidos|mostram|indicam|demonstram|confirmam|sugerem)\b",
    r"\bfoi\s+(possível|demonstrado|verificado|comprovado)\s+que\b",
    r"\bcomo\s+conclusão\b",
    r"\bin\s+this\s+(work|thesis|paper|study)[^.]{0,40}(proposed|presented|demonstrated|showed)\b",
    r"\bthe\s+(proposed|present)\s+(work|method|approach)\b",
    r"\bthe\s+results?\s+(show|indicate|demonstrate|confirm|suggest)\b",
    r"\bwe\s+(conclude|showed|demonstrated|proposed|presented)\b",
    r"\bit\s+was\s+(shown|demonstrated|verified|confirmed)\s+that\b",
    r"\bfuture\s+work\s+(includes|will|should|may)\b",
    r"\btrabalhos?\s+futuros?\s+(incluem|incluir[áa]|podem|ser[aã]o)\b",
    r"\bsugest[õo]es\s+para\s+(trabalhos|pesquisas)\s+futuros?\b",
    r"\bperspectivas?\s+de\s+trabalho\s+futuro\b",
]


# Caminhos candidatos para o manifest — mesmo padrão do tei_to_doco.py
MANIFEST_CANDIDATES = [
    "data/manifest.jsonl",
    "../fase_1/data/manifest.jsonl",
    "../../fase_1/data/manifest.jsonl",
    "../data/manifest.jsonl",
    "manifest.jsonl",
]

# Palavras que nunca devem aparecer como keywords — expandida com casos observados
KEYWORD_STOPWORDS = {
    "results", "resultados", "conclusion", "conclusão", "conclusões",
    "methodology", "metodologia", "simulation", "simulação", "simulações",
    "research", "pesquisa", "study", "estudos", "analysis", "análise",
    "work", "trabalho", "method", "método", "approach", "abordagem",
    "future work", "trabalhos futuros", "limitations", "limitações",
    "contribution", "contribuição", "contribuições", "introduction", "introdução",
    "discussion", "discussão", "overview", "summary", "resumo",
    "model", "modelo", "technique", "técnica",
    "data", "dados", "system", "sistema", "process", "processo",
    # Adicionados a partir de casos observados nos testes
    "seção 6.5", "análise da tabela", "melhores resultados dos experimentos",
    "indústria", "comunidade acadêmica", "conhecimento geral",
    "oportunidades de trabalho futuro", "prática",
}

# Frases que indicam que o GROBID leu agradecimentos/dedicatória como título
FAKE_TITLE_MARKERS = [
    "ao prof", "à prof", "ao dr", "à dr",
    "orientador desta", "minha gratidão", "meus sinceros agradecimentos",
    "dedico esta", "dedico este", "dedicatória",
    "a todos os", "a todas as",
    "ao corpo docente", "aos professores",
]


def load_manifest_index() -> tuple[dict, str]:
    """
    Carrega o manifest e retorna (handle→record, caminho_usado).
    Retorna dict vazio se não encontrar — nunca falha.
    """
    for path in MANIFEST_CANDIDATES:
        if os.path.exists(path):
            records = {}
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                        h = r.get("handle")
                        if h:
                            records[h] = r
                    except Exception:
                        pass
            if records:
                return records, path
    return {}, ""


def get_title_from_manifest(handle: str, manifest: dict) -> str:
    """Retorna o título do manifest para um handle, ou string vazia."""
    rec = manifest.get(handle, {})
    return rec.get("title", "").strip()


def is_fake_title(title: str) -> bool:
    """Detecta se o título é na verdade um agradecimento/dedicatória."""
    tl = title.lower()
    return any(marker in tl for marker in FAKE_TITLE_MARKERS)


def make_prompt(section_title: str, section_text: str, doc_title: str) -> str:
    text = section_text[:6000]
    return f"""Analyze this section from an academic thesis titled: "{doc_title}"

Section title: "{section_title}"
Section text:
{text}

Extract the following and respond ONLY with a JSON object (no markdown, no explanation):
{{
  "claims": ["1-5 SPECIFIC findings with concrete details, numbers, comparisons. Only include claims explicitly present in the text. Example of GOOD claim: 'The proposed method reduced error by 23% compared to baseline.' Example of BAD claim: 'Results were obtained.' — do NOT include bad claims."],
  "contributions": ["1-3 specific technical artifacts produced: named algorithms, implementations, datasets, models, frameworks — not generic statements."],
  "limitations": ["0-3 limitations EXPLICITLY stated by the authors. If none mentioned in this text, return []."],
  "future_work": ["0-3 future directions EXPLICITLY mentioned by the authors. If none, return []."],
  "keywords_inferred": ["3-5 specific TECHNICAL terms from this text: algorithm/method/tool/material names. FORBIDDEN words: 'results', 'conclusion', 'methodology', 'analysis', 'research', 'work', 'contributions', 'pesquisa', 'conclusão', 'dados', 'sistema'. Use instead: 'MBBR bioreactor', 'finite element method', 'LSTM network', 'TGA analysis'."],
  "rhetorical_type": "pick exactly ONE: conclusion OR results OR discussion OR contribution OR mixed"
}}"""


# ── Extração de seções do TEI ─────────────────────────────────────────────────

def matches_target(text: str) -> bool:
    t = text.lower().strip()
    return any(re.search(p, t, re.IGNORECASE) for p in TARGET_PATTERNS)


def has_conclusion_content(text: str) -> bool:
    """Retorna True se o texto contém frases típicas de conclusão/resultados."""
    return any(re.search(p, text, re.IGNORECASE) for p in CONCLUSION_CONTENT_PHRASES)


def extract_target_sections_tei(tei_path: str) -> tuple[str, list[dict]]:
    """
    Extrai seções retoricamente relevantes do TEI XML.
    Três níveis de busca:
      1. Título bate em TARGET_PATTERNS (ex: "Conclusões", "Results")
      2. Título numérico/romano + keyword (ex: "VII - CONCLUSÕES")
      3. Conteúdo contém frases de conclusão (ex: "conclui-se que")
         — para casos onde o GROBID extraiu título com OCR garbage
    """
    ns = {"tei": TEI_NS}
    try:
        root = ET.parse(tei_path).getroot()
    except Exception:
        return "", []

    title_el  = root.find(".//tei:titleStmt/tei:title", ns)
    doc_title = " ".join(title_el.itertext()).strip() if title_el is not None else ""

    body = root.find(".//tei:body", ns)
    if body is None:
        return doc_title, []

    sections   = []
    by_content = []  # candidatos pelo nível 3 (conteúdo)

    for i, div in enumerate(body.findall(".//tei:div", ns)):
        head_el  = div.find("tei:head", ns)
        head_txt = " ".join(head_el.itertext()).strip() if head_el is not None else ""

        paras = [
            " ".join(p.itertext()).strip()
            for p in div.findall("tei:p", ns)
            if " ".join(p.itertext()).strip()
        ]
        full_text = " ".join(paras)
        if len(full_text) < 100:
            continue

        if matches_target(head_txt):
            # Nível 1 e 2: título reconhecido
            sections.append({
                "section_index": i,
                "head":          head_txt,
                "text":          full_text,
                "source":        "tei",
            })
        elif has_conclusion_content(full_text):
            # Nível 3: conteúdo indica conclusão mas título não foi reconhecido
            by_content.append({
                "section_index": i,
                "head":          head_txt or "[sem título]",
                "text":          full_text,
                "source":        "tei_content_search",
            })

    # Usa nível 3 apenas se os níveis 1+2 não encontraram nada
    if not sections and by_content:
        sections = by_content

    return doc_title, sections


def extract_target_sections_ttl(ttl_path: str) -> tuple[str, list[dict]]:
    """
    Fallback: extrai seções do TTL quando o TEI não tem títulos matcháveis.
    Lê APENAS seções deo:Conclusion, deo:Results, deo:Discussion.
    NÃO inclui Methods/Background — esses geram claims irrelevantes.
    """
    if not os.path.exists(ttl_path):
        return "", []

    with open(ttl_path, encoding="utf-8") as f:
        lines = f.readlines()

    # Reconstrói índice de blocos por sujeito (mesmo padrão do ner_extractor.py)
    # Necessário porque os parágrafos têm URIs próprios fora do bloco da seção
    blocks: dict = {}
    current = None
    for line in lines:
        m = re.match(r'^(base:\S+)\s+', line)
        if m:
            current = m.group(1)
            blocks.setdefault(current, [])
        if current:
            blocks[current].append(line)

    block_str = {k: "".join(v) for k, v in blocks.items()}

    # Título do documento
    doc_title = ""
    for uri, blk in block_str.items():
        if "fabio:" in blk and "dcterms:title" in blk:
            m = re.search(r'dcterms:title "([^"]{10,300})"', blk)
            if m:
                doc_title = m.group(1).strip()
                break

    # Apenas seções retóricas relevantes para análise de discurso
    # Excluímos deo:Methods e deo:Background — não têm conclusões/claims
    DISCOURSE_DEO = ["deo:Conclusion", "deo:Results", "deo:Discussion"]

    sections = []
    for uri, blk in block_str.items():
        sec_type = next((t for t in DISCOURSE_DEO if t in blk), None)
        if not sec_type:
            continue

        # Título da seção
        title_m = re.search(r'dcterms:title "([^"]+)"', blk)
        head = title_m.group(1).strip() if title_m else ""

        # Parágrafos: a seção lista os URIs em po:contains
        para_uris = re.findall(r'base:(\S+_para_\d+)', blk)
        para_texts = []
        for pu in para_uris:
            pb = block_str.get(f"base:{pu}", "")
            cm = re.search(r'c4o:hasContent "([^"]{10,})"', pb)
            if cm:
                para_texts.append(cm.group(1))

        full_text = " ".join(para_texts)
        if len(full_text) < 100:
            continue

        sections.append({
            "section_index": len(sections),
            "head":          head,
            "text":          full_text,
            "source":        "ttl_fallback",
            "type":          sec_type,   # campo adicionado — evita KeyError
        })

    return doc_title, sections


# ── Chamada ao LLM ────────────────────────────────────────────────────────────

# Parâmetros — cada chamada ao /api/generate é completamente independente.
# Não há histórico compartilhado entre documentos (/api/generate é stateless).
OLLAMA_OPTIONS = {
    "temperature": 0.1,
    "top_p":       0.9,
    "num_predict": 1000,   # margem segura: JSON rico com 4-5 claims = ~360 tokens
                           # o modelo para naturalmente ao fechar o }, não precisa
                           # atingir o limite — subir não penaliza a velocidade
    "num_ctx":     2048,   # suficiente para o prompt (~1000 tokens) — não afeta output
    "num_gpu":     99,     # TODOS os layers na GPU — 70% → 95%+ de uso da RTX 4070
    "keep_alive":  "10m",  # mantém modelo na VRAM entre requests
}


def call_ollama(prompt: str, model: str, retries: int = 2) -> dict | None:
    import time
    for attempt in range(retries + 1):
        try:
            r = requests.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model":  model,
                    "prompt": prompt,
                    "system": SYSTEM_PROMPT,
                    "stream": False,
                    "options": OLLAMA_OPTIONS,
                },
                timeout=120,  # 120s — margem para num_predict=1000
            )
            if r.status_code != 200:
                if attempt < retries:
                    time.sleep(2 ** attempt)
                continue

            raw = r.json().get("response", "")
            if not raw:
                if attempt < retries:
                    time.sleep(1)
                continue

            # Remove markdown code fences
            clean = re.sub(r"```(?:json)?\s*", "", raw).strip().replace("```", "")

            # Encontra o JSON
            j = clean.find("{")
            if j < 0:
                continue

            text = clean[j:]
            # Tenta parsear direto
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                # Tenta fechar JSON truncado
                text += "]" * max(text.count("[") - text.count("]"), 0)
                text += "}" * max(text.count("{") - text.count("}"), 0)
                try:
                    return json.loads(text)
                except Exception:
                    pass

        except Exception:
            if attempt < retries:
                continue

    return None


def normalize_keywords(keywords: list) -> list:
    """
    Remove keywords genéricas usando KEYWORD_STOPWORDS global,
    normaliza case e deduplica.
    """
    seen   = set()
    result = []
    for kw in keywords:
        if not kw:
            continue
        kw_norm = kw.strip()
        kw_low  = kw_norm.lower()
        if kw_low in KEYWORD_STOPWORDS:
            continue
        if len(kw_norm) < 4:
            continue
        if kw_low in seen:
            continue
        seen.add(kw_low)
        result.append(kw_norm)
    return result[:5]


def analyze_one(tei_path: str, handle: str, model: str, manifest: dict) -> dict:
    result = {
        "handle":    handle,
        "status":    "pending",
        "doc_title": "",
        "sections":  [],
    }

    # Tenta TEI primeiro
    doc_title, sections = extract_target_sections_tei(tei_path)

    # Fallback: TTL se TEI não encontrou seções
    if not sections:
        ttl_path = os.path.join(
            TTL_DIR, handle.replace("/", "_") + ".ttl"
        )
        doc_title_ttl, sections = extract_target_sections_ttl(ttl_path)
        if doc_title_ttl and not doc_title:
            doc_title = doc_title_ttl

    # Título autoritativo: manifest prevalece sobre TEI
    # Corrige: GROBID às vezes extrai agradecimentos como título
    manifest_title = get_title_from_manifest(handle, manifest)
    if manifest_title:
        if not doc_title or is_fake_title(doc_title):
            doc_title = manifest_title
    
    result["doc_title"] = doc_title

    if not sections:
        result["status"] = "no_target_sections"
        return result

    doc_results = []
    for sec in sections:
        prompt   = make_prompt(sec["head"], sec["text"], doc_title)
        analysis = call_ollama(prompt, model)

        if analysis:
            # Limpa keywords
            kws = analysis.get("keywords_inferred", [])
            analysis["keywords_inferred"] = normalize_keywords(kws)

            doc_results.append({
                "section_index": sec["section_index"],
                "section_head":  sec["head"],
                "text_length":   len(sec["text"]),
                "source":        sec.get("source", "tei"),
                **analysis,
            })

    result["sections"] = doc_results
    result["status"]   = "ok" if doc_results else "llm_failed"
    return result


def check_ollama(model: str):
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        models = [m["name"] for m in r.json().get("models", [])]
        if not any(model.split(":")[0] in m for m in models):
            print(f"⚠  Modelo '{model}' não encontrado. Execute: ollama pull {model}")
            print(f"   Disponíveis: {models}")
            sys.exit(1)
        print(f"✓ ollama rodando | modelo: {model}")
    except Exception:
        print(f"✗ ollama não acessível em {OLLAMA_URL}")
        sys.exit(1)


def load_done() -> set:
    done = set()
    if not os.path.exists(REPORT_FILE):
        return done
    with open(REPORT_FILE, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
                if r.get("status") == "ok":
                    done.add(r["handle"])
            except Exception:
                pass
    return done


def main():
    parser = argparse.ArgumentParser(description="Análise de discurso via LLM local (v4)")
    parser.add_argument("--limit",     type=int, default=None)
    parser.add_argument("--model",     type=str, default=DEFAULT_MODEL)
    parser.add_argument("--workers",   type=int, default=3,
                        help="Workers paralelos (padrão: 3, recomendado para RTX 4070)")
    parser.add_argument("--reprocess", action="store_true")
    parser.add_argument("--manifest",  type=str, default=None,
                        help="Caminho explícito para o manifest.jsonl")
    args = parser.parse_args()

    check_ollama(args.model)
    os.makedirs(DISCOURSE_DIR, exist_ok=True)

    # Carrega manifest — fonte autoritativa de título e metadados
    candidates = ([args.manifest] if args.manifest else []) + MANIFEST_CANDIDATES
    manifest, manifest_path = load_manifest_index()
    # Se veio --manifest explícito, tenta esse primeiro
    if args.manifest and os.path.exists(args.manifest):
        with open(args.manifest, encoding="utf-8") as f:
            manifest = {}
            for line in f:
                try:
                    r = json.loads(line.strip())
                    if r.get("handle"):
                        manifest[r["handle"]] = r
                except Exception:
                    pass
        manifest_path = args.manifest

    tei_files = sorted(Path(TEI_DIR).glob("*.tei.xml"))
    done      = set() if args.reprocess else load_done()

    tasks = [
        (str(tei), tei.name.replace(".tei.xml", "").replace("_", "/", 1))
        for tei in tei_files
        if tei.name.replace(".tei.xml", "").replace("_", "/", 1) not in done
    ]

    if args.limit:
        tasks = tasks[:args.limit]

    print(f"\nTEIs disponíveis  : {len(tei_files)}")
    print(f"Já analisados     : {len(done)}")
    print(f"A analisar agora  : {len(tasks)}")
    print(f"Workers           : {args.workers}")
    import inspect
    src_make = inspect.getsource(make_prompt)
    tl_match = re.search(r'\[:(\d+)\]', src_make)
    text_limit_display = tl_match.group(1) if tl_match else "6000"
    print(f"Config LLM        : num_predict={OLLAMA_OPTIONS['num_predict']}  "
          f"num_ctx={OLLAMA_OPTIONS['num_ctx']}  "
          f"text_limit={text_limit_display}ch")
    est_secs = len(tasks) * 10 / args.workers
    est_h    = est_secs / 3600
    print(f"Estimativa        : ~{est_h:.1f}h\n")
    print(f"Manifest          : {manifest_path} ({len(manifest)} registros)\n")
    print(f"Fallback TTL      : ativo (recupera docs com seções numéricas)\n")

    if not tasks:
        print("Nada a analisar.")
        return

    stats  = {"ok": 0, "no_sections": 0, "failed": 0, "ttl_fallback": 0}
    report = open(REPORT_FILE, "a", encoding="utf-8")

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(analyze_one, tp, h, args.model, manifest): h
            for tp, h in tasks
        }
        with tqdm(total=len(futures), desc="Discurso LLM", unit="doc") as pbar:
            for future in as_completed(futures):
                res = future.result()
                report.write(json.dumps(res, ensure_ascii=False) + "\n")
                report.flush()

                out = os.path.join(
                    DISCOURSE_DIR, res["handle"].replace("/", "_") + ".json"
                )
                with open(out, "w", encoding="utf-8") as f:
                    json.dump(res, f, ensure_ascii=False, indent=2)

                st = res["status"]
                if st == "ok":
                    stats["ok"] += 1
                    if any(s.get("source") == "ttl_fallback"
                           for s in res.get("sections", [])):
                        stats["ttl_fallback"] += 1
                elif st == "no_target_sections":
                    stats["no_sections"] += 1
                else:
                    stats["failed"] += 1

                pbar.set_postfix(stats, refresh=False)
                pbar.update(1)

    report.close()
    print(f"\n{'='*55}")
    print(f"Análise concluída")
    print(f"  ✓ OK                  : {stats['ok']}")
    print(f"  ✓ Recuperados via TTL : {stats['ttl_fallback']}")
    print(f"  ⚠ Sem seções alvo     : {stats['no_sections']}")
    print(f"  ✗ Falhas LLM          : {stats['failed']}")
    print(f"\nPróximo: python enrich_graph.py")


if __name__ == "__main__":
    main()