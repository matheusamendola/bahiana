"""Sincronização RM -> Pipefy: Sindicato (PIPEFY_0002 -> HOMOLOGAÇAO 8. Sindicato).

Lógica:
- Se registro existe no RM e no Pipefy: compara; se divergir, atualiza; senão nada.
- Se existe no RM e não no Pipefy: cria.
- Se existe no Pipefy (Ativo) e não no RM: marca como Concluído
  (updateTableRecord statusId=344030239).

Chave: NOME (normalizado UPPER). Pipefy só guarda `sindicato`.
Uso:
    python sync/sync_0002_sindicato.py [--dry-run] [--limit N]
"""
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import pipefy_client
import rm_client
import utils

RM_CODE = "PIPEFY_0002"
TABLE_ID = config.TABLES[RM_CODE]["table_id"]  # 307304972
STATUS_ATIVO = config.STATUS[TABLE_ID]["ativo"]
STATUS_CONCLUIDO = config.STATUS[TABLE_ID]["concluido"]


def rm_key(row: dict) -> str:
    return utils.key_norm(row.get("NOME", ""))


def pipefy_key(rec: dict) -> str:
    return utils.key_norm(rec["fields"].get("sindicato", "") or rec.get("title", ""))


def map_rm(row: dict):
    nome = utils.s(row.get("NOME", ""))
    title = nome
    fields = {"sindicato": nome}
    return title, fields


def sync(dry_run: bool = False, limit: int | None = None):
    token = None if dry_run else pipefy_client.get_access_token()
    rm_rows = rm_client.fetch_rm(RM_CODE)
    if limit:
        rm_rows = rm_rows[:limit]

    rm_map: dict[str, dict] = {}
    for r in rm_rows:
        k = rm_key(r)
        if not k:
            continue
        if k in rm_map:
            print(f"[WARN] RM duplicado ignorado (mantém 1º): {k}")
            continue
        rm_map[k] = r

    # dry-run também lê o Pipefy (só não escreve)
    pipefy_recs = pipefy_client.fetch_all_table_records(TABLE_ID, token=token)
    # agrupa por chave (Pipefy permite títulos duplicados)
    pipefy_map: dict[str, list] = {}
    for rec in pipefy_recs:
        k = pipefy_key(rec)
        if not k:
            continue
        pipefy_map.setdefault(k, []).append(rec)

    stats = {"created": 0, "updated": 0, "concluded": 0, "reactivated": 0, "ok": 0}

    # 1) RM -> Pipefy (cria / atualiza / reativa)
    for k, row in rm_map.items():
        title, expected = map_rm(row)
        recs = pipefy_map.get(k, [])
        if not recs:
            print(f"[CREATE] {k} -> {title}")
            if not dry_run:
                pipefy_client.create_table_record(TABLE_ID, title, expected, token=token)
            stats["created"] += 1
            continue
        for rec in recs:
            status_name = (rec.get("status") or {}).get("name", "")
            status_id = (rec.get("status") or {}).get("id", "")
            diff = utils.diff_fields(expected, rec["fields"])
            # título divergente também atualiza
            title_diff = utils.s(title) != utils.s(rec.get("title", ""))
            if status_id == STATUS_CONCLUIDO or status_name == "Concluído":
                # Reapareceu no RM -> reativa + garante campos
                print(f"[REACTIVATE] {k} id={rec['id']}")
                if not dry_run:
                    pipefy_client.reactivate_record(rec["id"], TABLE_ID, token=token)
                    if diff:
                        pipefy_client.set_fields(rec["id"], diff, token=token)
                    if title_diff:
                        pipefy_client.update_title_status(rec["id"], title=title, token=token)
                stats["reactivated"] += 1
            elif diff or title_diff:
                print(f"[UPDATE] {k} id={rec['id']} diff={list(diff.keys())}{' +title' if title_diff else ''}")
                if not dry_run:
                    if diff:
                        pipefy_client.set_fields(rec["id"], diff, token=token)
                    if title_diff:
                        pipefy_client.update_title_status(rec["id"], title=title, token=token)
                stats["updated"] += 1
            else:
                stats["ok"] += 1

    # 2) Pipefy -> RM (conclui órfãos Ativos)
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
                print(f"[CONCLUDE] {k} id={rec['id']} title={rec.get('title')}")
                if not dry_run:
                    pipefy_client.conclude_record(rec["id"], TABLE_ID, token=token)
                stats["concluded"] += 1

    print(f"DONE {RM_CODE} -> {TABLE_ID} stats={stats} dry_run={dry_run}")
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="não escreve no Pipefy")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    sync(dry_run=args.dry_run, limit=args.limit)


if __name__ == "__main__":
    main()
