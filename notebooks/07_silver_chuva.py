# Databricks notebook source
# MAGIC %md
# MAGIC # 07 — Chuva: bronze.chuva_sibh, silver.postos e silver.chuva_10min
# MAGIC
# MAGIC Fonte, inventario e verificacao dos dados: **`docs/chuva_sibh.md`** (repositorio). Resumo:
# MAGIC
# MAGIC - **SIBH (DAEE/SP Aguas)**, telemetria, 141 postos do municipio, 01/08 → 25/10/2026, CSVs exportados a mao
# MAGIC   em blocos de 10 postos (o site bloqueia automacao). Coordenadas: `stations.json` (DevTools do SIBH).
# MAGIC - `Data` esta em **UTC** (prova: arquivos salvos as 18:04 de Brasilia terminam em 21:00). `Valor` = mm de chuva
# MAGIC   **desde a leitura anterior** (incremento).
# MAGIC - Tres redes com comportamentos diferentes:
# MAGIC
# MAGIC | Rede | Operador | Postos | Como reporta |
# MAGIC |---|---|---|---|
# MAGIC | `daee` | SAISP, SP Aguas, Sabesp, ANA | 83 | grade fixa de 10 min (um posto a 5 min), com zeros explicitos. Falta de linha = dado faltante |
# MAGIC | `cemaden` | CEMADEN (IDs `3550308xx`) | 56 | **por evento**: seco → 1 leitura/h; chovendo → a cada ~10 min. Leitura espacada cobre o intervalo inteiro |
# MAGIC | `inmet` | INMET (`A701`, `A771`) | 2 | horaria |
# MAGIC
# MAGIC **Principio: silver marca, nao apaga.** Nenhuma regra de qualidade remove dado; cada uma vira uma flag ou um
# MAGIC status, para testar depois a sensibilidade dos resultados ao criterio.
# MAGIC
# MAGIC **Saidas:**
# MAGIC 1. `bronze.chuva_sibh` — as linhas dos CSVs como vieram (+ arquivo de origem).
# MAGIC 2. `silver.chuva_10min` — grade comum de 10 min em UTC, por posto (ver secao 3).
# MAGIC 3. `silver.postos` — 1 linha por posto: coordenadas, rede, qualidade e status.

# COMMAND ----------

import json
import math

import numpy as np
import pandas as pd
from pyspark.sql import functions as F, types as T

spark.conf.set("spark.sql.session.timeZone", "UTC")

PASTA = "/Volumes/onibus/bronze/raw/chuva/sibh/download=2026-10-25"
BRONZE = "onibus.bronze.chuva_sibh"
CHUVA = "onibus.silver.chuva_10min"
POSTOS = "onibus.silver.postos"

INICIO = pd.Timestamp("2026-08-01 03:00")   # 01/08 00:00 de SP, em UTC
COBERTURA_MAX_MIN = 60     # uma leitura cobre no maximo 60 min para tras; mais que isso, o antes vira faltante
PICO_MM_10MIN = 30.0       # acima disso em 10 min (= 180 mm/h): fisicamente implausivel, marcar
K_VIZINHOS = 5             # QC espacial: total do posto contra a mediana dos 5 vizinhos mais proximos
RAZAO_MIN, RAZAO_MAX = 0.4, 2.0
COMPLETUDE_MIN = 0.90
INICIO_ONIBUS = "2026-08-25"   # a coleta de onibus comeca aqui: a completude que importa e daqui em diante

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Bronze: os CSVs como vieram
# MAGIC
# MAGIC O `manifesto.csv` (gerado ao baixar) lista cada arquivo, o bloco, quantas linhas e quais postos tem.
# MAGIC O arquivo marcado `descartar` (repeticao parcial de um bloco) fica no volume mas nao entra na tabela.
# MAGIC Checagem: linhas na tabela = soma das linhas do manifesto.

# COMMAND ----------

manifesto = pd.read_csv(f"{PASTA}/manifesto.csv", dtype=str)
usar = manifesto[~manifesto.bloco.str.startswith("descartar")]
print(f"{len(usar)} arquivos (de {len(manifesto)} no manifesto); {usar.linhas.astype(int).sum():,} linhas esperadas")

schema_csv = T.StructType([
    T.StructField("Prefixo", T.StringType()), T.StructField("Nome", T.StringType()),
    T.StructField("TipoPosto", T.IntegerType()), T.StructField("Data", T.StringType()),
    T.StructField("Valor", T.DoubleType()), T.StructField("Valor2", T.StringType()),
])
bronze = (spark.read.option("header", True).schema(schema_csv)
          .csv([f"{PASTA}/{a}" for a in usar.arquivo])
          .withColumn("arquivo", F.regexp_extract(F.col("_metadata.file_path"), r"[^/]+$", 0))
          .withColumn("instante_utc", F.to_timestamp("Data", "yyyy/MM/dd HH:mm"))
          .select(F.col("Prefixo").alias("prefixo"), F.col("Nome").alias("nome"), "instante_utc",
                  F.col("Valor").alias("mm"), "arquivo", F.col("Data").alias("data_original")))
bronze.write.mode("overwrite").option("overwriteSchema", True).saveAsTable(BRONZE)

n = spark.table(BRONZE).count()
assert n == usar.linhas.astype(int).sum(), f"bronze tem {n} linhas, manifesto diz {usar.linhas.astype(int).sum()}"
assert spark.table(BRONZE).filter("instante_utc IS NULL OR mm IS NULL").count() == 0, "data ou valor que nao converteu"
assert spark.table(BRONZE).groupBy("prefixo", "instante_utc").count().filter("count > 1").count() == 0, "duplicata"
print(f"ok: bronze = manifesto ({n:,} linhas), sem duplicata (prefixo, instante)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Postos: coordenadas e rede
# MAGIC
# MAGIC `stations.json` traz os ~3.700 postos do estado. Ficam os 141 que temos; os acentos do JSON vieram
# MAGIC corrompidos, entao o nome sai dos CSVs. Rede pelo formato do prefixo (`3550308xx[AB]` = CEMADEN; `A\d+` = INMET).

# COMMAND ----------

with open(f"{PASTA}/stations.json", encoding="utf-8") as fh:
    est = pd.DataFrame(json.load(fh))
nomes = (spark.table(BRONZE).groupBy("prefixo").agg(F.first("nome").alias("nome")).toPandas())
postos = nomes.merge(est.rename(columns={"prefix": "prefixo"}), on="prefixo", how="left")
assert postos.latitude.notna().all(), f"postos sem coordenada: {postos[postos.latitude.isna()].prefixo.tolist()}"

postos = pd.DataFrame({
    "prefixo": postos.prefixo,
    "nome": postos.nome.str.extract(r"\((.*)\)\s*$")[0].str.strip().fillna(postos.nome),
    "rede": np.where(postos.prefixo.str.match(r"^3\d{8}[AB]$"), "cemaden",
                     np.where(postos.prefixo.str.match(r"^A\d+$"), "inmet", "daee")),
    "operador": postos.station_owner.str.replace("�", "Á", regex=False),   # "SP �GUAS" -> "SP ÁGUAS"
    "lat": pd.to_numeric(postos.latitude), "lon": pd.to_numeric(postos.longitude),
})
fora = postos[~(postos.lat.between(-24.01, -23.35) & postos.lon.between(-46.83, -46.36))]
assert fora.empty, f"postos fora da caixa de SP: {fora.prefixo.tolist()}"
print(postos.groupby(["rede", "operador"]).size().to_string())

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Grade de 10 min
# MAGIC
# MAGIC Cada leitura vale para o intervalo **desde a leitura anterior** do mesmo posto. Esse intervalo e repartido
# MAGIC igualmente entre os slots de 10 min que ele cobre (`slot_utc` = inicio do slot; slot `[t, t+10min)`):
# MAGIC
# MAGIC | Caso | O que acontece |
# MAGIC |---|---|
# MAGIC | DAEE, leitura a 10 min da anterior | 1 slot, valor inteiro (`resolucao_min` = 10) |
# MAGIC | posto a 5 min (CTH-USP) | duas leituras no mesmo slot: somadas |
# MAGIC | CEMADEN seco, leitura 60 min depois com 0 mm | 6 slots com 0 |
# MAGIC | CEMADEN, leitura 60 min depois com 3 mm | 6 slots com 0,5 mm, `f_intervalo_longo` (nao sabemos em qual dos 10 min choveu) |
# MAGIC | intervalo > 60 min | so o ultimo slot recebe; os anteriores ficam **faltantes** (mm nulo, `f_faltante`) |
# MAGIC | leitura negativa (15 casos: manutencao do pluviometro) | slots do intervalo com mm nulo, `f_negativo` |
# MAGIC | slot sem nenhuma leitura cobrindo | mm nulo, `f_faltante` — **nunca 0** |
# MAGIC
# MAGIC Slot com mais de 30 mm (180 mm/h) fica com o valor e `f_pico_implausivel` (conferir com os vizinhos).

# COMMAND ----------

SCHEMA_GRADE = T.StructType([
    T.StructField("prefixo", T.StringType()), T.StructField("slot_utc", T.TimestampType()),
    T.StructField("mm", T.DoubleType()), T.StructField("resolucao_min", T.IntegerType()),
    T.StructField("f_faltante", T.BooleanType()), T.StructField("f_negativo", T.BooleanType()),
    T.StructField("f_intervalo_longo", T.BooleanType()), T.StructField("f_pico_implausivel", T.BooleanType()),
])
DEZ = pd.Timedelta(minutes=10)


def regularizar(g: pd.DataFrame) -> pd.DataFrame:
    g = g.sort_values("instante_utc")
    t = pd.to_datetime(g.instante_utc.values)
    v = g.mm.values.astype(float)
    fim_slot = t.ceil("10min")                                    # leitura as 14:50 fecha o slot 14:40–14:50
    gap = np.r_[1, np.diff(fim_slot.values) / np.timedelta64(10, "m")]   # em slots, desde a leitura anterior
    n_slots = np.where(gap > COBERTURA_MAX_MIN / 10, 1, np.maximum(gap, 1)).astype(int)
    # a 1a leitura: nao sabemos o que veio antes, entao vale so para o proprio slot (n_slots[0] = 1)

    linhas = []
    for fs, k, val in zip(fim_slot, n_slots, v):
        for j in range(k):
            linhas.append((fs - DEZ * (j + 1), val / k, 10 * k, val < 0))
    r = pd.DataFrame(linhas, columns=["slot_utc", "mm", "resolucao_min", "f_negativo"])
    # duas leituras no mesmo slot (posto a 5 min): soma; negativo contamina o slot
    r = r.groupby("slot_utc").agg(mm=("mm", "sum"), resolucao_min=("resolucao_min", "min"),
                                  f_negativo=("f_negativo", "any")).reset_index()

    # grade desde o inicio do periodo (ou antes, se a 1a leitura fechar um slot anterior: a das 03:00 fecha 02:50)
    inicio = min(INICIO - DEZ, r.slot_utc.min())
    grade = pd.DataFrame({"slot_utc": pd.date_range(inicio, r.slot_utc.max(), freq="10min")})
    r = grade.merge(r, on="slot_utc", how="left")
    r["f_faltante"] = r.mm.isna()
    r["f_negativo"] = r.f_negativo.astype("boolean").fillna(False).astype(bool)
    r.loc[r.f_negativo, "mm"] = np.nan
    r["f_intervalo_longo"] = r.resolucao_min.fillna(10) > 10
    r["f_pico_implausivel"] = r.mm > PICO_MM_10MIN
    r["resolucao_min"] = r.resolucao_min.astype("Int32")
    r["prefixo"] = g.prefixo.iloc[0]
    return r[SCHEMA_GRADE.fieldNames()]


grade = (spark.table(BRONZE).select("prefixo", "instante_utc", "mm")
         .groupBy("prefixo").applyInPandas(regularizar, schema=SCHEMA_GRADE)
         .withColumn("slot_sp", F.from_utc_timestamp("slot_utc", "America/Sao_Paulo"))
         .withColumn("dt", F.date_format("slot_sp", "yyyy-MM-dd")))
grade.write.mode("overwrite").option("overwriteSchema", True).partitionBy("dt").saveAsTable(CHUVA)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Checagens da grade (falham o run)
# MAGIC
# MAGIC 1. `(prefixo, slot_utc)` unico e todo slot alinhado em 10 min.
# MAGIC 2. **Conservacao:** por posto, mm na grade = soma das leituras nao negativas da bronze (o rateio so espalha,
# MAGIC    nao cria nem perde chuva). **Excecao:** quando uma leitura negativa cai no mesmo slot que uma positiva
# MAGIC    (leituras em minutos quebrados, ex. 16:58 e 17:00), o slot inteiro fica nulo e a parte positiva sai da conta
# MAGIC    (teste local: postos `5`, −1,1 mm, e `804`, −0,2 mm). Nesses postos a grade pode ficar ate 5 mm abaixo.
# MAGIC 3. Todos os 141 postos estao na grade.

# COMMAND ----------

ch = spark.table(CHUVA)
problemas = []
if ch.groupBy("prefixo", "slot_utc").count().filter("count > 1").count():
    problemas.append("(prefixo, slot_utc) repetido")
if ch.filter((F.minute("slot_utc") % 10 != 0) | (F.second("slot_utc") != 0)).count():
    problemas.append("slot fora da grade de 10 min")
conserv = (spark.table(BRONZE).filter("mm >= 0").groupBy("prefixo").agg(F.sum("mm").alias("bronze"))
           .join(ch.groupBy("prefixo").agg(F.sum("mm").alias("grade")), "prefixo", "full").fillna(0)
           .withColumn("dif", F.abs(F.col("bronze") - F.col("grade"))))
com_neg = {r.prefixo for r in ch.filter("f_negativo").select("prefixo").distinct().collect()}
ruins = [r for r in conserv.collect()
         if (r.prefixo in com_neg and not (-0.01 <= r.bronze - r.grade <= 5.0))   # -0,01: arredondamento
         or (r.prefixo not in com_neg and r.dif > 0.01)]
for r in conserv.filter("dif > 0.01").collect():
    print(f"  {r.prefixo}: bronze {r.bronze:.1f} mm, grade {r.grade:.1f} mm (slot negativo + positivo)")
if ruins:
    problemas.append("conservacao falhou: " + ", ".join(f"{r.prefixo} ({r.bronze:.1f} vs {r.grade:.1f})" for r in ruins[:10]))
n_postos = ch.select("prefixo").distinct().count()
if n_postos != len(postos):
    problemas.append(f"{n_postos} postos na grade, {len(postos)} esperados")
assert not problemas, "\n".join(problemas)
print(f"ok: {n_postos} postos, slots unicos e alinhados, chuva conservada em todos")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Qualidade por posto e status
# MAGIC
# MAGIC Medidas no periodo com onibus (desde 25/08):
# MAGIC - `completude` = fracao dos slots de 10 min com valor (nao faltante, nao negativo);
# MAGIC - `maior_lacuna_h` = maior sequencia de slots faltantes;
# MAGIC - `razao_vizinhos` = total do posto / mediana do total dos 5 vizinhos mais proximos **com completude ≥ 90%**.
# MAGIC   Mais justo que a mediana da cidade, porque a chuva variou ~2x entre regioes.
# MAGIC - `chuva_1209_mm` = total em 12/09 (SP), dia de chuva forte em toda a cidade: posto que marca 0 esta quebrado.
# MAGIC
# MAGIC **Status** (primeiro que se aplica): `quebrado` (razao < 0,4, ou 0 mm em 12/09 tendo dado), `suspeito`
# MAGIC (razao > 2,0), `lacunar` (completude < 90%), `ok`. Status nao apaga nada: a gold escolhe quais usar.

# COMMAND ----------

q = (ch.filter(F.col("dt") >= INICIO_ONIBUS)
     .groupBy("prefixo")
     .agg(F.avg((~F.col("f_faltante") & ~F.col("f_negativo")).cast("double")).alias("completude"),
          F.sum("mm").alias("mm_total"),
          F.sum(F.when(F.col("dt") == "2026-09-12", F.col("mm"))).alias("chuva_1209_mm"),
          F.sum(F.when(F.col("dt") == "2026-09-12", (~F.col("f_faltante")).cast("int"))).alias("slots_1209"),
          F.sum(F.col("f_negativo").cast("int")).alias("n_slots_negativos"),
          F.sum(F.col("f_pico_implausivel").cast("int")).alias("n_picos"),
          F.percentile_approx(F.col("resolucao_min"), 0.5).alias("resolucao_mediana_min"))
     .toPandas())

# maior lacuna: sequencias de faltantes (em pandas, ~1,2 M slots no periodo cabem no driver)
falt = (ch.filter(F.col("dt") >= INICIO_ONIBUS).select("prefixo", "slot_utc", "f_faltante")
        .toPandas().sort_values(["prefixo", "slot_utc"]))
falt["bloco"] = (falt.f_faltante != falt.groupby("prefixo").f_faltante.shift()).cumsum()
lac = (falt[falt.f_faltante].groupby(["prefixo", "bloco"]).size().groupby("prefixo").max() * 10 / 60)
q["maior_lacuna_h"] = q.prefixo.map(lac).fillna(0.0).round(1)

q = postos.merge(q, on="prefixo")


def dist_km(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371 * np.arcsin(np.sqrt(a))


ref = q[q.completude >= COMPLETUDE_MIN]
razao, viz_km = [], []
for r in q.itertuples():
    outros = ref[ref.prefixo != r.prefixo]
    d = dist_km(r.lat, r.lon, outros.lat.values, outros.lon.values)
    k = np.argsort(d)[:K_VIZINHOS]
    med = np.median(outros.mm_total.values[k])
    razao.append(r.mm_total / med if med > 0 else np.nan)
    viz_km.append(float(np.mean(d[k])))
q["razao_vizinhos"] = np.round(razao, 2)
q["dist_media_vizinhos_km"] = np.round(viz_km, 1)

q["status"] = np.select(
    [(q.razao_vizinhos < RAZAO_MIN) | ((q.chuva_1209_mm.fillna(0) == 0) & (q.slots_1209 > 0)),
     q.razao_vizinhos > RAZAO_MAX,
     q.completude < COMPLETUDE_MIN],
    ["quebrado", "suspeito", "lacunar"], default="ok")

cols = ["prefixo", "nome", "rede", "operador", "lat", "lon", "resolucao_mediana_min", "completude", "maior_lacuna_h",
        "mm_total", "chuva_1209_mm", "razao_vizinhos", "dist_media_vizinhos_km", "n_slots_negativos", "n_picos", "status"]
q = q[cols]
q["completude"] = q.completude.round(3)
q["mm_total"] = q.mm_total.round(1)
q["chuva_1209_mm"] = q.chuva_1209_mm.round(1)
spark.createDataFrame(q).write.mode("overwrite").option("overwriteSchema", True).saveAsTable(POSTOS)

display(spark.table(POSTOS).groupBy("rede", "status").count().orderBy("rede", "status"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Checagens de sentido (olhar)
# MAGIC
# MAGIC **a) Mapa do total por posto** (desde 25/08). Tem que ser espacialmente suave; pontos isolados muito diferentes
# MAGIC dos vizinhos sao os `quebrado`/`suspeito`. **b) Chuva por hora de SP.** Em set/2026 a chuva foi frontal e
# MAGIC persistente, entao o pico do fim da tarde pode nao aparecer (ver `docs/chuva_sibh.md`, sec. 9).

# COMMAND ----------

import matplotlib.pyplot as plt

p = spark.table(POSTOS).toPandas()
fig, ax = plt.subplots(figsize=(9, 9))
cores = {"ok": "#2f6fb0", "lacunar": "#9aa3ad", "suspeito": "#e8590c", "quebrado": "#d9480f"}
for st, g in p.groupby("status"):
    ax.scatter(g.lon, g.lat, s=20 + g.mm_total.fillna(0) / 6, c=cores[st], alpha=0.75,
               edgecolors="white", label=f"{st} ({len(g)})")
ax.set_aspect(1 / math.cos(math.radians(-23.55)))
ax.set_title("Chuva total desde 25/08 por posto (tamanho = mm)")
ax.legend()
plt.show()

display(spark.table(CHUVA).filter(F.col("dt") >= INICIO_ONIBUS)
        .join(spark.table(POSTOS).filter("status = 'ok'").select("prefixo"), "prefixo")
        .groupBy(F.hour("slot_sp").alias("hora_sp"))
        .agg(F.round(F.sum("mm"), 0).alias("mm_total"),
             F.round(100 * F.avg((F.col("mm") > 0).cast("double")), 2).alias("pct_slots_com_chuva"))
        .orderBy("hora_sp"))

# COMMAND ----------

# MAGIC %run ./metadados

# COMMAND ----------

aplicar_metadados(BRONZE)
aplicar_metadados(CHUVA)
aplicar_metadados(POSTOS)
