"""Sincronização RM -> Pipefy: Pessoa Colaboradora (PIPEFY_0001 -> HOMOLOGACAO 1).

Chave: CHAPA (matr_cula, preserva zeros: '0033'). Título: NOME.
Conclusão usa statusId 343980462 + seta situa_o='Concluído' (conforme exemplo
do usuário: m1 setTableRecordFieldValue + m2 updateTableRecord).
Reativação volta p/ Ativo e restaura situa_o do RM (SITUACAO).

Mapeamento RM -> Pipefy:
  NOME->pessoa_colaboradora, CHAPA->matr_cula, FUNCAO->fun_o, SECAO->setor,
  SINDICATO->sindicato_1, GRAUINSTRUCAO->grau_de_instru_o,
  DATAADMISSAO->data_de_admiss_o (date), EMAIL (ou EMAILPESSOAL)->email,
  CNPJ->cnpj, JORNADAMENSAL->ch_contratual, SITUACAO->situa_o,
  COD_TIPO->cod_tipo, REGIME->regime, DESCRICAO_HORARIO->drecri_o_hor_rio,
  GRUPOPCCR->grupopccr, AREAUNIFICADA->areaunificada,
  GERENCIARELACIONADA->gerencia_relacionada, COORDENAÇÃO->coordena_o

Uso:
    python sync/sync_0001_pessoa.py [--dry-run] [--limit N]
"""
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import pipefy_client
import rm_client
import utils

RM_CODE = "PIPEFY_0001"
TABLE_ID = config.TABLES[RM_CODE]["table_id"]  # 307296359
STATUS_ATIVO = config.STATUS[TABLE_ID]["ativo"]  # 343980461
STATUS_CONCLUIDO = config.STATUS[TABLE_ID]["concluido"]  # 343980462


def rm_key(row: dict) -> str:
    return utils.chapa_key(row.get("CHAPA", ""))


def pipefy_key(rec: dict) -> str:
    return utils.chapa_key(rec["fields"].get("matr_cula", ""))


def map_rm(row: dict):
    nome = utils.s(row.get("NOME", ""))
    email = utils.s(row.get("EMAIL", "")) or utils.s(row.get("EMAILPESSOAL", ""))
    # data_de_admiss_o é date no Pipefy: envia YYYY-MM-DD
    data_adm_iso = utils.rm_date_to_iso(row.get("DATAADMISSAO", ""))
    title = nome
    fields = {
        "pessoa_colaboradora": nome,
        "matr_cula": utils.s(row.get("CHAPA", "")),
        "fun_o": utils.s(row.get("FUNCAO", "")),
        "setor": utils.s(row.get("SECAO", "")),
        "sindicato_1": utils.s(row.get("SINDICATO", "")),
        "grau_de_instru_o": utils.s(row.get("GRAUINSTRUCAO", "")),
        "data_de_admiss_o": data_adm_iso,
        "email": email,
        "cnpj": utils.s(row.get("CNPJ", "")),
        "ch_contratual": utils.s(row.get("JORNADAMENSAL", "")),
        "situa_o": utils.s(row.get("SITUACAO", "")),
        "cod_tipo": utils.s(row.get("COD_TIPO", "")),
        "regime": utils.s(row.get("REGIME", "")),
        "drecri_o_hor_rio": utils.s(row.get("DESCRICAO_HORARIO", "")),
        "grupopccr": utils.s(row.get("GRUPOPCCR", "")),
        "areaunificada": utils.s(row.get("AREAUNIFICADA", "")),
        "gerencia_relacionada": utils.s(row.get("GERENCIARELACIONADA", "")),
        "coordena_o": utils.s(row.get("COORDENAÇÃO", "")),
    }
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
            print(f"[WARN] CHAPA duplicada no RM: {k}")
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
            # diff ignora campos vazios no RM? Não: se RM vazio e Pipefy tem valor,
            # consideramos diff apenas se RM fonte existe. Aqui todos os campos têm
            # fonte, exceto quando ausentes (ex: REGIME). Se RM não tem a chave,
            # map_rm já colocou "". Para não apagar dados válidos do Pipefy quando
            # RM omite (ex: REGIME ausente), ignoramos diff quando expected=="" e
            # current!=""? Decisão: só atualiza se expected != "" ou current == ""?
            # Simplificação: compara tudo; se RM omite REGIME, vai limpar no Pipefy.
            # Isso é o comportamento desejado (espelho do RM).
            diff = utils.diff_fields(expected, rec["fields"])
            title_diff = utils.s(title) != utils.s(rec.get("title", ""))
            is_done = status_id == STATUS_CONCLUIDO or status_name == "Concluído"
            if is_done:
                print(f"[REACTIVATE] CHAPA={k} id={rec['id']}")
                if not dry_run:
                    pipefy_client.reactivate_record(
                        rec["id"], TABLE_ID, situa_value=expected.get("situa_o", "Ativo"), token=token
                    )
                    if diff:
                        # remove situa_o do diff pois já foi setado na reativação
                        diff.pop("situa_o", None)
                        if diff:
                            pipefy_client.set_fields(rec["id"], diff, token=token)
                    if title_diff:
                        pipefy_client.update_title_status(rec["id"], title=title, token=token)
                stats["reactivated"] += 1
            elif diff or title_diff:
                print(f"[UPDATE] CHAPA={k} id={rec['id']} diff={list(diff.keys())}{' +title' if title_diff else ''}")
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
                print(f"[CONCLUDE] CHAPA={k} id={rec['id']} title={rec.get('title')}")
                if not dry_run:
                    # Replica exemplo do usuário: seta situa_o + status
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
