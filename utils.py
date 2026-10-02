"""Helpers de normalização/comparação."""
from datetime import datetime


def s(value):
    """Normaliza texto: None -> '', strip, mantém original (case preservado)."""
    if value is None:
        return ""
    return str(value).strip()


def key_norm(value):
    """Chave de comparação: strip + UPPER + colapsa espaços."""
    return " ".join(s(value).upper().split())


def chapa_key(value):
    """CHAPA/matrícula: preserva zeros à esquerda, só strip.

    Pipefy preserva '0033', '0358', então comparação é string exata após strip.
    """
    return s(value)


def cpf_norm(value):
    """Só dígitos, preservando zeros à esquerda."""
    digits = "".join(ch for ch in s(value) if ch.isdigit())
    return digits


def cnpj_norm(value):
    return s(value)


def rm_date_to_iso(date_br: str) -> str:
    """DD/MM/YYYY -> YYYY-MM-DD (para envio ao Pipefy). Retorna '' se vazio/inválido."""
    t = s(date_br)
    if not t:
        return ""
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.strptime(t, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def any_date_to_iso(value: str) -> str:
    """Normaliza data vinda do RM (DD/MM/YYYY) ou do Pipefy (DD/MM/YYYY) para ISO."""
    t = s(value)
    if not t:
        return ""
    # Pipefy devolve DD/MM/YYYY; RM também. Reusa rm_date_to_iso.
    iso = rm_date_to_iso(t)
    if iso:
        return iso
    return t  # fallback: compara literal


def bool_str(value) -> str:
    """Normaliza 'True'/'False' (RM e Pipefy usam short_text)."""
    t = s(value)
    low = t.lower()
    if low in ("true", "1", "sim", "s", "yes", "y", "verdadeiro"):
        return "True"
    if low in ("false", "0", "não", "nao", "n", "no", "falso"):
        return "False"
    return t


def cod_centro_equal(rm_cod: str, pipefy_cod: str, tol: float = 1e-6) -> bool:
    """Compara COD de centro de custo com tolerância.

    Pipefy usa campo number e arredonda/trunca (ex: 3.1510401001 -> 3.1510401),
    então comparação string exata sempre daria diff e geraria loop infinito.
    Compara como float com tolerância.
    """
    a, b = s(rm_cod).replace(",", "."), s(pipefy_cod).replace(",", ".")
    if not a and not b:
        return True
    if not a or not b:
        return False
    if a == b:
        return True
    try:
        return abs(float(a) - float(b)) <= tol
    except ValueError:
        return key_norm(a) == key_norm(b)


def diff_fields(expected: dict, current: dict, skip: set | None = None) -> dict:
    """Retorna {field_id: novo_valor} para campos divergentes.

    expected/current: {field_id: valor_str}. Comparação após strip.
    skip: field_ids ignorados (sem fonte no RM).
    Tratamento especial:
      - 'cod' (centro) usa cod_centro_equal
      - datas: compara via any_date_to_iso
    """
    skip = skip or set()
    out = {}
    for fid, exp_val in expected.items():
        if fid in skip:
            continue
        cur_val = current.get(fid, "")
        if fid == "cod":
            if not cod_centro_equal(exp_val, cur_val):
                out[fid] = exp_val
            continue
        # datas: compara ISO
        if fid in (
            "data_de_admiss_o",
            "data_base",
            "data_de_nascimento",
            "dataadmissao",
            "dtnascimento",
            "dtemissaoident",
            "data_da_uni_o",
        ):
            if any_date_to_iso(exp_val) != any_date_to_iso(cur_val):
                out[fid] = exp_val
            continue
        if s(exp_val) != s(cur_val):
            out[fid] = exp_val
    return out
