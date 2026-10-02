"""Cliente RM (Totvs Framework)."""
import requests
from requests.auth import HTTPBasicAuth

import config


def fetch_rm(rm_code: str, timeout: int = 60):
    """Busca todos os registros de um endpoint PIPEFY_XXXX/0/P.

    Ex: fetch_rm("PIPEFY_0002") -> GET {RM_BASE}/PIPEFY_0002/0/P
    Retorna lista de dicts (JSON da consulta).
    """
    url = f"{config.RM_BASE_URL.rstrip('/')}/{rm_code}/0/P"
    resp = requests.get(
        url,
        auth=HTTPBasicAuth(config.RM_USER, config.RM_PASS),
        timeout=timeout,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
    )
    resp.raise_for_status()
    data = resp.json()
    # API retorna lista; garante lista mesmo se vier dict único
    if isinstance(data, dict):
        return [data]
    return data or []
