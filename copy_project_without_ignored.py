#!/usr/bin/env python3
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

SRC = Path('/home/astrodados3/luciana_projects/TextAnalysysTest/projeto-busca-mineracao-de-texto-artigos-cientificos').resolve()
DST = Path('/home/astrodados3/luciana_projects/TextAnalysysTest/cprojeto-busca-mineracao-de-texto-artigos-cientificos_COPIA').resolve()


def list_files_to_copy(src: Path) -> list[Path]:
    cmd = [
        'git', '-C', str(src), 'ls-files',
        '--cached', '--others', '--exclude-standard', '-z'
    ]
    result = subprocess.run(cmd, check=True, capture_output=True)
    raw = result.stdout.decode('utf-8', errors='replace')
    rels = [Path(p) for p in raw.split('\x00') if p]
    return rels


def copy_files(src: Path, dst: Path, files: list[Path]) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True, exist_ok=True)

    for rel in files:
        src_path = src / rel
        dst_path = dst / rel

        if not src_path.exists():
            continue

        dst_path.parent.mkdir(parents=True, exist_ok=True)

        if src_path.is_symlink():
            target = src_path.readlink()
            try:
                dst_path.symlink_to(target)
            except FileExistsError:
                dst_path.unlink()
                dst_path.symlink_to(target)
        elif src_path.is_file():
            shutil.copy2(src_path, dst_path)


def main() -> int:
    if not (SRC / '.git').exists():
        print(f'[ERRO] repositório git não encontrado em: {SRC}')
        return 1

    try:
        files = list_files_to_copy(SRC)
    except subprocess.CalledProcessError as e:
        print('[ERRO] falha ao listar arquivos com git ls-files')
        print(e)
        return 1

    copy_files(SRC, DST, files)

    print(f'[OK] cópia criada em: {DST}')
    print(f'[OK] arquivos copiados (respeitando .gitignore): {len(files)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
