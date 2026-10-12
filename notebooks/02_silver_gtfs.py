# Databricks notebook source
# MAGIC %md
# MAGIC # 02 — Silver: GTFS da SPTrans
# MAGIC
# MAGIC Uma tabela Delta por arquivo do GTFS, com tipos explicitos: `onibus.silver.gtfs_*`.
# MAGIC O grao de cada tabela e o do proprio arquivo, mais a coluna `versao`.
# MAGIC
# MAGIC | Tabela | 1 linha = | Para que serve |
# MAGIC |---|---|---|
# MAGIC | `gtfs_routes` | 1 linha de onibus | `route_id` = `c` da API |
# MAGIC | `gtfs_trips` | 1 viagem-modelo (linha × sentido × servico) | linha + `direction_id` → `shape_id` |
# MAGIC | `gtfs_shapes` | 1 ponto do tracado | a "regua" da rota (`shape_dist_traveled`, em metros) |
# MAGIC | `gtfs_stops` | 1 parada | posicao das paradas |
# MAGIC | `gtfs_stop_times` | 1 parada de 1 viagem | ordem das paradas → trechos |
# MAGIC | `gtfs_frequencies` | 1 faixa horaria de 1 viagem | headway programado |
# MAGIC | `gtfs_calendar` | 1 tipo de servico | dias da semana em que a viagem roda |
# MAGIC | `gtfs_versao` | 1 versao do GTFS | qual versao usar para cada dia |
# MAGIC
# MAGIC **Ponte com a bronze:** `c = route_id` e `sl = direction_id + 1` (validado em agosto).
# MAGIC
# MAGIC **Por que versionar.** O GTFS muda. Entre 26/08 e 12/10, 882 dos 2.188 shapes em comum
# MAGIC mudaram (a maioria < 15 m; 21 mudaram mais de 500 m de comprimento), 83 viagens trocaram
# MAGIC de shape e 612 das 2.271 mudaram a sequencia de paradas. A versao `AAAA-MM-DD` e a data
# MAGIC do download; `gtfs_versao` diz de que dia a que dia cada uma vale.
# MAGIC
# MAGIC **Versao nova:** baixar o zip, extrair em `/Volumes/onibus/bronze/raw/gtfs/versao=AAAA-MM-DD/`
# MAGIC e rodar este notebook de novo. Ele refaz as tabelas a partir de todas as versoes do volume.

# COMMAND ----------

from pyspark.sql import Window, functions as F, types as T

RAIZ = "/Volumes/onibus/bronze/raw/gtfs"
ESQUEMA = "onibus.silver"
INICIO_COLETA = "2026-08-25"   # a primeira versao vale tambem para os dias antes dela
CAIXA_SP = {"lat": (-24.01, -23.35), "lon": (-46.83, -46.36)}

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Schemas
# MAGIC
# MAGIC IDs ficam como texto (o GTFS define assim, e `route_id` tem hifen). Horarios do GTFS
# MAGIC tambem ficam como texto: podem passar de `24:00:00` (viagem que vira a noite).

# COMMAND ----------

S, I, D = T.StringType(), T.IntegerType(), T.DoubleType()

def schema(*campos):
    return T.StructType([T.StructField(nome, tipo) for nome, tipo in campos])

DIAS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

ARQUIVOS = {
    "routes": schema(("route_id", S), ("agency_id", S), ("route_short_name", S), ("route_long_name", S),
                     ("route_type", I), ("route_color", S), ("route_text_color", S)),
    "trips": schema(("route_id", S), ("service_id", S), ("trip_id", S), ("trip_headsign", S),
                    ("direction_id", I), ("shape_id", S)),
    "shapes": schema(("shape_id", S), ("shape_pt_lat", D), ("shape_pt_lon", D),
                     ("shape_pt_sequence", I), ("shape_dist_traveled", D)),
    "stops": schema(("stop_id", S), ("stop_name", S), ("stop_desc", S), ("stop_lat", D), ("stop_lon", D)),
    "stop_times": schema(("trip_id", S), ("arrival_time", S), ("departure_time", S),
                         ("stop_id", S), ("stop_sequence", I)),
    "frequencies": schema(("trip_id", S), ("start_time", S), ("end_time", S), ("headway_secs", I)),
    "calendar": schema(("service_id", S), *[(d, I) for d in DIAS], ("start_date", S), ("end_date", S)),
}

CHAVES = {
    "routes": ["route_id"],
    "trips": ["trip_id"],
    "shapes": ["shape_id", "shape_pt_sequence"],
    "stops": ["stop_id"],
    "stop_times": ["trip_id", "stop_sequence"],
    "frequencies": ["trip_id", "start_time"],
    "calendar": ["service_id"],
}

# (tabela filha, coluna, tabela mae): todo valor da filha tem que existir na mae, na mesma versao
REFERENCIAS = [
    ("trips", "route_id", "routes"),
    ("trips", "shape_id", "shapes"),
    ("trips", "service_id", "calendar"),
    ("stop_times", "trip_id", "trips"),
    ("stop_times", "stop_id", "stops"),
    ("frequencies", "trip_id", "trips"),
]

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Ler e gravar
# MAGIC
# MAGIC - `enforceSchema=False`: o cabecalho do arquivo e conferido com o schema. Se a SPTrans
# MAGIC   trocar colunas de lugar, a leitura falha em vez de trocar os dados de coluna em silencio.
# MAGIC - `mode=FAILFAST`: valor que nao casa com o tipo vira erro, nao `null`.
# MAGIC - `recursiveFileLookup` + `pathGlobFilter`: le `routes.txt` de todas as pastas `versao=...`;
# MAGIC   a versao sai do caminho do arquivo.

# COMMAND ----------

def versao_do_arquivo():
    return F.to_date(F.regexp_extract("_metadata.file_path", r"versao=(\d{4}-\d{2}-\d{2})", 1))

def ler(nome):
    return (spark.read.schema(ARQUIVOS[nome])
            .option("header", True)
            .option("enforceSchema", False)
            .option("mode", "FAILFAST")
            .option("recursiveFileLookup", True)
            .option("pathGlobFilter", f"{nome}.txt")
            .csv(RAIZ)
            .withColumn("versao", versao_do_arquivo())
            .select("versao", *ARQUIVOS[nome].fieldNames()))

def segundos(col):
    """'HH:MM:SS' -> segundos desde a meia-noite (aceita HH >= 24)."""
    p = F.split(col, ":")
    return p[0].cast("int") * 3600 + p[1].cast("int") * 60 + p[2].cast("int")

for nome in ARQUIVOS:
    df = ler(nome)
    if nome == "frequencies":
        df = df.withColumn("inicio_s", segundos("start_time")).withColumn("fim_s", segundos("end_time"))
    if nome == "calendar":
        df = (df.withColumn("start_date", F.to_date("start_date", "yyyyMMdd"))
                .withColumn("end_date", F.to_date("end_date", "yyyyMMdd")))
    (df.write.mode("overwrite").option("overwriteSchema", True)
       .saveAsTable(f"{ESQUEMA}.gtfs_{nome}"))
    print(f"{ESQUEMA}.gtfs_{nome}: {spark.table(f'{ESQUEMA}.gtfs_{nome}').count():,} linhas")

def tab(nome):
    return spark.table(f"{ESQUEMA}.gtfs_{nome}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Qual versao vale em cada dia
# MAGIC
# MAGIC Cada versao vale do dia do download ate a vespera da seguinte; a primeira cobre tambem
# MAGIC o inicio da coleta. `usar_ate` nulo = vale ate hoje. Na silver, o join e
# MAGIC `dt BETWEEN usar_de AND coalesce(usar_ate, '9999-12-31')`.
# MAGIC
# MAGIC Limitacao: so sabemos quando baixamos, nao quando a SPTrans mudou. Os dias antes de um
# MAGIC download podem estar usando um tracado ja desatualizado.

# COMMAND ----------

w = Window.orderBy("versao")
gtfs_versao = (
    tab("routes").select("versao").distinct()
    .withColumn("usar_de", F.when(F.row_number().over(w) == 1, F.to_date(F.lit(INICIO_COLETA)))
                            .otherwise(F.col("versao")))
    .withColumn("usar_ate", F.date_sub(F.lead("versao").over(w), 1))
)
gtfs_versao.write.mode("overwrite").option("overwriteSchema", True).saveAsTable(f"{ESQUEMA}.gtfs_versao")
display(spark.table(f"{ESQUEMA}.gtfs_versao").orderBy("versao"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Checagens (falham o run)
# MAGIC
# MAGIC 1. **Contagem:** linhas do arquivo − cabecalho = linhas da tabela, por versao.
# MAGIC 2. **Chave:** sem nulo e sem repeticao.
# MAGIC 3. **Referencia:** toda `route_id`, `shape_id`, `trip_id`, `stop_id`... usada existe na tabela de origem.

# COMMAND ----------

problemas = []

# 1. contagem
contagem = []
for nome in ARQUIVOS:
    arq = (spark.read.option("recursiveFileLookup", True).option("pathGlobFilter", f"{nome}.txt").text(RAIZ)
           .withColumn("versao", versao_do_arquivo())
           .groupBy("versao").agg((F.count("*") - 1).alias("arquivo")))
    t = tab(nome).groupBy("versao").agg(F.count("*").alias("tabela"))
    for r in arq.join(t, "versao", "full").collect():
        contagem.append((nome, r.versao, r.arquivo, r.tabela))
        if r.arquivo != r.tabela:
            problemas.append(f"contagem {nome} {r.versao}: arquivo {r.arquivo} x tabela {r.tabela}")
display(spark.createDataFrame(contagem, "tabela string, versao date, arquivo long, tabela_delta long")
        .orderBy("tabela", "versao"))

# 2. chave
for nome, chave in CHAVES.items():
    nulos = tab(nome).filter(" OR ".join(f"{c} IS NULL" for c in chave)).count()
    repetidas = tab(nome).groupBy("versao", *chave).count().filter("count > 1").count()
    if nulos or repetidas:
        problemas.append(f"chave {nome}{chave}: {nulos} nulas, {repetidas} repetidas")

# 3. referencia
for filha, col, mae in REFERENCIAS:
    orfas = (tab(filha).select("versao", col).distinct()
             .join(tab(mae).select("versao", col).distinct(), ["versao", col], "left_anti"))
    n = orfas.count()
    if n:
        problemas.append(f"referencia {filha}.{col} -> {mae}: {n} valores sem par, ex. "
                         + ", ".join(str(r[col]) for r in orfas.limit(5).collect()))

assert not problemas, "\n".join(problemas)
print("ok: contagem, chaves e referencias")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Relatorio (nao falha; e para saber com o que estamos lidando)

# COMMAND ----------

lat, lon = CAIXA_SP["lat"], CAIXA_SP["lon"]
fora_caixa = lambda la, lo: ~(F.col(la).between(*lat) & F.col(lo).between(*lon))

passo = F.col("shape_dist_traveled") - F.lag("shape_dist_traveled").over(
    Window.partitionBy("versao", "shape_id").orderBy("shape_pt_sequence"))
shapes_rel = (tab("shapes").withColumn("passo", passo)
              .groupBy("versao").agg(
                  F.countDistinct("shape_id").alias("shapes"),
                  F.sum((F.col("passo") < 0).cast("int")).alias("dist_decrescente"),
                  F.sum((F.col("passo") == 0).cast("int")).alias("pontos_repetidos"),
                  F.countDistinct(F.when(fora_caixa("shape_pt_lat", "shape_pt_lon"), F.col("shape_id"))).alias("shapes_saem_de_SP")))

shapes_por_sentido = (tab("trips").groupBy("versao", "route_id", "direction_id")
                      .agg(F.countDistinct("shape_id").alias("n"))
                      .groupBy("versao").agg(F.sum((F.col("n") > 1).cast("int")).alias("linha_sentido_com_2+_shapes")))
trips_rel = (tab("trips").groupBy("versao").agg(
                 F.countDistinct("route_id").alias("linhas"),
                 F.count("*").alias("viagens"),
                 F.sum((F.col("direction_id") == 0).cast("int")).alias("sentido_0"),
                 F.sum((F.col("direction_id") == 1).cast("int")).alias("sentido_1"))
             .join(shapes_por_sentido, "versao"))
paradas_rel = (tab("stops").groupBy("versao").agg(
                   F.count("*").alias("paradas"),
                   F.sum(fora_caixa("stop_lat", "stop_lon").cast("int")).alias("paradas_fora_de_SP")))

display(trips_rel.join(shapes_rel, "versao").join(paradas_rel, "versao").orderBy("versao"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Cobertura: quanto da bronze casa com o GTFS
# MAGIC
# MAGIC No ultimo dia da bronze, que fracao das posicoes tem (a) linha no GTFS e (b) linha + sentido
# MAGIC com shape. Em agosto: (a) 99,8%; (b) ~94% dos veiculos. Queda aqui = versao errada ou
# MAGIC linha nova sem tracado.

# COMMAND ----------

pos = spark.table("onibus.bronze.posicao")
ultimo = pos.agg(F.max("dt")).first()[0]
v = (spark.table(f"{ESQUEMA}.gtfs_versao")
     .filter(F.lit(ultimo).cast("date").between(F.col("usar_de"), F.coalesce("usar_ate", F.lit("9999-12-31").cast("date"))))
     .first().versao)

linhas = tab("routes").filter(F.col("versao") == v).select(F.col("route_id").alias("c"), F.lit(True).alias("tem_linha"))
sentidos = (tab("trips").filter(F.col("versao") == v)
            .select(F.col("route_id").alias("c"), (F.col("direction_id") + 1).alias("sl"), F.lit(True).alias("tem_shape"))
            .distinct())

cobertura = (pos.filter(F.col("dt") == ultimo)
             .join(linhas, "c", "left").join(sentidos, ["c", "sl"], "left")
             .agg(F.count("*").alias("posicoes"),
                  F.round(100 * F.avg(F.col("tem_linha").isNotNull().cast("double")), 2).alias("pct_com_linha"),
                  F.round(100 * F.avg(F.col("tem_shape").isNotNull().cast("double")), 2).alias("pct_com_shape")))
print(f"dia {ultimo}, GTFS versao {v}")
display(cobertura)
