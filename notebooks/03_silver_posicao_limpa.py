# Databricks notebook source
# MAGIC %md
# MAGIC # 03 — Silver: posicao_limpa
# MAGIC
# MAGIC **Grao:** 1 posicao de 1 onibus num instante da fonte. Chave `(p, ta)`.
# MAGIC
# MAGIC Entrada: `onibus.bronze.posicao` + `silver.gtfs_trips` + `silver.gtfs_versao`.
# MAGIC Saida: `silver.posicao_limpa` (as que passam) e `silver.quarentena_posicao` (as que nao
# MAGIC passam, com o motivo). Nada some: `bronze = limpa + quarentena`, por dia.
# MAGIC
# MAGIC **Regras**, em ordem (cada linha recebe o primeiro motivo que se aplica).
# MAGIC Tamanhos medidos na bronze de 25/08 a 11/10 (341 M de posicoes):
# MAGIC
# MAGIC | Motivo | Regra | Tamanho |
# MAGIC |---|---|---|
# MAGIC | `duplicata` | mesmo `(p, ta)` mais de uma vez; fica a 1a coleta | 2,0 M (0,59%). Ate 220 repeticoes: onibus "congelado" na API |
# MAGIC | `coordenada_invalida` | lat/lon nulo ou fora da caixa de SP | 0 (guarda) |
# MAGIC | `ta_no_futuro` | `ta` mais de 60 s depois de `coletado_em` | ~0,04%. Ate 60 s e normal: `coletado_em` e o inicio do ciclo e a requisicao leva ate ~46 s |
# MAGIC | `posicao_velha` | `coletado_em − ta` > 5 min | 0,06% (ha posicoes de semanas atras) |
# MAGIC | `linha_sem_shape` | `c` nao tem viagem (logo, shape) no GTFS do dia | 0,4%, 55 linhas: especiais (`PAEC-10`, `TREI-10`...) e ~37 variantes (`177H-21`, `5652-22`...) que estao no `routes.txt` sem `trips` |
# MAGIC | `sentido_sem_shape` | linha tem 2 sentidos no GTFS, mas nao o da API | ~0 |
# MAGIC
# MAGIC **Linhas de sentido unico** (circulares: 1 so shape no GTFS, ~370 linhas, ~6% das posicoes):
# MAGIC a API manda `sl=1` e `sl=2`, mas as duas caem em cima do mesmo shape (erro lateral 0 m na
# MAGIC mediana, p99 < 3 m, teste em 8 linhas em 08/10). Usam esse shape, com `sentido_unico = true`.
# MAGIC Na `deslocamento`, troca de `sl` nessas linhas **nao** e troca de viagem.

# COMMAND ----------

from pyspark.sql import Window, functions as F

spark.conf.set("spark.sql.session.timeZone", "UTC")

BRONZE = "onibus.bronze.posicao"
LIMPA = "onibus.silver.posicao_limpa"
QUARENTENA = "onibus.silver.quarentena_posicao"

CAIXA_SP = {"lat": (-24.01, -23.35), "lon": (-46.83, -46.36)}
FOLGA_FUTURO_S = 60
IDADE_MAX_S = 300

# Feriados nacionais/municipais no periodo da coleta. Onibus rodam com tabela de domingo.
FERIADOS = ["2026-09-07", "2026-10-12", "2026-11-02", "2026-11-15", "2026-11-20", "2026-12-25"]

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. GTFS: de `(versao, c, sl)` para `shape_id`
# MAGIC
# MAGIC Duas tabelinhas, ambas com chave unica (o notebook 02 garante 1 shape por linha × sentido):
# MAGIC - `linha`: por linha, quantos sentidos tem e, se for um so, qual shape;
# MAGIC - `sentido`: por linha × sentido, o shape.

# COMMAND ----------

trips = spark.table("onibus.silver.gtfs_trips").select("versao", "route_id", "direction_id", "shape_id").distinct()

linha = (trips.groupBy("versao", "route_id")
         .agg(F.count("*").alias("n_sentidos"),
              F.first("shape_id").alias("shape_unico"),
              F.first("direction_id").alias("direction_unico"))
         .withColumnRenamed("versao", "versao_gtfs")
         .withColumnRenamed("route_id", "c"))
sentido = (trips.select(F.col("versao").alias("versao_gtfs"), F.col("route_id").alias("c"),
                        "direction_id", F.col("shape_id").alias("shape_sentido")))

assert sentido.groupBy("versao_gtfs", "c", "direction_id").count().filter("count > 1").count() == 0, \
    "linha x sentido com mais de um shape: o join abaixo duplicaria posicoes"

versao = spark.table("onibus.silver.gtfs_versao")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Marcar cada posicao
# MAGIC
# MAGIC A janela por `(p, ta)` ordena pela coleta: a 1a fica, as outras sao `duplicata`. Como a
# MAGIC 1a e a mais recente em relacao a `ta`, o filtro de idade depois do dedupe so pega
# MAGIC posicao que ja chegou velha.

# COMMAND ----------

lat, lon = CAIXA_SP["lat"], CAIXA_SP["lon"]
w_dup = Window.partitionBy("p", "ta").orderBy("coletado_em", "arquivo")

marcado = (
    spark.table(BRONZE)
    .withColumn("ordem", F.row_number().over(w_dup))
    .withColumn("idade_s", F.col("coletado_em").cast("long") - F.col("ta").cast("long"))
    .join(F.broadcast(versao), F.col("dt").cast("date").between(
        F.col("usar_de"), F.coalesce("usar_ate", F.lit("9999-12-31").cast("date"))), "left")
    .withColumnRenamed("versao", "versao_gtfs")
    .join(F.broadcast(linha), ["versao_gtfs", "c"], "left")
    .withColumn("direction_id", F.when(F.col("n_sentidos") == 1, F.col("direction_unico"))
                                 .otherwise(F.col("sl") - 1))
    .join(F.broadcast(sentido), ["versao_gtfs", "c", "direction_id"], "left")
    .withColumn("sentido_unico", F.col("n_sentidos") == 1)
    .withColumn("shape_id", F.when(F.col("sentido_unico"), F.col("shape_unico"))
                             .otherwise(F.col("shape_sentido")))
    .withColumn("motivo",
        F.when(F.col("ordem") > 1, "duplicata")
         .when(F.col("py").isNull() | F.col("px").isNull()
               | ~F.col("py").between(*lat) | ~F.col("px").between(*lon), "coordenada_invalida")
         .when(F.col("idade_s") < -FOLGA_FUTURO_S, "ta_no_futuro")
         .when(F.col("idade_s") > IDADE_MAX_S, "posicao_velha")
         .when(F.col("n_sentidos").isNull(), "linha_sem_shape")
         .when(F.col("shape_id").isNull(), "sentido_sem_shape"))
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Gravar
# MAGIC
# MAGIC `ta_sp` e o horario de parede de SP (o `ta` continua em UTC). `tipo_dia` sai da data de
# MAGIC `ta_sp`, nao de `dt`: perto da meia-noite os dois podem diferir.

# COMMAND ----------

data_sp = F.to_date("ta_sp")
limpa = (
    marcado.filter(F.col("motivo").isNull())
    .withColumn("ta_sp", F.from_utc_timestamp("ta", "America/Sao_Paulo"))
    .withColumn("tipo_dia",
        F.when(data_sp.cast("string").isin(FERIADOS), "feriado")
         .when(F.dayofweek(data_sp) == 1, "domingo")
         .when(F.dayofweek(data_sp) == 7, "sabado")
         .otherwise("util"))
    .select("dt", "p", "ta", "ta_sp", "tipo_dia",
            F.col("c").alias("route_id"), "sl", "direction_id", "shape_id", "sentido_unico", "versao_gtfs",
            "py", "px", "coletado_em", "idade_s", "formato")
)

quarentena = (marcado.filter(F.col("motivo").isNotNull())
              .select(*spark.table(BRONZE).columns, "motivo"))

(quarentena.write.mode("overwrite").option("overwriteSchema", True)
    .partitionBy("dt").saveAsTable(QUARENTENA))
(limpa.write.mode("overwrite").option("overwriteSchema", True)
    .partitionBy("dt").saveAsTable(LIMPA))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Checagens (falham o run)
# MAGIC
# MAGIC 1. Por dia: `bronze = limpa + quarentena`.
# MAGIC 2. `(p, ta)` unico na limpa.
# MAGIC 3. Nenhuma posicao limpa sem `shape_id` ou `ta_sp`.

# COMMAND ----------

por_dia = lambda t, nome: spark.table(t).groupBy("dt").agg(F.count("*").alias(nome))
checagem = (por_dia(BRONZE, "bronze")
            .join(por_dia(LIMPA, "limpa"), "dt", "full")
            .join(por_dia(QUARENTENA, "quarentena"), "dt", "full")
            .fillna(0)
            .withColumn("dif", F.col("bronze") - F.col("limpa") - F.col("quarentena"))
            .orderBy("dt"))
display(checagem)

problemas = [f"{r.dt}: dif {r.dif:+}" for r in checagem.filter("dif != 0").collect()]
repetidas = spark.table(LIMPA).groupBy("p", "ta").count().filter("count > 1").count()
if repetidas:
    problemas.append(f"{repetidas} (p, ta) repetidos na limpa")
sem_shape = spark.table(LIMPA).filter(F.col("shape_id").isNull() | F.col("ta_sp").isNull()).count()
if sem_shape:
    problemas.append(f"{sem_shape} posicoes limpas sem shape_id/ta_sp")
assert not problemas, "\n".join(problemas)
print(f"ok: {checagem.count()} dias, bronze = limpa + quarentena; (p, ta) unico; todas com shape")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4b. Metadados
# MAGIC
# MAGIC O `overwrite` com `overwriteSchema` apaga os comentarios das colunas; reaplica a partir de `metadados`.

# COMMAND ----------

# MAGIC %run ./metadados

# COMMAND ----------

aplicar_metadados(LIMPA)
aplicar_metadados(QUARENTENA)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Relatorio

# COMMAND ----------

total = spark.table(BRONZE).groupBy("formato").agg(F.count("*").alias("bronze"))
display(spark.table(QUARENTENA).groupBy("formato", "motivo").agg(F.count("*").alias("n"))
        .join(total, "formato")
        .withColumn("pct", F.round(100 * F.col("n") / F.col("bronze"), 3))
        .orderBy("formato", F.desc("n")))

display(spark.table(LIMPA).groupBy("tipo_dia").agg(
            F.countDistinct(F.to_date("ta_sp")).alias("dias"),
            F.count("*").alias("posicoes"),
            F.round(100 * F.avg(F.col("sentido_unico").cast("double")), 2).alias("pct_sentido_unico"))
        .orderBy("tipo_dia"))
