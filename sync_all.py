"""Executa todas as sincronizações na ordem segura.

Ordem: tabelas de referência (sindicato, centro, setor, função, horário),
depois pessoa/gestor/diretor, depois titulares, depois dependentes
(dependentes precisam dos titulares para o connector).

Uso:
    python sync_all.py [--dry-run]
    python sync_all.py --only 0001,0002
"""
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ORDER = [
    ("PIPEFY_0002", "sync.sync_0002_sindicato"),
    ("PIPEFY_0003", "sync.sync_0003_centro_custo"),
    ("PIPEFY_0004", "sync.sync_0004_setor"),
    ("PIPEFY_0005", "sync.sync_0005_funcao"),
    ("PIPEFY_0012", "sync.sync_0012_horario"),
    ("PIPEFY_0001", "sync.sync_0001_pessoa"),
    ("PIPEFY_0011", "sync.sync_0011_gestor"),
    ("PIPEFY_0007", "sync.sync_0007_diretor"),
    ("PIPEFY_0008", "sync.sync_0008_titular_odonto"),
    ("PIPEFY_0009", "sync.sync_0009_titular_saude"),
    ("PIPEFY_0006", "sync.sync_0006_dependente_odonto"),
    ("PIPEFY_0010", "sync.sync_0010_dependente_saude"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="não escreve no Pipefy")
    ap.add_argument(
        "--only",
        default=None,
        help="ex: 0001,0002 ou PIPEFY_0001,PIPEFY_0002 (filtra etapas)",
    )
    ap.add_argument("--limit", type=int, default=None, help="limita N registros por tabela (teste)")
    args = ap.parse_args()

    only = None
    if args.only:
        only = set()
        for part in args.only.split(","):
            p = part.strip().upper()
            if p.startswith("PIPEFY_"):
                only.add(p)
            else:
                only.add(f"PIPEFY_{p.zfill(4)}")

    total = {}
    for rm_code, mod_name in ORDER:
        if only and rm_code not in only:
            print(f"SKIP {rm_code}")
            continue
        print(f"\n===== {rm_code} ({mod_name}) =====")
        mod = __import__(mod_name, fromlist=["sync"])
        stats = mod.sync(dry_run=args.dry_run, limit=args.limit)
        total[rm_code] = stats

    print("\n===== RESUMO =====")
    for k, v in total.items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()
