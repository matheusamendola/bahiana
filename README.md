# Integração RM (Totvs) -> Pipefy (Databases)

Sincroniza 12 consultas SQL do RM para 12 databases do Pipefy (homologação),
com lógica **cria / atualiza se divergir / conclui órfãos**.

## Mapeamento RM -> Pipefy (homologação)

| RM | Pipefy table_id | Database | Chave | Título |
|---|---|---|---|---|
| PIPEFY_0001/0/P | 307296359 | 1. Pessoa Colaboradora | CHAPA | NOME |
| PIPEFY_0002/0/P | 307304972 | 8. Sindicato | NOME | NOME |
| PIPEFY_0003/0/P | 307304973 | 2. Centro de Custo | CENTRO_DE_CUSTO | CENTRO_DE_CUSTO |
| PIPEFY_0004/0/P | 307304979 | 5. Setor | SETOR | SETOR |
| PIPEFY_0005/0/P | 307304984 | 4. Função | FUNCAO | FUNCAO |
| PIPEFY_0006/0/P | 307305040 | 24. Dependente - Odonto | CPF_DEPENDENTE | CPF_DEPENDENTE |
| PIPEFY_0007/0/P | 307346037 | 37. Diretor | MATRICULA | NOME |
| PIPEFY_0008/0/P | 307305002 | 28. Titular Odonto | CHAPA | NOME |
| PIPEFY_0009/0/P | 307305023 | 26. Titular Saúde | CHAPA | NOME |
| PIPEFY_0010/0/P | 307305033 | 23. Dependente - Saúde | CPF_DEPENDENTE | CPF_DEPENDENTE |
| PIPEFY_0011/0/P | 307304999 | 19. Gestor Solicitante | CHAPA | CHEFE01 |
| PIPEFY_0012/0/P | 307343427 | 18. Horário de Trabalho | CODIGO | DESCRICAO |

Exemplo RM: `GET https://www4.bahiana.edu.br/api/framework/v1/consultaSQLServer/RealizaConsulta/PIPEFY_0002/0/P`
com Basic Auth (`pipefy` / senha em `config.py` ou env `RM_USER`/`RM_PASS`).

## Lógica (igual p/ todas)

1. Busca RM + busca **todos** os records do Pipefy (paginação 50/50, inclui Ativo e Concluído).
2. Para cada chave do RM:
   - Não existe no Pipefy -> `createTableRecord`.
   - Existe e status = Concluído -> reativa p/ Ativo (+ restaura `situa_o` quando houver) e atualiza campos divergentes.
   - Existe e Ativo -> compara campo a campo (normalizado); se divergir -> `setTableRecordFieldValue` (batch 10/request) + `updateTableRecord` p/ título se mudou; senão nada.
3. Para cada record Pipefy Ativo cuja chave **não** existe no RM -> **Concluir**:
   ```graphql
   mutation {
     m1: setTableRecordFieldValue(input: {table_record_id: "ID", field_id: "situa_o", value: "Concluído"}) { table_record { id } }
     m2: updateTableRecord(input: {id: "ID", statusId: "<concluido>"}) { table_record { id } }
   }
   ```
   `situa_o` só é setado nas 3 tabelas que têm o campo (Pessoa, Tit Odonto, Tit Saúde).
   Nas demais, só muda o status.

Status Concluído por tabela (`config.STATUS`):

- Pessoa 307296359: Ativo 343980461 / Concluído **343980462**
- Sindicato 307304972: 344030238 / **344030239**
- Centro 307304973: 344030242 / **344030243**
- Setor 307304979: 344030291 / **344030292**
- Função 307304984: 344030309 / **344030310**
- Gestor 307304999: 344030382 / **344030383**
- Tit Odonto 307305002: 344030399 / **344030400**
- Tit Saúde 307305023: 344030491 / **344030492**
- Dep Saúde 307305033: 344030549 / **344030550**
- Dep Odonto 307305040: 344030587 / **344030588**
- Horário 307343427: 344245507 / **344245508**
- Diretor 307346037: 344260550 / **344260551**

## Estrutura

- `config.py` - credenciais (env com fallback), table_ids, statusIds.
- `rm_client.py` - `fetch_rm("PIPEFY_0002")`.
- `pipefy_client.py` - OAuth client_credentials, `graphql()`, paginação, create/set/update/conclude/reactivate.
- `utils.py` - normalização (datas DD/MM/YYYY <-> YYYY-MM-DD, CPF, CHAPA com zeros, COD centro com tolerância).
- `sync/sync_XXXX_*.py` - **1 script por tabela, cada um com toda a lógica** (runnable standalone).
- `sync_all.py` - roda todas na ordem segura (referência -> pessoa/gestor/diretor -> titulares -> dependentes).

## Uso

```bash
pip install -r requirements.txt

# teste (não escreve):
python sync/sync_0002_sindicato.py --dry-run
python sync_all.py --dry-run

# oficial (homologação):
python sync/sync_0001_pessoa.py
python sync_all.py

# só algumas + limite p/ teste:
python sync_all.py --dry-run --only 0002,0003 --limit 5
```

Credenciais via env (recomendado em prod) ou fallback em `config.py`:
`RM_USER`, `RM_PASS`, `PIPEFY_CLIENT_ID`, `PIPEFY_CLIENT_SECRET`.
Ver `.env.example`.

## Peculiaridades mapeadas (02/10/2026)

- **Centro COD é `number` no Pipefy e arredonda** (3.1510401001 -> 3.1510401; vários CODs distintos colapsam p/ mesmo valor). Comparação usa tolerância 1e-6 (`utils.cod_centro_equal`) para não gerar loop. Chave é o **nome**.
- **Função**: RM tem 558 linhas com 2 nomes duplicados (AJUDANTE DE SERVICOS GERAIS 2x, PRESTADOR 3x); Pipefy só tem `fun_o` (557 records). Deduplica por nome.
- **Dependente Saúde**: CPF 09681348583 aparece 2x no RM com titulares diferentes; Pipefy tem 2 records idênticos. Deduplica RM (mantém 1º) e atualiza todos os Pipefy do mesmo CPF.
- **Dependente Odonto/Saúde connector** `titular_homologa_o`: resolvido via CPF_TITULAR -> titular.cpf (fallback CHAPA). `Tit Saúde` estava zerada, então 1ª carga de Dep Saúde fica sem vínculo; reexecute após `sync_0009`.
- **Titular Saúde (0009)**: RM não traz plano (ASS_MEDICA_*, DESC_*) nem SITUAÇÃO; esses campos são ignorados no diff e criados vazios/`Ativo`.
- **Titular Odonto (0008)**: `situa_o` sem fonte -> cria `Ativo`, ignora no diff; `assistmedicadepend` sem fonte -> ignorado.
- **Horário**: `hor_rio_inativo` = inverso de ATIVO (True->False); `tipo_de_hor_rio` sem fonte -> ignorado. Título = DESCRICAO (Pipefy deriva título da descrição).
- **Pessoa**: EMAIL usa fallback EMAILPESSOAL; REGIME ausente em 899/1621 -> envia vazio; datas enviadas como YYYY-MM-DD (Pipefy devolve DD/MM/YYYY).
- **CPF**: Pipefy valida dígito (ex: 00000000000 rejeita). CPFs do RM são válidos; se algum falhar, o erro aparece no log e o record é pulado.
- Paginação Pipefy capa em 50/página mesmo pedindo 100; código pagina com `first: 50`.
