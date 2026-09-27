# Databricks notebook source
# MAGIC %md
# MAGIC # 01 — Bronze: posicoes do Olho Vivo (formato v2, cru)
# MAGIC
# MAGIC Le os arquivos `.json.gz` do volume (uma resposta inteira da API por arquivo),
# MAGIC achata para **uma linha por onibus por ciclo** e grava a tabela Delta
# MAGIC `onibus.bronze.posicao`, particionada por `dt` (dia de SP).
# MAGIC
# MAGIC Nada de limpeza aqui: sem dedupe, sem filtro. Isso e trabalho da silver.
# MAGIC A unica coisa descartada sao os arquivos `null` (resposta vazia da API).

# COMMAND ----------

from pyspark.sql import functions as F, types as T

# Todos os timestamps em UTC; a conversao para horario de SP e explicita.
spark.conf.set("spark.sql.session.timeZone", "UTC")

BASE = "/Volumes/onibus/bronze/raw/olhovivo/bronze_raw"
TABELA = "onibus.bronze.posicao"

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Ler os arquivos crus
# MAGIC
# MAGIC Schema explicito em vez de deixar o Spark adivinhar: (a) nao precisa ler tudo
# MAGIC duas vezes para inferir, (b) se a SPTrans mudar um tipo, a gente percebe.
# MAGIC A pasta `dt=...` vira uma coluna automaticamente (particionamento).

# COMMAND ----------

veiculo = T.StructType([
    T.StructField("p", T.LongType()),       # prefixo do onibus
    T.StructField("a", T.BooleanType()),    # acessivel
    T.StructField("ta", T.StringType()),    # instante da posicao na fonte (UTC)
    T.StructField("py", T.DoubleType()),    # latitude
    T.StructField("px", T.DoubleType()),    # longitude
])
linha = T.StructType([
    T.StructField("c", T.StringType()),     # letreiro = route_id do GTFS
    T.StructField("cl", T.LongType()),      # codigo interno linha+sentido
    T.StructField("sl", T.IntegerType()),   # sentido 1/2
    T.StructField("lt0", T.StringType()),
    T.StructField("lt1", T.StringType()),
    T.StructField("qv", T.IntegerType()),   # qtd de veiculos da linha
    T.StructField("vs", T.ArrayType(veiculo)),
])
payload = T.StructType([
    T.StructField("hr", T.StringType()),    # hora da resposta, SP
    T.StructField("l", T.ArrayType(linha)),
])

raw = (spark.read.schema(payload).json(BASE)
       .withColumn("arquivo", F.col("_metadata.file_path")))

print("arquivos lidos:", raw.count())
print("arquivos null :", raw.filter(F.col("l").isNull()).count())

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Achatar
# MAGIC
# MAGIC `explode` transforma cada item de uma lista numa linha. Dois explodes:
# MAGIC resposta → linhas de onibus → veiculos. O instante da coleta vem do nome
# MAGIC do arquivo (`posicao_20260922T030001Z.json.gz`).

# COMMAND ----------

posicao = (
    raw.filter(F.col("l").isNotNull())
    .withColumn("coletado_em", F.to_timestamp(
        F.regexp_extract("arquivo", r"(\d{8}T\d{6}Z)", 1), "yyyyMMdd'T'HHmmss'Z'"))
    .select("dt", "coletado_em", "hr", "arquivo", F.explode("l").alias("linha"))
    .select("*", F.explode("linha.vs").alias("v"))
    .select(
        F.col("dt").cast("string").alias("dt"),
        "coletado_em",
        F.to_timestamp("v.ta").alias("ta"),
        F.col("v.p").alias("p"),
        F.col("linha.c").alias("c"),
        F.col("linha.cl").alias("cl"),
        F.col("linha.sl").alias("sl"),
        F.col("v.py").alias("py"),
        F.col("v.px").alias("px"),
        F.col("v.a").alias("a"),
        F.col("linha.lt0").alias("lt0"),
        F.col("linha.lt1").alias("lt1"),
        "hr",
        "arquivo",
    )
)
display(posicao.limit(10))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Gravar como tabela Delta

# COMMAND ----------

(posicao.write
    .mode("overwrite")
    .partitionBy("dt")
    .saveAsTable(TABELA))

print(spark.table(TABELA).count(), "linhas em", TABELA)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Checagem de ponta a ponta
# MAGIC
# MAGIC Linhas por dia na tabela **tem que ser igual** a soma de `veiculos_gravados`
# MAGIC dos ciclos ok na auditoria. `dif` diferente de zero = posicao perdida ou
# MAGIC duplicada no caminho.

# COMMAND ----------

aud = spark.read.option("header", True).csv("/Volumes/onibus/bronze/raw/olhovivo/auditoria.csv")

aud_dia = (
    aud.filter(F.col("status") == "ok")
    .withColumn("dt", F.date_format(
        F.from_utc_timestamp(F.to_timestamp("coletado_em"), "America/Sao_Paulo"), "yyyy-MM-dd"))
    .groupBy("dt")
    .agg(F.count("*").alias("ciclos_ok"),
         F.sum(F.col("veiculos_gravados").cast("long")).alias("auditoria"))
)
tab_dia = spark.table(TABELA).groupBy("dt").agg(F.count("*").alias("tabela"))

display(tab_dia.join(aud_dia, "dt", "left")
        .withColumn("dif", F.col("tabela") - F.col("auditoria"))
        .orderBy("dt"))
