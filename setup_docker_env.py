#!/usr/bin/env python3
"""
setup_docker_env.py

Nova versão de setup para rodar o projeto inteiro em Docker, sem alterar arquivos existentes.

O script gera:
- Dockerfile.pipeline
- docker-compose.pipeline.yml
- .docker/pipeline_entrypoint.sh

E pode opcionalmente:
- buildar imagens
- subir containers
- puxar modelos do ollama
- executar run_pipeline.py dentro do container

Uso:
  python setup_docker_env.py --check
  python setup_docker_env.py --generate
  python setup_docker_env.py --up --build
  python setup_docker_env.py --pull-models
  python setup_docker_env.py --run-pipeline
  python setup_docker_env.py --down
"""

from __future__ import annotations

import argparse
import socket
import shutil
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.resolve()
DOCKER_DIR = PROJECT_ROOT / ".docker"
DOCKERFILE_PATH = PROJECT_ROOT / "Dockerfile.pipeline"
COMPOSE_PATH = PROJECT_ROOT / "docker-compose.pipeline.yml"
ENTRYPOINT_PATH = DOCKER_DIR / "pipeline_entrypoint.sh"

OLLAMA_MODELS = ["llama3.1:8b", "nomic-embed-text", "qwen2.5:14b-instruct"]
GROBID_PORT_CANDIDATES = [8070, 18070, 28070, 38070]

DOCKERFILE_CONTENT = """FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \\
    PYTHONUNBUFFERED=1 \\
    PIP_NO_CACHE_DIR=1

WORKDIR /workspace

RUN apt-get update && apt-get install -y --no-install-recommends \\
    curl ca-certificates socat \\
    && rm -rf /var/lib/apt/lists/*

COPY . /workspace

RUN python -m pip install --upgrade pip && \\
    python -m pip install \\
    requests==2.31.0 sickle==0.7.0 tqdm matplotlib networkx scipy numpy colorlog rdflib==7.0.0 \\
    beautifulsoup4==4.12.3 pyshacl tabulate==0.9.0 numpy

RUN chmod +x /workspace/.docker/pipeline_entrypoint.sh

ENTRYPOINT ["/workspace/.docker/pipeline_entrypoint.sh"]
CMD ["python", "run_pipeline.py"]
"""

BASE_COMPOSE_CONTENT = """services:
  app:
    build:
      context: .
      dockerfile: Dockerfile.pipeline
    container_name: pantheon_app
    depends_on:
      - grobid
      - fuseki
      - ollama
    working_dir: /workspace
    volumes:
      - ./:/workspace
    environment:
      - PYTHONUNBUFFERED=1
    command: ["python", "run_pipeline.py"]

  grobid:
    image: lfoppiano/grobid:0.8.1
    container_name: pantheon_grobid
    ports:
      - "__GROBID_HOST_PORT__:8070"
    restart: unless-stopped

  fuseki:
    image: secoresearch/fuseki
    container_name: pantheon_fuseki
    ports:
      - "3030:3030"
    environment:
      - ADMIN_PASSWORD=pantheon123
      - ENABLE_DATA_WRITE=true
      - ENABLE_UPDATE=true
      - QUERY_TIMEOUT=120000
    restart: unless-stopped

  ollama:
    image: ollama/ollama:latest
    container_name: pantheon_ollama
    ports:
      - "11434:11434"
    volumes:
      - ollama_data:/root/.ollama
    restart: unless-stopped

volumes:
  ollama_data:
"""

ENTRYPOINT_CONTENT = """#!/usr/bin/env sh
set -eu

# Forward local ports expected by legacy scripts (localhost) to compose services.
# This keeps existing code unchanged.
socat TCP-LISTEN:11434,fork,reuseaddr TCP:ollama:11434 >/tmp/socat_ollama.log 2>&1 &
socat TCP-LISTEN:8070,fork,reuseaddr TCP:grobid:8070 >/tmp/socat_grobid.log 2>&1 &
socat TCP-LISTEN:3030,fork,reuseaddr TCP:fuseki:3030 >/tmp/socat_fuseki.log 2>&1 &

exec "$@"
"""


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=PROJECT_ROOT, check=check)


def docker_ok() -> bool:
    return shutil.which("docker") is not None


def compose_cmd() -> list[str]:
    if shutil.which("docker"):
        return ["docker", "compose", "-f", str(COMPOSE_PATH)]
    return []


def is_port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False


def pick_grobid_host_port(preferred: int | None = None) -> int:
    candidates = [preferred] if preferred else GROBID_PORT_CANDIDATES
    for port in candidates:
        if port is None:
            continue
        if is_port_free(int(port)):
            return int(port)
    if preferred:
        raise RuntimeError(f"Porta preferida do GROBID ({preferred}) está ocupada.")
    raise RuntimeError(
        f"Nenhuma porta livre para GROBID nas candidatas: {GROBID_PORT_CANDIDATES}"
    )


def compose_content(use_gpu: bool, gpu_label: str | None = None, grobid_host_port: int = 8070) -> str:
    if not use_gpu and not gpu_label:
        return BASE_COMPOSE_CONTENT.replace("__GROBID_HOST_PORT__", str(grobid_host_port))

    content = BASE_COMPOSE_CONTENT.replace("__GROBID_HOST_PORT__", str(grobid_host_port))

    # Habilita GPU em app e ollama.
    content = content.replace(
        '    command: ["python", "run_pipeline.py"]\n',
        '    command: ["python", "run_pipeline.py"]\n'
        "    gpus:\n"
        "      - driver: nvidia\n"
        "        count: all\n",
    )
    content = content.replace(
        "    restart: unless-stopped\n\nvolumes:",
        "    restart: unless-stopped\n"
        "    gpus:\n"
        "      - driver: nvidia\n"
        "        count: all\n\nvolumes:",
    )

    # Seleção opcional de dispositivo GPU (índice ou UUID).
    if gpu_label:
        content = content.replace(
            "    environment:\n      - PYTHONUNBUFFERED=1\n",
            "    environment:\n"
            "      - PYTHONUNBUFFERED=1\n"
            f"      - NVIDIA_VISIBLE_DEVICES={gpu_label}\n",
        )
        content = content.replace(
            "    volumes:\n      - ollama_data:/root/.ollama\n",
            "    environment:\n"
            f"      - NVIDIA_VISIBLE_DEVICES={gpu_label}\n"
            "    volumes:\n"
            "      - ollama_data:/root/.ollama\n",
        )

    return content


def write_files(use_gpu: bool = False, gpu_label: str | None = None, grobid_host_port: int = 8070) -> None:
    DOCKER_DIR.mkdir(parents=True, exist_ok=True)
    DOCKERFILE_PATH.write_text(DOCKERFILE_CONTENT, encoding="utf-8")
    COMPOSE_PATH.write_text(compose_content(use_gpu, gpu_label, grobid_host_port), encoding="utf-8")
    ENTRYPOINT_PATH.write_text(ENTRYPOINT_CONTENT, encoding="utf-8")
    ENTRYPOINT_PATH.chmod(0o755)


def check_mode() -> int:
    print("\n=== CHECK DOCKER ENV ===")
    if not docker_ok():
        print("[ERRO] docker não encontrado no PATH.")
        return 1
    print("[OK] docker disponível")

    cmd = compose_cmd()
    if not cmd:
        print("[ERRO] docker compose não disponível")
        return 1
    print("[OK] docker compose disponível")

    print("[OK] arquivos serão gerados em:")
    print(f"  - {DOCKERFILE_PATH}")
    print(f"  - {COMPOSE_PATH}")
    print(f"  - {ENTRYPOINT_PATH}")
    return 0


def do_build() -> int:
    cmd = compose_cmd() + ["build", "app"]
    run(cmd)
    return 0


def do_up() -> int:
    cmd = compose_cmd() + ["up", "-d", "grobid", "fuseki", "ollama", "app"]
    run(cmd)
    return 0


def do_down() -> int:
    # Remove serviços e somente imagens locais geradas pelo build deste compose.
    cmd = compose_cmd() + ["down", "--rmi", "local"]
    run(cmd)

    # Limpeza explícita solicitada para evitar resíduos entre execuções.
    run(["docker", "rm", "-f", "grobid_pantheon"], check=False)
    run([
        "docker", "rmi",
        "lfoppiano/grobid:0.8.1",
        "secoresearch/fuseki",
        "ollama/ollama:latest",
    ], check=False)
    return 0


def pull_models(models: list[str]) -> int:
    for m in models:
        cmd = compose_cmd() + ["exec", "ollama", "ollama", "pull", m]
        run(cmd)
    return 0


def run_pipeline(extra_args: list[str]) -> int:
    cmd = compose_cmd() + ["run", "--rm", "app", "python", "run_pipeline.py"] + extra_args
    run(cmd)
    return 0


def wait_grobid_healthy(host_port: int, timeout_s: int = 180) -> bool:
    url = f"http://localhost:{host_port}/api/isalive"
    deadline = time.time() + timeout_s
    print(f"[INFO] aguardando GROBID saudável em {url} (timeout {timeout_s}s)...")

    while time.time() < deadline:
        try:
            with urlopen(url, timeout=5) as resp:
                if resp.status == 200:
                    print("[OK] GROBID saudável")
                    return True
        except URLError:
            pass
        except Exception:
            pass
        time.sleep(2)

    print("[ERRO] timeout aguardando GROBID saudável")
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Gera e orquestra ambiente Docker do projeto")
    parser.add_argument("--check", action="store_true", help="Só valida pré-requisitos")
    parser.add_argument("--generate", action="store_true", help="Só gera arquivos Docker")
    parser.add_argument("--gpu", action="store_true", help="Gera compose com uso de GPU (quando disponível)")
    parser.add_argument("--gpulabel", default=None, help="Seleciona a GPU (ex.: 0, 1, GPU-UUID)")
    parser.add_argument("--grobid-port", type=int, default=None, help="Porta do host para expor o GROBID (se ocupada e não informada, tenta fallback automático)")
    parser.add_argument("--build", action="store_true", help="Build da imagem app")
    parser.add_argument("--up", action="store_true", help="Sobe os serviços")
    parser.add_argument("--down", action="store_true", help="Derruba os serviços e remove imagens locais geradas por este compose")
    parser.add_argument("--pull-models", action="store_true", help="Baixa modelos ollama")
    parser.add_argument("--run-pipeline", action="store_true", help="Executa run_pipeline.py no container app")
    parser.add_argument("--pipeline-args", nargs=argparse.REMAINDER, default=[], help="Args extras para run_pipeline.py")
    args = parser.parse_args()

    if args.check:
        return check_mode()

    if not docker_ok():
        print("[ERRO] docker não encontrado.")
        return 1

    use_gpu = args.gpu or bool(args.gpulabel)
    try:
        grobid_host_port = pick_grobid_host_port(args.grobid_port)
    except RuntimeError as e:
        print(f"[ERRO] {e}")
        return 1

    write_files(use_gpu=use_gpu, gpu_label=args.gpulabel, grobid_host_port=grobid_host_port)
    print("[OK] arquivos Docker gerados")
    print(f"[OK] porta do GROBID no host: {grobid_host_port}")
    if use_gpu:
        print("[OK] modo GPU habilitado no docker-compose para app e ollama")
    if args.gpulabel:
        print(f"[OK] GPU selecionada: {args.gpulabel}")

    if args.generate and not any([args.build, args.up, args.pull_models, args.run_pipeline, args.down]):
        return 0

    if args.build:
        do_build()
        print("[OK] build concluído")

    if args.up:
        do_up()
        print("[OK] serviços ativos")

    if args.pull_models:
        pull_models(OLLAMA_MODELS)
        print("[OK] modelos ollama baixados")

    if args.run_pipeline:
        if not wait_grobid_healthy(grobid_host_port):
            return 1
        run_pipeline(args.pipeline_args)

    if args.down:
        do_down()
        print("[OK] serviços derrubados")

    if not any([args.build, args.up, args.pull_models, args.run_pipeline, args.down, args.generate]):
        print("Nada para executar. Exemplo:")
        print("  python setup_docker_env.py --build --up --pull-models --run-pipeline")

    return 0


if __name__ == "__main__":
    sys.exit(main())
