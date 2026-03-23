#!/usr/bin/env python3
# fuseki_setup.py — sobe o Apache Jena Fuseki via Docker e carrega os TTLs
#
# Uso:
#   python fuseki_setup.py            # sobe Fuseki e carrega corpus
#   python fuseki_setup.py --reload   # recarrega TTLs (corpus atualizado)
#   python fuseki_setup.py --stop     # para o container

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import requests
from tqdm import tqdm

FUSEKI_IMAGE    = "secoresearch/fuseki"
CONTAINER_NAME  = "fuseki_pantheon"
FUSEKI_PORT     = 3030
FUSEKI_URL      = f"http://localhost:{FUSEKI_PORT}"
DATASET         = "pantheon"          # endpoint: http://localhost:3030/pantheon
FUSEKI_USER     = "admin"
FUSEKI_PASS     = "pantheon123"       # pode alterar
# Caminho para os TTLs gerados na Fase 2
# Ajuste se necessário para o caminho absoluto
RDF_DIR         = "../fase_2/data/rdf"


def run(cmd: str, check=True):
    return subprocess.run(cmd, shell=True, check=check)


def run_silent(cmd: str):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, check=False)


def is_running() -> bool:
    r = run_silent(f"docker ps --filter name={CONTAINER_NAME} --format {{{{.Names}}}}")
    return CONTAINER_NAME in r.stdout


def is_healthy() -> bool:
    try:
        r = requests.get(f"{FUSEKI_URL}/$/ping", timeout=5,
                         auth=(FUSEKI_USER, FUSEKI_PASS))
        return r.status_code == 200
    except Exception:
        return False


def start():
    r = run_silent("docker info")
    if r.returncode != 0:
        print("✗ Docker não está rodando. Abra o Docker Desktop.")
        sys.exit(1)

    stopped = run_silent(
        f"docker ps -a --filter name={CONTAINER_NAME} --format {{{{.Names}}}}"
    ).stdout.strip()

    if stopped == CONTAINER_NAME:
        print("Reiniciando container Fuseki existente...")
        run(f"docker start {CONTAINER_NAME}")
    else:
        print(f"Baixando {FUSEKI_IMAGE}...")
        run(f"docker pull {FUSEKI_IMAGE}")
        print("Subindo Fuseki...")
        run(
            f"docker run -d --name {CONTAINER_NAME} "
            f"-p {FUSEKI_PORT}:3030 "
            f"--memory=6g "
            f"-e ADMIN_PASSWORD={FUSEKI_PASS} "
            f"-e ENABLE_DATA_WRITE=true "
            f"-e ENABLE_UPDATE=true "
            f"-e QUERY_TIMEOUT=120000 "
            f"--restart unless-stopped "
            f"{FUSEKI_IMAGE}"
        )

    print("Aguardando Fuseki inicializar", end="", flush=True)
    for _ in range(60):
        if is_healthy():
            print(" ✓")
            break
        print(".", end="", flush=True)
        time.sleep(2)
    else:
        print(f"\n✗ Timeout. Veja: docker logs {CONTAINER_NAME}")
        sys.exit(1)

    print(f"✓ Fuseki em {FUSEKI_URL}")


def create_dataset():
    """Cria o dataset no Fuseki se não existir."""
    r = requests.get(f"{FUSEKI_URL}/$/datasets/{DATASET}",
                     auth=(FUSEKI_USER, FUSEKI_PASS))
    if r.status_code == 200:
        print(f"Dataset '{DATASET}' já existe.")
        return  # não recria se já existe

    print(f"Criando dataset '{DATASET}'...")
    r = requests.post(
        f"{FUSEKI_URL}/$/datasets",
        data={"dbName": DATASET, "dbType": "tdb2"},
        auth=(FUSEKI_USER, FUSEKI_PASS),
    )
    if r.status_code in (200, 201):
        print(f"✓ Dataset '{DATASET}' criado.")
    else:
        print(f"✗ Erro ao criar dataset: {r.status_code} {r.text[:200]}")
        sys.exit(1)


def load_ttls(reload=False):
    """Carrega todos os TTLs no Fuseki via HTTP upload."""
    rdf_path = Path(RDF_DIR)
    if not rdf_path.exists():
        print(f"✗ Diretório não encontrado: {rdf_path.resolve()}")
        print(f"  Ajuste a variável RDF_DIR no topo do script.")
        sys.exit(1)

    ttl_files = sorted(rdf_path.glob("*.ttl"))
    if not ttl_files:
        print(f"✗ Nenhum TTL encontrado em {rdf_path.resolve()}")
        sys.exit(1)

    print(f"✓ {len(ttl_files)} TTLs encontrados em {rdf_path.resolve()}")

    # Descobre quais já foram carregados (via named graphs)
    if not reload:
        try:
            r = requests.get(
                f"{FUSEKI_URL}/{DATASET}/query",
                params={"query": "SELECT (COUNT(*) as ?n) WHERE { ?s ?p ?o }"},
                auth=(FUSEKI_USER, FUSEKI_PASS),
                timeout=30,
            )
            count = r.json()["results"]["bindings"][0]["n"]["value"]
            if int(count) > 0:
                print(f"Dataset já contém {count} triplas. Use --reload para recarregar.")
                return
        except Exception:
            pass

    upload_url = f"{FUSEKI_URL}/{DATASET}/data"
    stats = {"ok": 0, "error": 0}

    print(f"\nCarregando {len(ttl_files)} TTLs no Fuseki...")

    for ttl in tqdm(ttl_files, desc="Upload TTL", unit="arquivo"):
        handle = ttl.stem.replace("_", "/", 1)
        graph_uri = f"http://pantheon.ufrj.br/graph/{ttl.stem}"

        try:
            with open(ttl, "rb") as f:
                # Envia para o default graph (sem parâmetro 'graph')
                # Isso garante que as queries SPARQL sem GRAPH pattern funcionem
                r = requests.post(
                    upload_url,
                    data=f.read(),
                    headers={"Content-Type": "text/turtle"},
                    auth=(FUSEKI_USER, FUSEKI_PASS),
                    timeout=30,
                )
            if r.status_code in (200, 201, 204):
                stats["ok"] += 1
            else:
                stats["error"] += 1
        except Exception:
            stats["error"] += 1

    # Conta total de triplas
    # Conta triplas no default graph E em named graphs
    count_q = "SELECT (COUNT(*) as ?n) WHERE { { ?s ?p ?o } UNION { GRAPH ?g { ?s ?p ?o } } }"
    r = requests.get(
        f"{FUSEKI_URL}/{DATASET}/query",
        params={"query": count_q},
        auth=(FUSEKI_USER, FUSEKI_PASS),
        timeout=120,
    )
    total = r.json()["results"]["bindings"][0]["n"]["value"]

    print(f"\n{'='*50}")
    print(f"✓ Carregamento concluído")
    print(f"  TTLs enviados : {stats['ok']}")
    print(f"  Erros         : {stats['error']}")
    print(f"  Triplas totais: {total}")
    print(f"\n  SPARQL endpoint : {FUSEKI_URL}/{DATASET}/query")
    print(f"  Interface web   : {FUSEKI_URL}")
    print(f"  Login           : {FUSEKI_USER} / {FUSEKI_PASS}")
    print(f"\nPróximo: python discourse_analysis.py")


def stop():
    run_silent(f"docker stop {CONTAINER_NAME}")
    run_silent(f"docker rm {CONTAINER_NAME}")
    print(f"Fuseki parado.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--stop",   action="store_true")
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    if args.stop:
        stop()
    else:
        start()
        create_dataset()
        load_ttls(reload=args.reload)