#!/usr/bin/env python3
# run_pipeline.py — executa o pipeline completo do projeto
#
# Fases:
#   1. Coleta OAI-PMH do Pantheon/UFRJ   (fase_1/)
#   2. Extração GROBID + RDF DoCO         (fase_2/)
#   3. Fuseki + discurso LLM + SPARQL     (fase_3/)
#   4. Geração do relatório               (avaliacao/)
#
# Uso:
#   python run_pipeline.py                         # pipeline completo
#   python run_pipeline.py --from-step fase_2      # retoma de uma fase
#   python run_pipeline.py --only fase_3           # só uma fase
#   python run_pipeline.py --dry-run               # mostra os comandos, não executa
#   python run_pipeline.py --limit-pdfs 100        # testa com 100 PDFs
#   python run_pipeline.py --skip-collect          # pula coleta (dados já existem)

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# ── Configuração ──────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent.resolve()

STEPS = [
    # (id, nome_display, fase_dir, script, args_padrão, descrição)
    ("fase_1_collect",    "Coleta OAI-PMH",
     "fase_1", "collect_all_sets.py", [],
     "Coleta teses/dissertações do Pantheon via OAI-PMH"),

    ("fase_2_grobid",     "Subir GROBID",
     "fase_2", "grobid_setup.py", [],
     "Sobe o container Docker com GROBID 0.8.1"),

    ("fase_2_process",    "Processar PDFs → TEI",
     "fase_2", "process_pdfs.py", [],
     "Envia PDFs ao GROBID e gera XML TEI"),

    ("fase_2_retry",      "Reprocessar PDFs com falha",
     "fase_2", "retry_failed.py", [],
     "Reprocessa PDFs que deram timeout — aumenta cobertura de 81% para mais"),

    ("fase_2_quality",    "Quality Gate TEI",
     "fase_2", "quality_gate.py", ["stage2"],
     "Valida os TEIs gerados e rejeita os ruins"),

    ("fase_2_convert",    "TEI → DoCO RDF",
     "fase_2", "tei_to_doco.py", [],
     "Converte TEI XML em triplas RDF com ontologias SPAR"),

    ("fase_2_patch",      "Quality Gate TTL + patch metadados",
     "fase_2", "quality_gate.py", ["stage3", "--patch"],
     "Corrige metadados (tipos, datas, subjects) nos TTLs via manifest — garante Tese vs Dissertação corretos"),

    ("fase_2_validate",   "Validar RDF",
     "fase_2", "validate_rdf.py", [],
     "Valida integridade dos TTLs gerados"),

    ("fase_3_fuseki",     "Subir Fuseki",
     "fase_3", "fuseki_setup.py", ["--reload"],
     "Sobe o Apache Jena Fuseki e carrega os TTLs"),

    ("fase_3_discourse",  "Análise de discurso LLM",
     "fase_3", "discourse_analysis.py", [],
     "Extrai claims/limitações/contribuições via llama3.1:8b"),

    ("fase_3_check_disc", "Verificar qualidade do discurso",
     "fase_3", "check_discourse.py", [],
     "Relatório de qualidade da análise LLM antes de enriquecer o grafo"),

    ("fase_3_compare",    "Comparar modelos LLM",
     "avaliacao", "compare_models.py", ["--limit", "30"],
     "Compara llama3.1:8b vs qwen2.5:14b-instruct em 30 documentos"),

    ("fase_3_enrich",     "Enriquecer grafo",
     "fase_3", "enrich_graph.py", [],
     "Insere triplas de discurso no Fuseki"),

    ("fase_3_fix_titles", "Corrigir títulos no Fuseki",
     "fase_3", "fix_titles.py", ["--manifest", "../fase_1/data/manifest.jsonl"],
     "Corrige títulos errados (Lista de Figuras, etc.) — afeta qualidade das queries 7, 14, 15"),

    ("fase_3_sparql",     "Queries SPARQL",
     "fase_3", "sparql_queries.py", ["--export", "data/sparql_results.json"],
     "Executa as 20 queries de análise do corpus"),

    ("fase_3_advanced",   "Queries SPARQL avançadas",
     "fase_3", "sparql_advanced.py", ["--export", "data/sparql_advanced_results.json"],
     "Executa as 10 queries de análise aprofundada"),

    ("avaliacao_report",  "Gerar relatório",
     "avaliacao", "generate_report.py", [],
     "Gera o relatório final em Markdown"),
]

STEP_IDS = [s[0] for s in STEPS]

# ── Helpers ───────────────────────────────────────────────────────────────────

OK    = "\033[92m✓\033[0m"
FAIL  = "\033[91m✗\033[0m"
SKIP  = "\033[94m○\033[0m"
RUN   = "\033[93m▶\033[0m"
BOLD  = "\033[1m"
RESET = "\033[0m"
GRAY  = "\033[90m"


def fmt_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    td = timedelta(seconds=int(seconds))
    h, rem = divmod(td.seconds, 3600)
    m, s   = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m"
    return f"{m}m{s:02d}s"


def run_step(step_id: str, fase_dir: str, script: str, extra_args: list[str],
             desc: str, dry_run: bool, python: str) -> dict:
    """Executa um passo da pipeline. Retorna resultado com status e tempo."""
    script_path = PROJECT_ROOT / fase_dir / script
    work_dir    = PROJECT_ROOT / fase_dir

    cmd_parts = [python, str(script_path)] + extra_args
    cmd_str   = " ".join(cmd_parts)

    print(f"\n  {RUN} {BOLD}{desc}{RESET}")
    print(f"     {GRAY}$ {cmd_str}{RESET}")

    if not script_path.exists():
        print(f"  {FAIL} Script não encontrado: {script_path}")
        return {"step": step_id, "status": "error", "duration": 0,
                "error": f"Script não encontrado: {script_path}"}

    if dry_run:
        print(f"  {SKIP} [dry-run] não executado")
        return {"step": step_id, "status": "skipped", "duration": 0}

    t0 = time.time()
    try:
        result = subprocess.run(
            cmd_parts,
            cwd=str(work_dir),
            check=False,
        )
        duration = time.time() - t0

        if result.returncode == 0:
            print(f"  {OK} Concluído em {fmt_duration(duration)}")
            return {"step": step_id, "status": "ok", "duration": duration}
        else:
            print(f"  {FAIL} Falhou (código {result.returncode}) após {fmt_duration(duration)}")
            return {"step": step_id, "status": "error", "duration": duration,
                    "returncode": result.returncode}

    except KeyboardInterrupt:
        print(f"\n  {FAIL} Interrompido pelo usuário")
        return {"step": step_id, "status": "interrupted", "duration": time.time() - t0}
    except Exception as e:
        return {"step": step_id, "status": "error", "duration": time.time() - t0,
                "error": str(e)}


def save_run_log(results: list[dict], args):
    """Salva log de execução em JSON."""
    log_dir  = PROJECT_ROOT / "avaliacao" / "run_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    log = {
        "timestamp": datetime.now().isoformat(),
        "args": vars(args),
        "total_duration": sum(r.get("duration", 0) for r in results),
        "steps": results,
    }
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)
    return log_file


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Pipeline completo — Pantheon COPPE Knowledge Graph",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Passos disponíveis:
{"".join(f"  {s[0]:<25} {s[5]}{chr(10)}" for s in STEPS)}
Exemplos:
  python run_pipeline.py
  python run_pipeline.py --skip-collect
  python run_pipeline.py --from-step fase_2_convert
  python run_pipeline.py --only fase_3_sparql
  python run_pipeline.py --dry-run
  python run_pipeline.py --limit-pdfs 50
        """,
    )

    parser.add_argument("--from-step", choices=STEP_IDS, default=None,
                        help="Começa a partir deste passo (pula os anteriores)")
    parser.add_argument("--only",      choices=STEP_IDS, default=None,
                        help="Executa apenas este passo")
    parser.add_argument("--skip-collect", action="store_true",
                        help="Pula coleta OAI-PMH (dados já existem)")
    parser.add_argument("--skip-grobid",  action="store_true",
                        help="Pula processamento GROBID (TEIs já existem)")
    parser.add_argument("--skip-discourse", action="store_true",
                        help="Pula análise de discurso LLM (JSONs já existem)")
    parser.add_argument("--limit-pdfs", type=int, default=None,
                        help="Limita número de PDFs processados (para testes)")
    parser.add_argument("--limit-discourse", type=int, default=None,
                        help="Limita documentos na análise de discurso")
    parser.add_argument("--dry-run",  action="store_true",
                        help="Mostra os comandos sem executar")
    parser.add_argument("--no-reload", action="store_true",
                        help="Não recarrega o Fuseki se já estiver rodando")
    parser.add_argument("--model",    default="llama3.1:8b",
                        help="Modelo LLM para análise de discurso")
    args = parser.parse_args()

    python = sys.executable

    # ── Banner
    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}  Pipeline — Pantheon/UFRJ Knowledge Graph{RESET}")
    print(f"{BOLD}  Início: {datetime.now().strftime('%d/%m/%Y %H:%M')}{RESET}")
    print(f"{BOLD}{'='*60}{RESET}")

    if args.dry_run:
        print(f"\n  {SKIP} MODO DRY-RUN — comandos serão exibidos mas não executados\n")

    # ── Determina quais passos executar
    if args.only:
        steps_to_run = [s for s in STEPS if s[0] == args.only]
    elif args.from_step:
        idx = STEP_IDS.index(args.from_step)
        steps_to_run = STEPS[idx:]
    else:
        steps_to_run = STEPS[:]

    # ── Aplica skips e ajustes de args
    skip_set = set()
    if args.skip_collect:
        skip_set.add("fase_1_collect")
        print(f"  {SKIP} Coleta OAI-PMH ignorada (--skip-collect)")
    if args.skip_grobid:
        skip_set.update({"fase_2_grobid", "fase_2_process", "fase_2_quality"})
        print(f"  {SKIP} Processamento GROBID ignorado (--skip-grobid)")
    if args.skip_discourse:
        skip_set.update({"fase_3_discourse", "fase_3_check_disc", "fase_3_compare"})
        print(f"  {SKIP} Análise de discurso ignorada (--skip-discourse)")
    if args.no_reload:
        # Remove --reload do fuseki_setup
        for s in STEPS:
            if s[0] == "fase_3_fuseki" and "--reload" in s[4]:
                s[4].remove("--reload")

    # Ajusta args dos scripts com base nos parâmetros CLI
    arg_overrides: dict[str, list[str]] = {}

    if args.limit_pdfs:
        arg_overrides["fase_2_process"] = ["--limit", str(args.limit_pdfs)]

    if args.limit_discourse:
        arg_overrides["fase_3_discourse"] = [
            "--limit", str(args.limit_discourse), "--model", args.model
        ]
    else:
        arg_overrides["fase_3_discourse"] = ["--model", args.model]

    # ── Estimativa de tempo (em modo normal)
    estimates = {
        "fase_1_collect":    "30-60 min",
        "fase_2_grobid":     "1-2 min",
        "fase_2_process":    "50 min",
        "fase_2_retry":      "10-20 min",
        "fase_2_quality":    "5 min",
        "fase_2_patch":      "5 min",
        "fase_2_convert":    "< 1 min",
        "fase_2_validate":   "5 min",
        "fase_3_fuseki":     "10 min",
        "fase_3_discourse":  "10-17 h",
        "fase_3_check_disc": "< 1 min",
        "fase_3_compare":    "15 min",
        "fase_3_enrich":     "10 min",
        "fase_3_fix_titles": "5-10 min",
        "fase_3_sparql":     "2 min",
        "fase_3_advanced":   "2 min",
        "avaliacao_report":  "< 1 min",
    }

    print(f"\n{BOLD}  Passos a executar:{RESET}")
    for step in steps_to_run:
        step_id = step[0]
        skipped = step_id in skip_set
        est     = estimates.get(step_id, "?")
        status  = f"{GRAY}[skip]{RESET}" if skipped else f"{GRAY}[~{est}]{RESET}"
        print(f"    {'○' if skipped else '▶'}  {step[1]:<30} {status}")

    total_steps = sum(1 for s in steps_to_run if s[0] not in skip_set)
    print(f"\n  {total_steps} passos efetivos | Tempo estimado total: vários horas\n")

    # ── Execução
    results    = []
    t0_total   = time.time()
    step_count = 0
    error_count = 0

    for step in steps_to_run:
        step_id, nome, fase_dir, script, default_args, desc = step

        if step_id in skip_set:
            results.append({"step": step_id, "status": "skipped", "duration": 0})
            continue

        step_count += 1
        n_total = sum(1 for s in steps_to_run if s[0] not in skip_set)
        print(f"\n{BOLD}[{step_count}/{n_total}] {nome}{RESET}")

        extra_args = arg_overrides.get(step_id, default_args)
        result     = run_step(step_id, fase_dir, script, extra_args,
                              desc, args.dry_run, python)
        results.append(result)

        if result["status"] == "error":
            error_count += 1
            print(f"\n  {FAIL} Passo '{nome}' falhou.")
            resp = input("  Continuar mesmo assim? [s/N] ").strip().lower()
            if resp != "s":
                print("  Pipeline interrompida.")
                break

        elif result["status"] == "interrupted":
            print("\n  Pipeline interrompida pelo usuário.")
            break

    # ── Resumo final
    total_duration = time.time() - t0_total
    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}  RESUMO DA EXECUÇÃO{RESET}")
    print(f"{BOLD}{'='*60}{RESET}")

    ok_steps   = sum(1 for r in results if r["status"] == "ok")
    skip_steps = sum(1 for r in results if r["status"] == "skipped")
    err_steps  = sum(1 for r in results if r["status"] == "error")

    print(f"\n  {OK} Concluídos com sucesso : {ok_steps}")
    print(f"  {SKIP} Ignorados (skip)       : {skip_steps}")
    if err_steps:
        print(f"  {FAIL} Com erro               : {err_steps}")

    print(f"\n  Duração total: {fmt_duration(total_duration)}")
    print(f"  Término      : {datetime.now().strftime('%d/%m/%Y %H:%M')}")

    # Detalhes por passo
    print(f"\n  {'Passo':<35} {'Status':<12} {'Tempo'}")
    print(f"  {'─'*55}")
    for r in results:
        nome   = next((s[1] for s in STEPS if s[0] == r["step"]), r["step"])
        status = r["status"]
        dur    = fmt_duration(r.get("duration", 0))
        icon   = OK if status == "ok" else (SKIP if status == "skipped" else FAIL)
        print(f"  {icon} {nome:<33} {status:<12} {dur}")

    # Salva log
    if not args.dry_run:
        log_file = save_run_log(results, args)
        print(f"\n  Log salvo em: {log_file.relative_to(PROJECT_ROOT)}")

    # Mostra o relatório se foi gerado
    report_result = next((r for r in results if r["step"] == "avaliacao_report"), None)
    if report_result and report_result["status"] == "ok":
        report_path = PROJECT_ROOT / "avaliacao" / "relatorio_final.md"
        if report_path.exists():
            print(f"\n  {OK} Relatório disponível em: avaliacao/relatorio_final.md")

    print(f"\n{'='*60}\n")
    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())