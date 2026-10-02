"""Sincronização RM -> Pipefy: Horário de Trabalho (PIPEFY_0012 -> 18. Horário).

Chave: CODIGO (c_digo_do_hor_rio). Título: DESCRICAO (Pipefy deriva título da
descrição; mantém title=DESCRICAO e atualiza se mudar).

Mapeamento:
  CODIGO->c_digo_do_hor_rio,
  DESCRICAO->hor_rio_de_trabalho,
  DATA_BASE (DD/MM/YYYY)->data_base (YYYY-MM-DD p/ envio),
  ATIVO True/False -> hor_rio_inativo (invertido: ATIVO True => 'False'),
  CONSIDERAREDUCAOJORNADANOTURNA->considera_redu_o_da_jornada_noturna,
  PAGA_ADICIONAL_NOTURNO->paga_adicional_noturno,
  TIPO_JORNADA_ESOCIAL->ch,
  CONSIDERA_DTFINAL_JOR_REF->considerar_a_data_final_da_jornada_como_data_refer_ncia
  tipo_de_hor_rio: sem fonte no RM -> ignorado.

Uso:
    python sync/sync_0012_horario.py [--dry-run] [--limit N]
"""
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import pipefy_client
import rm_client
import utils

RM_CODE = "PIPEFY_0012"
TABLE_ID = config.TABLES[RM_CODE]["table_id"]  # 307343427
STATUS_ATIVO = config.STATUS[TABLE_ID]["ativo"]
STATUS_CONCLUIDO = config.STATUS[TABLE_ID]["concluido"]


def rm_key(row: dict) -> str:
    return utils.s(row.get("CODIGO", ""))


def pipefy_key(rec: dict) -> str:
    return utils.s(rec["fields"].get("c_digo_do_hor_rio", ""))


def map_rm(row: dict):
    codigo = utils.s(row.get("CODIGO", ""))
    descr = utils.s(row.get("DESCRICAO", ""))
    title = descr or codigo
    ativo = utils.bool_str(row.get("ATIVO", ""))
    inativo = "False" if ativo == "True" else "True" if ativo == "False" else ativo
    fields = {
        "c_digo_do_hor_rio": codigo,
        "hor_rio_de_trabalho": descr,
        "data_base": utils.rm_date_to_iso(row.get("DATA_BASE", "")),
        # tipo_de_hor_rio sem fonte -> não envia
        "hor_rio_inativo": inativo,
        "considera_redu_o_da_jornada_noturna": utils.bool_str(
            row.get("CONSIDERAREDUCAOJORNADANOTURNA", "")
        ),
        "paga_adicional_noturno": utils.bool_str(row.get("PAGA_ADICIONAL_NOTURNO", "")),
        "ch": utils.s(row.get("TIPO_JORNADA_ESOCIAL", "")),
        "considerar_a_data_final_da_jornada_como_data_refer_ncia": utils.bool_str(
            row.get("CONSIDERA_DTFINAL_JOR_REF", "")
        ),
    }
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
            print(f"[WARN] duplicado RM: {k}")
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
            print(f"[CREATE] COD={k}")
            if not dry_run:
                pipefy_client.create_table_record(TABLE_ID, title, expected, token=token)
            stats["created"] += 1
            continue
        for rec in recs:
            status_name = (rec.get("status") or {}).get("name", "")
            status_id = (rec.get("status") or {}).get("id", "")
            # ignora tipo_de_hor_rio (sem fonte)
            diff = utils.diff_fields(expected, rec["fields"], skip={"tipo_de_hor_rio"})
            title_diff = utils.s(title) != utils.s(rec.get("title", ""))
            if status_id == STATUS_CONCLUIDO or status_name == "Concluído":
                print(f"[REACTIVATE] COD={k} id={rec['id']}")
                if not dry_run:
                    pipefy_client.reactivate_record(rec["id"], TABLE_ID, token=token)
                    if diff:
                        pipefy_client.set_fields(rec["id"], diff, token=token)
                    if title_diff:
                        pipefy_client.update_title_status(rec["id"], title=title, token=token)
                stats["reactivated"] += 1
            elif diff or title_diff:
                print(f"[UPDATE] COD={k} id={rec['id']} diff={list(diff.keys())}")
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
                print(f"[CONCLUDE] COD={k} id={rec['id']}")
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
