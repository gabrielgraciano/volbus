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

import csv
import io
import json
import os
import time
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

def pedir(url: str, params: dict | None = None, tentativas: int = 5) -> requests.Response:
    """GET com nova tentativa e espera crescente (2, 4, 8, 16 s) em erro passageiro:
    429 (limite de requisicoes) e 5xx (erro do servidor do Google)."""
    for t in range(1, tentativas + 1):
        r = sess.get(url, params=params, timeout=120)
        if r.status_code == 429 or r.status_code >= 500:
            if t < tentativas:
                time.sleep(2 ** t)
                continue
        r.raise_for_status()
        return r

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
        corpo = pedir(f"{API}/files", {
            "q": q + " and trashed = false", "pageSize": 1000, "pageToken": token,
            "fields": f"nextPageToken, files({campos})"}).json()
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

# Fonte independente do que DEVERIA existir: a auditoria da VM lista o nome de cada
# arquivo gravado com sucesso. Licao de 03/10: a busca do Drive e eventualmente
# consistente — logo depois de um upload grande ela devolve so parte dos arquivos
# (509, depois 1.392, de 1.439 reais). Conferir contra a propria listagem nao pega isso.
aud = listar(f"'{id_raiz}' in parents and name = 'auditoria.csv'", "id,name")
conteudo_aud = pedir(f"{API}/files/{aud[0]['id']}", {"alt": "media"}).content
with open(f"{DESTINO_BASE}/auditoria.csv", "wb") as f:
    f.write(conteudo_aud)

# A auditoria so descreve as posicoes do Olho Vivo. v1 (ate 21/09) gravava .ndjson.gz em
# bronze_posicao; v2 grava .json.gz em bronze_raw. No dia 21/09 aparecem os dois.
EXTENSAO = {"bronze_raw": ".json.gz", "bronze_posicao": ".ndjson.gz"}.get(SUBPASTA)
esperados = set()
if EXTENSAO:
    for linha in csv.DictReader(io.StringIO(conteudo_aud.decode("utf-8"))):
        nome = linha["arquivo"]
        if (linha["status"] == "ok" and nome.endswith(EXTENSAO)
                and not (EXTENSAO == ".json.gz" and nome.endswith(".ndjson.gz"))):
            dia_sp = (datetime.fromisoformat(linha["coletado_em"])
                      .astimezone(ZoneInfo("America/Sao_Paulo")).strftime("%Y-%m-%d"))
            if dia_sp == DT:
                esperados.add(nome)
print(len(esperados), "arquivos esperados pela auditoria")

# Lista ate a busca do Drive mostrar tudo que a auditoria espera (ate 6 vezes, 30 s entre elas).
for rodada in range(1, 7):
    arquivos = [a for a in listar(f"'{id_dia}' in parents") if a["mimeType"] != PASTA]
    faltam = esperados - {a["name"] for a in arquivos}
    print(f"rodada {rodada}: {len(arquivos)} listados, faltam {len(faltam)}")
    if not faltam:
        break
    time.sleep(30)

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
    conteudo = pedir(f"{API}/files/{a['id']}", {"alt": "media"}).content
    with open(caminho, "wb") as f:
        f.write(conteudo)
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
# MAGIC ## 4. Conferir contra a auditoria
# MAGIC
# MAGIC O teste que importa: **todo arquivo que a auditoria diz que existe esta no volume?**
# MAGIC Se nao, o notebook falha — num job, o run fica vermelho e rodar de novo busca o que faltou.

# COMMAND ----------

no_volume = set(os.listdir(destino))
ausentes = esperados - no_volume
print(f"esperados: {len(esperados)} | listados no Drive: {len(arquivos)} | no volume: {len(no_volume)}")
print("ausentes:", sorted(ausentes)[:5], "..." if len(ausentes) > 5 else "")
assert resultado["falhou"] == 0, f"{resultado['falhou']} downloads falharam"
assert not ausentes, f"{len(ausentes)} arquivos da auditoria nao estao no volume"
