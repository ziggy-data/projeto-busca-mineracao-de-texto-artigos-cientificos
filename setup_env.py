#!/usr/bin/env python3
# setup_env.py — prepara o ambiente para execução do projeto
#
# Verifica e instala tudo o que é necessário, supondo que os dados já existem.
# Execute uma vez antes de rodar run_pipeline.py ou qualquer script do projeto.
#
# Uso:
#   python setup_env.py             # verifica e instala tudo
#   python setup_env.py --check     # só verifica, não instala nada
#   python setup_env.py --skip-ollama  # pula verificação de modelos LLM

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# ── Configuração ──────────────────────────────────────────────────────────────

PYTHON_MIN = (3, 10)

# Dependências por fase
REQUIREMENTS = {
    "fase_1": [
        "requests==2.31.0",
        "sickle==0.7.0",
        "tqdm",
        "colorlog",
        "rdflib==7.0.0",
        "beautifulsoup4==4.12.3",
    ],
    "fase_2": [
        "requests==2.31.0",
        "tqdm",
        "rdflib==7.0.0",
    ],
    "fase_3": [
        "requests==2.31.0",
        "rdflib==7.0.0",
        "tqdm",
        "tabulate==0.9.0",
        "numpy",
    ],
    "avaliacao": [
        "requests==2.31.0",
    ],
}

# Modelos ollama necessários
OLLAMA_MODELS = {
    "llama3.1:8b": "Análise de discurso científico (~4.7GB)",
    "nomic-embed-text": "Embeddings para IR semântico (~274MB)",
}

# Imagens Docker necessárias
DOCKER_IMAGES = {
    "secoresearch/fuseki":   "Apache Jena Fuseki (triplestore)",
    "lfoppiano/grobid:0.8.1": "GROBID — extração estrutural de PDFs",
}

# Estrutura de diretórios esperada
EXPECTED_DIRS = [
    "fase_1",
    "fase_1/data",
    "fase_2",
    "fase_2/data/tei",
    "fase_2/data/rdf",
    "fase_3",
    "fase_3/data/discourse",
    "avaliacao",
]

EXPECTED_DATA = [
    ("fase_1/data/manifest.jsonl",   "Manifest OAI-PMH (Fase 1)"),
    ("fase_2/data/tei",              "TEI XMLs (Fase 2)"),
    ("fase_2/data/rdf",              "TTLs RDF (Fase 2)"),
    ("fase_3/data/discourse",        "JSONs de discurso (Fase 3)"),
]

# ── Helpers ───────────────────────────────────────────────────────────────────

OK    = "\033[92m✓\033[0m"
FAIL  = "\033[91m✗\033[0m"
WARN  = "\033[93m⚠\033[0m"
INFO  = "\033[96m→\033[0m"
BOLD  = "\033[1m"
RESET = "\033[0m"


def run(cmd: str, capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, shell=True, capture_output=capture,
        text=True, check=False,
    )


def header(title: str):
    print(f"\n{BOLD}{'─'*55}{RESET}")
    print(f"{BOLD}  {title}{RESET}")
    print(f"{BOLD}{'─'*55}{RESET}")


def ok(msg: str):
    print(f"  {OK}  {msg}")


def fail(msg: str):
    print(f"  {FAIL}  {msg}")


def warn(msg: str):
    print(f"  {WARN}  {msg}")


def info(msg: str):
    print(f"  {INFO}  {msg}")


# ── Verificações ──────────────────────────────────────────────────────────────

def check_python() -> bool:
    v = sys.version_info
    if v >= PYTHON_MIN:
        ok(f"Python {v.major}.{v.minor}.{v.micro}")
        return True
    fail(f"Python {v.major}.{v.minor} — mínimo exigido: {PYTHON_MIN[0]}.{PYTHON_MIN[1]}")
    return False


def check_pip_package(pkg: str) -> bool:
    """Verifica se um pacote está instalado (ignora versão)."""
    base = pkg.split("==")[0].replace("-", "_").lower()
    r = run(f"{sys.executable} -c \"import importlib; importlib.import_module('{base}')\"")
    return r.returncode == 0


def install_requirements(dry_run: bool) -> dict[str, bool]:
    """Instala dependências de todas as fases. Retorna {fase: sucesso}."""
    results = {}
    all_pkgs = list({pkg for pkgs in REQUIREMENTS.values() for pkg in pkgs})

    if dry_run:
        missing = [p for p in all_pkgs if not check_pip_package(p)]
        if missing:
            warn(f"{len(missing)} pacotes não instalados: {', '.join(missing)}")
        else:
            ok("Todos os pacotes Python instalados")
        return {"all": not missing}

    info(f"Instalando {len(all_pkgs)} pacotes Python...")
    cmd = f"{sys.executable} -m pip install {' '.join(all_pkgs)} -q"
    r   = run(cmd, capture=False)
    if r.returncode == 0:
        ok("Pacotes Python instalados")
        results["all"] = True
    else:
        fail("Erro ao instalar pacotes — verifique o pip")
        results["all"] = False

    return results


def check_docker() -> bool:
    r = run("docker info")
    if r.returncode == 0:
        ok("Docker está rodando")
        return True
    fail("Docker não está rodando — abra o Docker Desktop")
    return False


def check_docker_images(dry_run: bool) -> bool:
    all_ok = True
    for image, desc in DOCKER_IMAGES.items():
        r = run(f"docker images -q {image}")
        if r.stdout.strip():
            ok(f"{image}")
        else:
            if dry_run:
                warn(f"{image} não encontrado localmente ({desc})")
                all_ok = False
            else:
                info(f"Baixando {image}...")
                r2 = run(f"docker pull {image}", capture=False)
                if r2.returncode == 0:
                    ok(f"{image} baixado")
                else:
                    fail(f"Erro ao baixar {image}")
                    all_ok = False
    return all_ok


def check_ollama(skip: bool, dry_run: bool) -> bool:
    if skip:
        warn("Verificação do ollama ignorada (--skip-ollama)")
        return True

    import urllib.request
    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3)
    except Exception:
        fail("ollama não está rodando — execute: ollama serve")
        info("Depois instale os modelos:")
        for model, desc in OLLAMA_MODELS.items():
            info(f"  ollama pull {model}  ({desc})")
        return False

    ok("ollama está rodando")

    # Verifica modelos
    try:
        import urllib.request
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5) as resp:
            data     = json.loads(resp.read())
            installed = [m["name"] for m in data.get("models", [])]
    except Exception:
        installed = []

    all_ok = True
    for model, desc in OLLAMA_MODELS.items():
        base = model.split(":")[0]
        if any(base in m for m in installed):
            ok(f"{model}")
        else:
            if dry_run:
                warn(f"{model} não instalado ({desc})")
                all_ok = False
            else:
                info(f"Baixando {model} ({desc})...")
                r = run(f"ollama pull {model}", capture=False)
                if r.returncode == 0:
                    ok(f"{model} instalado")
                else:
                    fail(f"Erro ao baixar {model}")
                    all_ok = False

    return all_ok


def check_directories() -> bool:
    all_ok = True
    for d in EXPECTED_DIRS:
        p = Path(d)
        if p.exists():
            ok(f"{d}/")
        else:
            warn(f"{d}/ não existe — será criado pelo pipeline")
            p.mkdir(parents=True, exist_ok=True)
            info(f"  Criado: {d}/")
    return all_ok


def check_data() -> dict[str, bool]:
    results = {}
    for path, desc in EXPECTED_DATA:
        p = Path(path)
        if p.exists():
            if p.is_file():
                size = p.stat().st_size
                ok(f"{desc}: {path} ({size/1e6:.1f} MB)")
            else:
                n = len(list(p.glob("*")))
                ok(f"{desc}: {path}/ ({n} arquivos)")
            results[path] = True
        else:
            warn(f"{desc}: {path} — não encontrado")
            warn(f"    Execute a fase correspondente antes de prosseguir")
            results[path] = False
    return results


def check_scripts() -> bool:
    """Verifica se todos os scripts principais existem."""
    scripts = [
        "fase_1/collect.py",
        "fase_1/collect_all_sets.py",
        "fase_2/grobid_setup.py",
        "fase_2/process_pdfs.py",
        "fase_2/tei_to_doco.py",
        "fase_2/quality_gate.py",
        "fase_3/fuseki_setup.py",
        "fase_3/discourse_analysis.py",
        "fase_3/enrich_graph.py",
        "fase_3/sparql_queries.py",
        "fase_3/sparql_advanced.py",
        "avaliacao/generate_report.py",
    ]
    all_ok = True
    for s in scripts:
        if Path(s).exists():
            ok(s)
        else:
            fail(f"{s} — não encontrado")
            all_ok = False
    return all_ok


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Prepara o ambiente para execução do projeto Pantheon/UFRJ"
    )
    parser.add_argument("--check",        action="store_true",
                        help="Só verifica, não instala nem baixa nada")
    parser.add_argument("--skip-ollama",  action="store_true",
                        help="Pula verificação do ollama e modelos LLM")
    args = parser.parse_args()

    dry_run = args.check
    mode    = "VERIFICAÇÃO" if dry_run else "INSTALAÇÃO"

    print(f"\n{BOLD}{'='*55}{RESET}")
    print(f"{BOLD}  SETUP — Pantheon COPPE Knowledge Graph{RESET}")
    print(f"{BOLD}  Modo: {mode}{RESET}")
    print(f"{BOLD}{'='*55}{RESET}")

    issues = []

    # ── Python
    header("Python")
    if not check_python():
        issues.append("Python abaixo da versão mínima")

    # ── Pacotes Python
    header("Pacotes Python")
    result = install_requirements(dry_run)
    if not all(result.values()):
        issues.append("Pacotes Python com problemas")

    # ── Docker
    header("Docker")
    docker_ok = check_docker()
    if docker_ok:
        check_docker_images(dry_run)
    else:
        issues.append("Docker não está rodando")

    # ── ollama
    header("ollama + Modelos LLM")
    if not check_ollama(args.skip_ollama, dry_run):
        issues.append("ollama ou modelos LLM não disponíveis")

    # ── Estrutura de diretórios
    header("Estrutura de diretórios")
    check_directories()

    # ── Scripts
    header("Scripts do projeto")
    if not check_scripts():
        issues.append("Alguns scripts não encontrados")

    # ── Dados existentes
    header("Dados existentes")
    data_status = check_data()
    missing_data = [k for k, v in data_status.items() if not v]

    # ── Resumo
    header("Resumo")
    if not issues and not missing_data:
        ok("Ambiente completamente configurado")
        ok("Pronto para executar: python run_pipeline.py")
    else:
        if issues:
            for issue in issues:
                fail(issue)
        if missing_data:
            warn(f"{len(missing_data)} conjuntos de dados ausentes")
            warn("Execute run_pipeline.py --from-scratch para coletar os dados")

    print(f"\n{'='*55}\n")
    return 0 if not issues else 1


if __name__ == "__main__":
    sys.exit(main())
