"""Sincronização RM -> Pipefy: Setor/Seção (PIPEFY_0004 -> HOMOLOGAÇAO 5. Setor).

Chave: SETOR (UPPER). Campos: setor, cnpj.
Uso:
    python sync/sync_0004_setor.py [--dry-run] [--limit N]
"""
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import pipefy_client
import rm_client
import utils

RM_CODE = "PIPEFY_0004"
TABLE_ID = config.TABLES[RM_CODE]["table_id"]  # 307304979
STATUS_ATIVO = config.STATUS[TABLE_ID]["ativo"]
STATUS_CONCLUIDO = config.STATUS[TABLE_ID]["concluido"]


def rm_key(row: dict) -> str:
    return utils.key_norm(row.get("SETOR", ""))


def pipefy_key(rec: dict) -> str:
    return utils.key_norm(rec["fields"].get("setor", "") or rec.get("title", ""))


def map_rm(row: dict):
    nome = utils.s(row.get("SETOR", ""))
    title = nome
    fields = {"setor": nome, "cnpj": utils.s(row.get("CNPJ", ""))}
    return title, fields


def sync(dry_run: bool = False, limit: int | None = None):
    token = None if dry_run else pipefy_client.get_access_token()
    rm_rows = rm_client.fetch_rm(RM_CODE)
    if limit:
        rm_rows = rm_rows[:limit]
    rm_map = {}
    for r in rm_rows:
        k = rm_key(r)
        if not k:
            continue
        if k in rm_map:
            print(f"[WARN] RM duplicado: {k}")
            continue
        rm_map[k] = r
    pipefy_recs = pipefy_client.fetch_all_table_records(TABLE_ID, token=token)
    pipefy_map: dict[str, list] = {}
    for rec in pipefy_recs:
        k = pipefy_key(rec)
        if not k:
            continue
        pipefy_map.setdefault(k, []).append(rec)
    stats = {"created": 0, "updated": 0, "concluded": 0, "reactivated": 0, "ok": 0}
    for k, row in rm_map.items():
        title, expected = map_rm(row)
        recs = pipefy_map.get(k, [])
        if not recs:
            print(f"[CREATE] {k}")
            if not dry_run:
                pipefy_client.create_table_record(TABLE_ID, title, expected, token=token)
            stats["created"] += 1
            continue
        for rec in recs:
            status_name = (rec.get("status") or {}).get("name", "")
            status_id = (rec.get("status") or {}).get("id", "")
            diff = utils.diff_fields(expected, rec["fields"])
            title_diff = utils.s(title) != utils.s(rec.get("title", ""))
            if status_id == STATUS_CONCLUIDO or status_name == "Concluído":
                print(f"[REACTIVATE] {k} id={rec['id']}")
                if not dry_run:
                    pipefy_client.reactivate_record(rec["id"], TABLE_ID, token=token)
                    if diff:
                        pipefy_client.set_fields(rec["id"], diff, token=token)
                    if title_diff:
                        pipefy_client.update_title_status(rec["id"], title=title, token=token)
                stats["reactivated"] += 1
            elif diff or title_diff:
                print(f"[UPDATE] {k} id={rec['id']} diff={list(diff.keys())}")
                if not dry_run:
                    if diff:
                        pipefy_client.set_fields(rec["id"], diff, token=token)
                    if title_diff:
                        pipefy_client.update_title_status(rec["id"], title=title, token=token)
                stats["updated"] += 1
            else:
                stats["ok"] += 1
    # Com --limit o RM está parcial: não conclui para não gerar falso-positivo
    if limit is not None:
        print("[SKIP conclude] --limit ativo, RM parcial: fase de conclusão pulada")
    else:
        for k, recs in pipefy_map.items():
            if k in rm_map:
                continue
            for rec in recs:
                status_name = (rec.get("status") or {}).get("name", "")
                status_id = (rec.get("status") or {}).get("id", "")
                if status_id == STATUS_CONCLUIDO or status_name == "Concluído":
                    continue
                print(f"[CONCLUDE] {k} id={rec['id']}")
                if not dry_run:
                    pipefy_client.conclude_record(rec["id"], TABLE_ID, token=token)
                stats["concluded"] += 1
    print(f"DONE {RM_CODE} -> {TABLE_ID} stats={stats} dry_run={dry_run}")
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    sync(dry_run=args.dry_run, limit=args.limit)


if __name__ == "__main__":
    main()
