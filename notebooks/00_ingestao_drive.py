# Databricks notebook source
# MAGIC %md
# MAGIC # 00 — Ingestao: Google Drive → volume
# MAGIC
# MAGIC Copia os arquivos de UM dia de uma subpasta do Drive (`olhovivo-bronze/<subpasta>/dt=<dia>/`)
# MAGIC para o volume (`/Volumes/onibus/bronze/raw/olhovivo/<subpasta>/dt=<dia>/`).
# MAGIC Tambem atualiza a `auditoria.csv`.
# MAGIC
# MAGIC - **Quem acessa o Drive:** uma service account (robo) com acesso de leitor so a pasta
# MAGIC   `olhovivo-bronze`. A chave dela esta no secret `onibus/gdrive_sa`, nunca no codigo.
# MAGIC - **Idempotente:** arquivo que ja esta no volume com o mesmo tamanho e pulado.
# MAGIC   Rodar duas vezes o mesmo dia nao duplica nada.
# MAGIC - **Por que puxar do Drive:** o serverless deste workspace so alcanca PyPI e `*.googleapis.com`;
# MAGIC   a API da SPTrans e bloqueada. A VM coleta, o Databricks busca no Drive.

# COMMAND ----------

# MAGIC %pip install google-auth --quiet

# COMMAND ----------

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from google.auth.transport.requests import Request
from google.oauth2 import service_account

# Parametros. Num job, chegam como parametros da task; aqui, como widgets.
ontem = (datetime.now(ZoneInfo("America/Sao_Paulo")) - timedelta(days=1)).strftime("%Y-%m-%d")
dbutils.widgets.text("dt", ontem)
dbutils.widgets.text("subpasta", "bronze_raw")
DT = dbutils.widgets.get("dt")
SUBPASTA = dbutils.widgets.get("subpasta")

RAIZ_DRIVE = "olhovivo-bronze"
DESTINO_BASE = "/Volumes/onibus/bronze/raw/olhovivo"
API = "https://www.googleapis.com/drive/v3"
print(f"dia={DT} subpasta={SUBPASTA}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Autenticar como o robo
# MAGIC
# MAGIC A chave JSON vira um **token de acesso** temporario (~1 h). Toda chamada a API leva esse
# MAGIC token no cabecalho `Authorization`. Escopo `drive.readonly`: o robo so le.

# COMMAND ----------

chave = json.loads(dbutils.secrets.get("onibus", "gdrive_sa"))
cred = service_account.Credentials.from_service_account_info(
    chave, scopes=["https://www.googleapis.com/auth/drive.readonly"])
cred.refresh(Request())

sess = requests.Session()
sess.headers["Authorization"] = f"Bearer {cred.token}"
print("autenticado como", chave["client_email"])

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Achar a pasta do dia
# MAGIC
# MAGIC O Drive nao tem caminhos como `a/b/c`: cada pasta e um objeto com um `id`, e se acha uma
# MAGIC pasta pelo nome e pelo `id` da pasta-mae. Entao descemos um nivel por vez:
# MAGIC `olhovivo-bronze` → `bronze_raw` → `dt=2026-09-23`.

# COMMAND ----------

PASTA = "application/vnd.google-apps.folder"

def listar(q: str, campos: str = "id,name,size,mimeType") -> list[dict]:
    """Lista tudo que casa com a consulta q, seguindo a paginacao (1000 por pagina)."""
    itens, token = [], None
    while True:
        r = sess.get(f"{API}/files", params={
            "q": q + " and trashed = false", "pageSize": 1000, "pageToken": token,
            "fields": f"nextPageToken, files({campos})"}, timeout=60)
        r.raise_for_status()
        corpo = r.json()
        itens += corpo.get("files", [])
        token = corpo.get("nextPageToken")
        if not token:
            return itens

def achar_pasta(nome: str, pai: str | None = None) -> str:
    q = f"name = '{nome}' and mimeType = '{PASTA}'"
    if pai:
        q += f" and '{pai}' in parents"
    achados = listar(q, "id,name")
    if len(achados) != 1:
        raise RuntimeError(f"esperava 1 pasta '{nome}', achei {len(achados)}")
    return achados[0]["id"]

id_raiz = achar_pasta(RAIZ_DRIVE)
id_pasta = id_raiz
for parte in SUBPASTA.split("/"):          # aceita subpasta aninhada, ex.: kmz/bronze_kmz
    id_pasta = achar_pasta(parte, id_pasta)
id_dia = achar_pasta(f"dt={DT}", id_pasta)

arquivos = [a for a in listar(f"'{id_dia}' in parents") if a["mimeType"] != PASTA]
print(len(arquivos), "arquivos no Drive para", DT)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Copiar para o volume, pulando o que ja existe
# MAGIC
# MAGIC Volumes aparecem como pastas comuns (`/Volumes/...`), entao da para gravar com `open()`.
# MAGIC Varios downloads ao mesmo tempo (threads), porque cada arquivo e pequeno e o tempo
# MAGIC e quase todo espera de rede.

# COMMAND ----------

destino = f"{DESTINO_BASE}/{SUBPASTA}/dt={DT}"
os.makedirs(destino, exist_ok=True)

def copiar(a: dict) -> str:
    caminho = f"{destino}/{a['name']}"
    if os.path.exists(caminho) and os.path.getsize(caminho) == int(a.get("size", -1)):
        return "ja_existia"
    r = sess.get(f"{API}/files/{a['id']}", params={"alt": "media"}, timeout=120)
    r.raise_for_status()
    with open(caminho, "wb") as f:
        f.write(r.content)
    return "copiado"

resultado = {"copiado": 0, "ja_existia": 0, "falhou": 0}
falhas = []
with ThreadPoolExecutor(max_workers=16) as pool:
    for a, fut in [(a, pool.submit(copiar, a)) for a in arquivos]:
        try:
            resultado[fut.result()] += 1
        except Exception as e:  # noqa: BLE001
            resultado["falhou"] += 1
            falhas.append((a["name"], f"{type(e).__name__}: {e}"[:200]))

print(resultado)
for nome, erro in falhas[:10]:
    print("  FALHOU", nome, erro)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Atualizar a auditoria e conferir
# MAGIC
# MAGIC A `auditoria.csv` muda todo dia, entao e sempre copiada de novo (sem pular).
# MAGIC No fim, o notebook **falha** se algum arquivo nao veio — num job, isso deixa o run vermelho.

# COMMAND ----------

aud = [a for a in listar(f"'{id_raiz}' in parents and name = 'auditoria.csv'")]
if len(aud) == 1:
    r = sess.get(f"{API}/files/{aud[0]['id']}", params={"alt": "media"}, timeout=120)
    r.raise_for_status()
    with open(f"{DESTINO_BASE}/auditoria.csv", "wb") as f:
        f.write(r.content)
    print("auditoria.csv atualizada:", len(r.content), "bytes")

no_volume = len([n for n in os.listdir(destino) if not n.endswith(".tmp")])
print(f"Drive: {len(arquivos)} | volume: {no_volume}")
assert resultado["falhou"] == 0, f"{resultado['falhou']} arquivos falharam"
assert no_volume >= len(arquivos), "volume tem menos arquivos que o Drive"
