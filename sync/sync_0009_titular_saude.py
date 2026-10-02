"""Sincronização RM -> Pipefy: Titular Saúde (PIPEFY_0009 -> 26. Titular Saúde).

Chave: CHAPA. Título: NOME.
RM 0009 não traz plano de saúde (ASS_MEDICA_*, DESC_*, SITUAÇÃO, TIPO via CODTIPO
só parcial): esses campos Pipefy ficam vazios na criação e são ignorados na
comparação para não gerar update infinito.
  - situa_o: default 'Ativo' na criação, ignorado no diff (só conclude/reactivate)
  - tipo_funcionario <- CODTIPO (único com fonte)
  - ass_medica_1, cod_ans_assis_medica, desc_assis_medica: sem fonte -> skip

Uso:
    python sync/sync_0009_titular_saude.py [--dry-run] [--limit N]
"""
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import pipefy_client
import rm_client
import utils

RM_CODE = "PIPEFY_0009"
TABLE_ID = config.TABLES[RM_CODE]["table_id"]  # 307305023
STATUS_ATIVO = config.STATUS[TABLE_ID]["ativo"]
STATUS_CONCLUIDO = config.STATUS[TABLE_ID]["concluido"]

SKIP_COMPARE = {"ass_medica_1", "cod_ans_assis_medica", "desc_assis_medica", "situa_o"}


def rm_key(row: dict) -> str:
    return utils.chapa_key(row.get("CHAPA", ""))


def pipefy_key(rec: dict) -> str:
    return utils.chapa_key(rec["fields"].get("chapa", ""))


def map_rm(row: dict):
    nome = utils.s(row.get("NOME", ""))
    title = nome
    fields = {
        "chapa": utils.s(row.get("CHAPA", "")),
        "nome_social": nome,
        "funcao": utils.s(row.get("FUNCAO", "")),
        "secao": utils.s(row.get("SECAO", "")),
        "cnpj": utils.s(row.get("CNPJ", "")),
        "dataadmissao": utils.rm_date_to_iso(row.get("DATAADMISSAO", "")),
        "cpf": utils.cpf_norm(row.get("CPF", "")),
        "dtnascimento": utils.rm_date_to_iso(row.get("DTNASCIMENTO", "")),
        "cartidentidade": utils.s(row.get("CARTIDENTIDADE", "")),
        "orgemissorident": utils.s(row.get("ORGEMISSORIDENT", "")),
        "ufcartident": utils.s(row.get("UFCARTIDENT", "")),
        "dtemissaoident": utils.rm_date_to_iso(row.get("DTEMISSAOIDENT", "")),
        "sexo": utils.s(row.get("SEXO", "")),
        "estadocivil": utils.s(row.get("ESTADOCIVIL", "")),
        "email": utils.s(row.get("EMAIL", "")),
        "rua": utils.s(row.get("RUA", "")),
        "numero": utils.s(row.get("NUMERO", "")),
        "complemento": utils.s(row.get("COMPLEMENTO", "")),
        "bairro": utils.s(row.get("BAIRRO", "")),
        "cidade": utils.s(row.get("CIDADE", "")),
        "estado": utils.s(row.get("ESTADO", "")),
        "cep": utils.s(row.get("CEP", "")),
        "situa_o": "Ativo",
        "tipo_funcionario": utils.s(row.get("CODTIPO", "")),
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
            print(f"[CREATE] CHAPA={k} NOME={title}")
            if not dry_run:
                pipefy_client.create_table_record(TABLE_ID, title, expected, token=token)
            stats["created"] += 1
            continue
        for rec in recs:
            status_name = (rec.get("status") or {}).get("name", "")
            status_id = (rec.get("status") or {}).get("id", "")
            diff = utils.diff_fields(expected, rec["fields"], skip=SKIP_COMPARE)
            title_diff = utils.s(title) != utils.s(rec.get("title", ""))
            if status_id == STATUS_CONCLUIDO or status_name == "Concluído":
                print(f"[REACTIVATE] CHAPA={k} id={rec['id']}")
                if not dry_run:
                    pipefy_client.reactivate_record(rec["id"], TABLE_ID, situa_value="Ativo", token=token)
                    if diff:
                        pipefy_client.set_fields(rec["id"], diff, token=token)
                    if title_diff:
                        pipefy_client.update_title_status(rec["id"], title=title, token=token)
                stats["reactivated"] += 1
            elif diff or title_diff:
                print(f"[UPDATE] CHAPA={k} id={rec['id']} diff={list(diff.keys())}")
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
                print(f"[CONCLUDE] CHAPA={k} id={rec['id']}")
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
