"""Cliente Pipefy GraphQL (conta de serviço via client_credentials)."""
import time

import requests

import config

_TOKEN_CACHE = {"token": None, "ts": 0}


def get_access_token(force: bool = False) -> str:
    """Obtém OAuth token via client_credentials. Cache simples em memória."""
    if _TOKEN_CACHE["token"] and not force:
        return _TOKEN_CACHE["token"]
    resp = requests.post(
        config.PIPEFY_TOKEN_URL,
        headers={"Content-Type": "application/json"},
        json={
            "grant_type": "client_credentials",
            "client_id": config.PIPEFY_CLIENT_ID,
            "client_secret": config.PIPEFY_CLIENT_SECRET,
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    token = data["access_token"]
    _TOKEN_CACHE["token"] = token
    _TOKEN_CACHE["ts"] = time.time()
    return token


def graphql(query: str, token: str | None = None, timeout: int = 60, retries: int = 5) -> dict:
    """Executa query/mutation GraphQL com retry p/ erros transitórios (502/503/504/429)."""
    token = token or get_access_token()
    last_err = None
    for attempt in range(retries):
        try:
            resp = requests.post(
                config.PIPEFY_GRAPHQL_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={"query": query},
                timeout=timeout,
            )
            # 429/5xx são transitórios -> retry
            if resp.status_code in (429, 502, 503, 504):
                last_err = RuntimeError(f"Pipefy HTTP {resp.status_code} (tentativa {attempt+1}/{retries})")
                time.sleep(2 * (attempt + 1))
                continue
            resp.raise_for_status()
            payload = resp.json()
            if "errors" in payload and payload["errors"]:
                # erros de validação (ex: CPF inválido) não adianta retry
                raise RuntimeError(f"Pipefy GraphQL errors: {payload['errors']}")
            return payload.get("data", {})
        except RuntimeError:
            raise
        except Exception as e:  # noqa: BLE001 - rede/timeout
            last_err = e
            time.sleep(2 * (attempt + 1))
    raise last_err if last_err else RuntimeError("Pipefy graphql falhou sem detalhe")


def _esc(value: str) -> str:
    """Escape para string dentro de GraphQL (aspas/barras)."""
    if value is None:
        return ""
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )


def fetch_all_table_records(table_id: str, token: str | None = None, page_size: int = 50):
    """Pagina table_records (via table(id)) e retorna lista de nodes.

    Cada item: {"id":..., "title":..., "status": {"id":..,"name":..},
                "fields": {field_id: value_str}}
    Inclui Ativos e Concluídos (Pipefy retorna ambos nesse endpoint).
    """
    token = token or get_access_token()
    all_nodes = []
    after = None
    while True:
        if after:
            q = (
                f'{{ table(id: "{table_id}") {{ table_records(first: {page_size}, '
                f'after: "{after}") {{ pageInfo {{ hasNextPage endCursor }} '
                f"edges {{ node {{ id title status {{ id name }} "
                f"record_fields {{ field {{ id }} value }} }} }} }} }} }}"
            )
        else:
            q = (
                f'{{ table(id: "{table_id}") {{ table_records(first: {page_size}) '
                f"{{ pageInfo {{ hasNextPage endCursor }} edges {{ node {{ id title "
                f"status {{ id name }} record_fields {{ field {{ id }} value }} }} }} }} }} }}"
            )
        last_err = None
        for attempt in range(3):
            try:
                data = graphql(q, token=token)
                break
            except Exception as e:  # noqa: BLE001 - retry transitório
                last_err = e
                time.sleep(1.5 * (attempt + 1))
        else:
            raise last_err
        conn = data["table"]["table_records"]
        for e in conn["edges"]:
            node = e["node"]
            fields = {}
            for rf in node.get("record_fields") or []:
                fid = (rf.get("field") or {}).get("id")
                if fid:
                    fields[fid] = rf.get("value") or ""
            all_nodes.append(
                {
                    "id": node["id"],
                    "title": node.get("title") or "",
                    "status": node.get("status") or {},
                    "fields": fields,
                }
            )
        pi = conn["pageInfo"]
        if not pi.get("hasNextPage"):
            break
        after = pi["endCursor"]
        time.sleep(0.2)
    return all_nodes


def create_table_record(table_id: str, title: str, fields: dict, token: str | None = None):
    """Cria record. fields: {field_id: valor | [ids p/ connector]}.

    Valores vazios (""/None) são ignorados (Pipefy rejeita vazio p/ email/cpf/date).
    """
    token = token or get_access_token()
    parts = []
    for fid, val in fields.items():
        if val is None:
            continue
        if isinstance(val, (list, tuple)):
            # connector: [ids]
            ids = [f'"{_esc(v)}"' for v in val if str(v).strip()]
            if not ids:
                continue
            parts.append(f'{{field_id: "{fid}", field_value: [{", ".join(ids)}]}}')
        else:
            txt = str(val).strip()
            if txt == "":
                continue
            parts.append(f'{{field_id: "{fid}", field_value: "{_esc(txt)}"}}')
    fields_gql = "\n      ".join(parts)
    mutation = (
        "mutation {\n"
        "  createTableRecord(input: {\n"
        f'    table_id: "{table_id}"\n'
        f'    title: "{_esc(title)}"\n'
        f"    fields_attributes: [\n      {fields_gql}\n    ]\n"
        "  }) { table_record { id } }\n"
        "}"
    )
    data = graphql(mutation, token=token)
    time.sleep(0.5)  # evita 502 por burst em cargas iniciais (409/1558 creates)
    return data["createTableRecord"]["table_record"]["id"]


def set_fields(record_id: str, fields: dict, token: str | None = None):
    """Atualiza N campos com 1 request (aliases m1..mN via setTableRecordFieldValue).

    fields: {field_id: valor | [ids]}. Valores vazios viram "" (limpa campo).
    Connector vazio (lista vazia) é ignorado aqui (Pipefy não aceita limpar assim).
    """
    token = token or get_access_token()
    aliases = []
    idx = 0
    for fid, val in fields.items():
        idx += 1
        if isinstance(val, (list, tuple)):
            ids = [f'"{_esc(v)}"' for v in val if str(v).strip()]
            if not ids:
                continue  # não limpa connector via set vazio
            aliases.append(
                f'm{idx}: setTableRecordFieldValue(input: '
                f'{{table_record_id: "{record_id}", field_id: "{fid}", '
                f'value: [{", ".join(ids)}]}}) {{ table_record {{ id }} }}'
            )
        else:
            txt = "" if val is None else str(val)
            aliases.append(
                f'm{idx}: setTableRecordFieldValue(input: '
                f'{{table_record_id: "{record_id}", field_id: "{fid}", '
                f'value: "{_esc(txt)}"}}) {{ table_record {{ id }} }}'
            )
    if not aliases:
        return
    # Pipefy aceita várias mutations por request; fatiamos de 10 em 10
    for i in range(0, len(aliases), 10):
        chunk = "\n  ".join(aliases[i : i + 10])
        graphql(f"mutation {{ {chunk} }}", token=token)
        time.sleep(0.2)


def update_title_status(record_id: str, title=None, status_id=None, token=None):
    """Atualiza title e/ou status (updateTableRecord)."""
    token = token or get_access_token()
    args = [f'id: "{record_id}"']
    if title is not None:
        args.append(f'title: "{_esc(title)}"')
    if status_id is not None:
        args.append(f'statusId: "{status_id}"')
    mutation = f'mutation {{ updateTableRecord(input: {{ {", ".join(args)} }}) {{ table_record {{ id }} }} }}'
    graphql(mutation, token=token)
    time.sleep(0.2)


def conclude_record(record_id: str, table_id: str, token=None):
    """Marca como Concluído: seta situa_o='Concluído' (se existir) + status.

    Replica a lógica informada:
      mutation { m1: setTableRecordFieldValue(... situa_o='Concluído' ...)
                 m2: updateTableRecord(... statusId=concluído ...) }
    """
    from config import SITUACAO_FIELD, STATUS  # import tardio p/ evitar ciclo

    token = token or get_access_token()
    situa_field = SITUACAO_FIELD.get(table_id)
    concluido = STATUS[table_id]["concluido"]
    if situa_field:
        set_fields(record_id, {situa_field: "Concluído"}, token=token)
    update_title_status(record_id, status_id=concluido, token=token)


def reactivate_record(record_id: str, table_id: str, situa_value: str | None = None, token=None):
    """Volta para Ativo (quando reaparece no RM)."""
    from config import SITUACAO_FIELD, STATUS

    token = token or get_access_token()
    ativo = STATUS[table_id]["ativo"]
    situa_field = SITUACAO_FIELD.get(table_id)
    if situa_field and situa_value is not None:
        set_fields(record_id, {situa_field: situa_value}, token=token)
    update_title_status(record_id, status_id=ativo, token=token)
