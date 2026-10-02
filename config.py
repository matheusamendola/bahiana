"""Config central da integração RM -> Pipefy (homologação)."""
import os

# --- RM (Totvs) ---
RM_BASE_URL = os.getenv(
    "RM_BASE_URL",
    "https://www4.bahiana.edu.br/api/framework/v1/consultaSQLServer/RealizaConsulta",
)
RM_USER = os.getenv("RM_USER", "pipefy")
RM_PASS = os.getenv("RM_PASS", "P1p3fy_26@")

# --- Pipefy OAuth (conta de serviço) ---
PIPEFY_CLIENT_ID = os.getenv(
    "PIPEFY_CLIENT_ID", "9lVjvx73er7azre0eThfJdaN33uDv2HZnew-Q_s4GGA"
)
PIPEFY_CLIENT_SECRET = os.getenv(
    "PIPEFY_CLIENT_SECRET", "NUbYY27FV8qWni6WSKU1dWvqk8SMpc5l3sDO11-ST0g"
)
PIPEFY_TOKEN_URL = os.getenv(
    "PIPEFY_TOKEN_URL", "https://app.pipefy.com/oauth/token"
)
PIPEFY_GRAPHQL_URL = os.getenv(
    "PIPEFY_GRAPHQL_URL", "https://api.pipefy.com/graphql"
)

# Tabelas homologação: RM_CODE -> pipefy table_id
TABLES = {
    "PIPEFY_0001": {"table_id": "307296359", "nome": "1. Pessoa Colaboradora"},
    "PIPEFY_0002": {"table_id": "307304972", "nome": "8. Sindicato"},
    "PIPEFY_0003": {"table_id": "307304973", "nome": "2. Centro de Custo"},
    "PIPEFY_0004": {"table_id": "307304979", "nome": "5. Setor"},
    "PIPEFY_0005": {"table_id": "307304984", "nome": "4. Função"},
    "PIPEFY_0006": {"table_id": "307305040", "nome": "24. Dependente - Plano Odonto"},
    "PIPEFY_0007": {"table_id": "307346037", "nome": "37. Diretor (Desligamento)"},
    "PIPEFY_0008": {"table_id": "307305002", "nome": "28. Titular Plano Odontológico"},
    "PIPEFY_0009": {"table_id": "307305023", "nome": "26. Titular Plano de Saúde"},
    "PIPEFY_0010": {"table_id": "307305033", "nome": "23. Dependente - Plano Saude"},
    "PIPEFY_0011": {"table_id": "307304999", "nome": "19. Gestor Solicitante"},
    "PIPEFY_0012": {"table_id": "307343427", "nome": "18. Horário de Trabalho"},
}

# Status "Concluído" por tabela (levantado via GraphQL em 02/10/2026)
# Formato: table_id -> {"ativo": id, "concluido": id}
STATUS = {
    "307296359": {"ativo": "343980461", "concluido": "343980462"},  # Pessoa
    "307304972": {"ativo": "344030238", "concluido": "344030239"},  # Sindicato
    "307304973": {"ativo": "344030242", "concluido": "344030243"},  # Centro
    "307304979": {"ativo": "344030291", "concluido": "344030292"},  # Setor
    "307304984": {"ativo": "344030309", "concluido": "344030310"},  # Funcao
    "307304999": {"ativo": "344030382", "concluido": "344030383"},  # Gestor
    "307305002": {"ativo": "344030399", "concluido": "344030400"},  # Tit Odonto
    "307305023": {"ativo": "344030491", "concluido": "344030492"},  # Tit Saude
    "307305033": {"ativo": "344030549", "concluido": "344030550"},  # Dep Saude
    "307305040": {"ativo": "344030587", "concluido": "344030588"},  # Dep Odonto
    "307343427": {"ativo": "344245507", "concluido": "344245508"},  # Horario
    "307346037": {"ativo": "344260550", "concluido": "344260551"},  # Diretor
}

# Tabelas que possuem campo situa_o (para setar "Concluído"/reativar junto com status)
# pessoa_colaboradora.situa_o, titular odonto/saude .situa_o
SITUACAO_FIELD = {
    "307296359": "situa_o",  # Pessoa Colaboradora
    "307305002": "situa_o",  # Titular Odonto
    "307305023": "situa_o",  # Titular Saude
}
