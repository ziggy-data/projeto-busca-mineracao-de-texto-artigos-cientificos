#!/usr/bin/env python3
# grobid_setup.py — sobe o GROBID otimizado para processamento em batch

import subprocess
import sys
import time
import requests

GROBID_IMAGE   = "lfoppiano/grobid:0.8.1"
CONTAINER_NAME = "grobid_pantheon"
GROBID_PORT    = 8070
GROBID_URL     = f"http://localhost:{GROBID_PORT}"

# ── Configuração de performance ───────────────────────────────────────────────
# GROBID usa 1 thread por worker no modelo de ML
GROBID_WORKERS = 10      # threads internas do GROBID
GROBID_RAM_GB  = 10     # RAM do container (deixa 6GB para o resto do sistema)


def run(cmd: str, check=True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, shell=True, check=check)


def run_silent(cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, check=False)


def is_running() -> bool:
    r = run_silent(f"docker ps --filter name={CONTAINER_NAME} --format {{{{.Names}}}}")
    return CONTAINER_NAME in r.stdout


def is_healthy() -> bool:
    try:
        r = requests.get(f"{GROBID_URL}/api/isalive", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def check_docker():
    r = run_silent("docker info")
    if r.returncode != 0:
        print("✗ Docker não está acessível.")
        print("  Abra o Docker Desktop e aguarde inicializar.")
        print(f"\n  Erro: {r.stderr[:300]}")
        sys.exit(1)
    print("✓ Docker está rodando")


def stop_existing():
    """Para e remove container existente para recriar com nova config."""
    r = run_silent(f"docker ps -a --filter name={CONTAINER_NAME} --format {{{{.Names}}}}")
    if CONTAINER_NAME in r.stdout:
        print(f"Removendo container antigo ({CONTAINER_NAME})...")
        run_silent(f"docker stop {CONTAINER_NAME}")
        run_silent(f"docker rm {CONTAINER_NAME}")


def start(force_recreate=False):
    check_docker()

    if is_running() and is_healthy() and not force_recreate:
        print(f"✓ GROBID já está rodando em {GROBID_URL}")
        print_info()
        return

    stop_existing()

    print(f"Baixando imagem {GROBID_IMAGE} (pode demorar na primeira vez)...")
    run(f"docker pull {GROBID_IMAGE}")

    print(f"\nSubindo GROBID com {GROBID_WORKERS} workers e {GROBID_RAM_GB}GB RAM...")

    # Configuração de workers via variável de ambiente do GROBID
    run(
        f"docker run -d --name {CONTAINER_NAME} "
        f"-p {GROBID_PORT}:8070 "
        f"-p 8071:8071 "
        f"--memory={GROBID_RAM_GB}g "
        f"--cpus={GROBID_WORKERS} "
        # Passa o número de workers para o GROBID via env var
        f'-e GROBID_NB_WORKERS={GROBID_WORKERS} '
        f"--restart unless-stopped "
        f"{GROBID_IMAGE}"
    )

    print(f"\nAguardando GROBID inicializar", end="", flush=True)
    for _ in range(90):  # até 3 min
        if is_healthy():
            print(" ✓")
            break
        print(".", end="", flush=True)
        time.sleep(2)
    else:
        print(f"\n✗ Timeout. Veja: docker logs {CONTAINER_NAME}")
        sys.exit(1)

    print_info()


def print_info():
    print(f"\n{'='*50}")
    print(f"✓ GROBID rodando em {GROBID_URL}")
    print(f"  Workers    : {GROBID_WORKERS}")
    print(f"  RAM alocada: {GROBID_RAM_GB}GB")
    print(f"  Logs       : docker logs -f {CONTAINER_NAME}")
    print(f"  Parar      : python grobid_setup.py --stop")
    print(f"\nPróximo passo: python process_pdfs.py")
    print(f"{'='*50}")


def stop():
    run_silent(f"docker stop {CONTAINER_NAME}")
    run_silent(f"docker rm {CONTAINER_NAME}")
    print(f"Container {CONTAINER_NAME} parado e removido.")


if __name__ == "__main__":
    if "--stop" in sys.argv:
        stop()
    elif "--restart" in sys.argv:
        start(force_recreate=True)
    else:
        start()