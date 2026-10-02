"""Sincronização RM -> Pipefy: Dependente Saúde (PIPEFY_0010 -> 23. Dep Saúde).

Chave: CPF_DEPENDENTE. Título = CPF.
RM 0010 tem duplicata real: CPF 09681348583 aparece 2x com titulares diferentes
(mãe e pai). Pipefy permite títulos duplicados e hoje tem 2 records idênticos.
Estratégia: deduplica RM por CPF (mantém 1º + WARN) e, se Pipefy tiver N records
p/ mesmo CPF existente no RM, atualiza todos (não conclui nenhum).

Connector titular_homologa_o -> Titular Saúde HOMOLOG (307305023).
Como Tit Saúde ainda está vazia (0 records), na 1ª carga connector ficará vazio;
após sync_0009, reexecute este para vincular.

Campos sem fonte (skip): data_da_uni_o, nome_completo_da_m_e, titular.
NUMEROCARTAOSUS pode estar ausente no RM -> envia vazio (ignora na criação se vazio).

Uso:
    python sync/sync_0010_dependente_saude.py [--dry-run] [--limit N]
"""
import argparse
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import pipefy_client
import rm_client
import utils

RM_CODE = "PIPEFY_0010"
TABLE_ID = config.TABLES[RM_CODE]["table_id"]  # 307305033
TIT_TABLE_ID = config.TABLES["PIPEFY_0009"]["table_id"]  # 307305023
STATUS_ATIVO = config.STATUS[TABLE_ID]["ativo"]
STATUS_CONCLUIDO = config.STATUS[TABLE_ID]["concluido"]

SKIP_COMPARE = {"data_da_uni_o", "nome_completo_da_m_e", "titular", "titular_homologa_o"}


def rm_key(row: dict) -> str:
    return utils.cpf_norm(row.get("CPF_DEPENDENTE", ""))


def pipefy_key(rec: dict) -> str:
    return utils.cpf_norm(rec["fields"].get("cpf", "") or rec.get("title", ""))


def load_titular_maps(token):
    recs = pipefy_client.fetch_all_table_records(TIT_TABLE_ID, token=token)
    por_cpf, por_chapa = {}, {}
    for r in recs:
        cpf = utils.cpf_norm(r["fields"].get("cpf", ""))
        chapa = utils.chapa_key(r["fields"].get("chapa", ""))
        info = {"id": r["id"], "title": r.get("title", "")}
        if cpf and cpf not in por_cpf:
            por_cpf[cpf] = info
        if chapa and chapa not in por_chapa:
            por_chapa[chapa] = info
    return por_cpf, por_chapa


def expected_connector_id(row: dict, por_cpf: dict, por_chapa: dict):
    cpf_tit = utils.cpf_norm(row.get("CPF_TITULAR", ""))
    if cpf_tit and cpf_tit in por_cpf:
        return por_cpf[cpf_tit]["id"]
    ch_tit = utils.chapa_key(row.get("CHAPA_TITULAR", ""))
    if ch_tit and ch_tit in por_chapa:
        return por_chapa[ch_tit]["id"]
    return None


def expected_connector_title(row: dict, por_cpf: dict, por_chapa: dict):
    cpf_tit = utils.cpf_norm(row.get("CPF_TITULAR", ""))
    if cpf_tit and cpf_tit in por_cpf:
        return por_cpf[cpf_tit]["title"]
    ch_tit = utils.chapa_key(row.get("CHAPA_TITULAR", ""))
    if ch_tit and ch_tit in por_chapa:
        return por_chapa[ch_tit]["title"]
    return ""


def connector_current_titles(rec: dict) -> list:
    raw = rec["fields"].get("titular_homologa_o", "") or ""
    try:
        val = json.loads(raw) if raw.strip().startswith("[") else []
        return val if isinstance(val, list) else []
    except Exception:
        return []


def map_rm(row: dict):
    cpf_dep = utils.cpf_norm(row.get("CPF_DEPENDENTE", ""))
    title = cpf_dep
    fields = {
        "cpf": cpf_dep,
        "nome_completo_do_dependente": utils.s(row.get("NOME_COMPLETO_DEPENDENTE", "")),
        "data_de_nascimento": utils.rm_date_to_iso(row.get("DATA_DE_NASCIMENTO", "")),
        "parentesco": utils.s(row.get("PARENTESCO", "")),
        "estado_civil_1": utils.s(row.get("ESTADO_CIVIL", "")),
        "sexo": utils.s(row.get("SEXO", "")),
        "n_carteira_nacional_de_sa_de_sus": utils.s(row.get("NUMEROCARTAOSUS", "")),
        "cpf_titular": utils.cpf_norm(row.get("CPF_TITULAR", "")),
    }
    return title, fields


def sync(dry_run: bool = False, limit: int | None = None):
    token = None if dry_run else pipefy_client.get_access_token()
    rm_rows = rm_client.fetch_rm(RM_CODE)
    if limit:
        rm_rows = rm_rows[:limit]

    por_cpf, por_chapa = load_titular_maps(token)

    rm_map: dict[str, dict] = {}
    for r in rm_rows:
        k = rm_key(r)
        if not k:
            continue
        if k in rm_map:
            print(f"[WARN] CPF duplicado no RM (mantém 1º): {k} titular={r.get('CPF_TITULAR')}")
            continue
        rm_map[k] = r

    pipefy_recs = pipefy_client.fetch_all_table_records(TABLE_ID, token=token)
    pipefy_map: dict[str, list] = {}
    for rec in pipefy_recs:
        k = pipefy_key(rec)
        if not k:
            continue
        pipefy_map.setdefault(k, []).append(rec)

    stats = {"created": 0, "updated": 0, "concluded": 0, "reactivated": 0, "ok": 0, "no_titular": 0}

    for k, row in rm_map.items():
        title, expected = map_rm(row)
        conn_id = expected_connector_id(row, por_cpf, por_chapa)
        conn_title = expected_connector_title(row, por_cpf, por_chapa)
        if conn_id:
            expected["titular_homologa_o"] = [conn_id]
        else:
            stats["no_titular"] += 1
            # Não é erro na 1ª carga (Tit Saúde vazia); só avisa em debug
            # print(f"[WARN] titular saúde não encontrado p/ dep {k}")

        recs = pipefy_map.get(k, [])
        if not recs:
            print(f"[CREATE] CPF_DEP={k}")
            if not dry_run:
                pipefy_client.create_table_record(TABLE_ID, title, expected, token=token)
            stats["created"] += 1
            continue
        for rec in recs:
            status_name = (rec.get("status") or {}).get("name", "")
            status_id = (rec.get("status") or {}).get("id", "")
            diff = utils.diff_fields(expected, rec["fields"], skip=SKIP_COMPARE)
            conn_diff = False
            if conn_id:
                cur_titles = connector_current_titles(rec)
                if conn_title and conn_title not in cur_titles:
                    conn_diff = True
            title_diff = utils.s(title) != utils.s(rec.get("title", ""))
            is_done = status_id == STATUS_CONCLUIDO or status_name == "Concluído"
            if is_done:
                print(f"[REACTIVATE] CPF_DEP={k} id={rec['id']}")
                if not dry_run:
                    pipefy_client.reactivate_record(rec["id"], TABLE_ID, token=token)
                    if diff:
                        pipefy_client.set_fields(rec["id"], diff, token=token)
                    if conn_diff:
                        pipefy_client.set_fields(rec["id"], {"titular_homologa_o": [conn_id]}, token=token)
                    if title_diff:
                        pipefy_client.update_title_status(rec["id"], title=title, token=token)
                stats["reactivated"] += 1
            elif diff or conn_diff or title_diff:
                print(f"[UPDATE] CPF_DEP={k} id={rec['id']} diff={list(diff.keys())}{' +connector' if conn_diff else ''}")
                if not dry_run:
                    if diff:
                        pipefy_client.set_fields(rec["id"], diff, token=token)
                    if conn_diff:
                        pipefy_client.set_fields(rec["id"], {"titular_homologa_o": [conn_id]}, token=token)
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
                print(f"[CONCLUDE] CPF_DEP={k} id={rec['id']}")
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
