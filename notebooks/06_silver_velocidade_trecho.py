# Databricks notebook source
# MAGIC %md
# MAGIC # 06 — Silver: gtfs_trechos e velocidade_trecho
# MAGIC
# MAGIC Ultima etapa da silver: de **pares de posicoes** (`deslocamento`) para **velocidade por trecho entre
# MAGIC paradas, a cada 10 minutos** — o insumo dos KRs.
# MAGIC
# MAGIC **Parte A — `silver.gtfs_trechos`.** Cada par de paradas consecutivas de cada shape, com inicio e fim
# MAGIC na mesma regua da `posicao_rota` (`d_ini_m`, `d_fim_m`). As paradas do `stop_times` sao projetadas no
# MAGIC shape **em ordem**: cada parada so pode cair adiante da anterior (resolve shape que passa duas vezes pela
# MAGIC mesma rua, como nas circulares). O GTFS da SPTrans tem 1 viagem por shape, ~44 paradas.
# MAGIC
# MAGIC **Parte B — `silver.velocidade_trecho`.** Um par anda 200–700 m e um trecho tem ~300–400 m: quase nenhum
# MAGIC trecho tem ping dentro. Entao cada par `ok` **rateia** distancia e tempo entre os trechos que atravessou,
# MAGIC supondo velocidade constante dentro do par:
# MAGIC
# MAGIC ```
# MAGIC par: d 12.060 -> 12.330 (270 m) em 45 s;  parada em 12.150
# MAGIC   trecho anterior: 90 m em 15 s      trecho seguinte: 180 m em 30 s
# MAGIC ```
# MAGIC
# MAGIC Cada pedaco vai para a janela de 10 min (horario de SP) do seu instante medio. Por trecho x janela:
# MAGIC **velocidade = Σ distancia / Σ tempo** (media ponderada — um par curto e lento nao pesa igual a um longo).
# MAGIC Par parado (Δd <= 0: recuo pequeno ou engarrafamento) conta **tempo** no trecho onde esta e distancia 0.
# MAGIC
# MAGIC Fica de fora: o que o onibus anda antes da 1a parada e depois da ultima.
# MAGIC
# MAGIC Tambem guardamos o **trecho fisico** (`parada_de`, `parada_ate`): a mesma rua percorrida por varias
# MAGIC linhas. Na gold, juntar as linhas por trecho fisico multiplica as observacoes (estabilidade do KR3).

# COMMAND ----------

import math

import numpy as np
import pandas as pd
from pyspark.sql import functions as F, types as T

spark.conf.set("spark.sql.session.timeZone", "UTC")

DESL = "onibus.silver.deslocamento"
TRECHOS = "onibus.silver.gtfs_trechos"
VEL = "onibus.silver.velocidade_trecho"

# Teste: um dia e poucas linhas -> so mostra, nao grava a velocidade (a gtfs_trechos e pequena e sempre
# e recalculada). Producao: linhas vazio -> grava; dias vazio = todos (overwrite), senao replaceWhere.
dbutils.widgets.text("dias", "2026-10-08")
dbutils.widgets.text("linhas", "2290-10,6000-10,516N-10,4113-10")
DIAS = [d.strip() for d in dbutils.widgets.get("dias").split(",") if d.strip()]
LINHAS = [l.strip() for l in dbutils.widgets.get("linhas").split(",") if l.strip()]
ESCREVER = not LINHAS

LAT0, LON0, R_TERRA = -23.55, -46.63, 6_371_000.0
VOLTA_M = 30.0        # parada pode cair ate 30 m "atras" da anterior (ruido da projecao)
MARGEM_PARADA_M = 25  # passagens "boas" = erro ate (melhor + 25 m); entre elas, a mais proxima adiante
JANELA_MIN = 10
print(f"dias={DIAS or 'todos'} linhas={LINHAS or 'todas'} escrever={ESCREVER}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## A1. Projetar as paradas no shape, em ordem
# MAGIC
# MAGIC Mesma geometria do notebook 04 (plano equirretangular centrado em SP). Para cada parada, calcula a
# MAGIC projecao em **todos** os segmentos do shape. Entre as que estao **adiante da parada anterior**, ficam as
# MAGIC "boas" (erro ate o melhor + 25 m) e, entre elas, a **mais proxima adiante** — nao a de menor erro.
# MAGIC
# MAGIC Por que: numa linha de ida e volta pela mesma avenida, a parada do inicio da ida tambem esta a poucos
# MAGIC metros da volta (calcada oposta), perto do fim da rota. Escolhendo so pelo erro, a projecao pulava para o
# MAGIC fim e todas as paradas seguintes ficavam presas ali (1a versao: 23 mil trechos de 0 m, 673 shapes).
# MAGIC Se nenhuma passagem estiver adiante, fica a de menor erro e a parada e marcada (`fora_de_ordem`).

# COMMAND ----------

def para_xy(lat, lon):
    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)
    return (np.radians(lon - LON0) * R_TERRA * math.cos(math.radians(LAT0)),
            np.radians(lat - LAT0) * R_TERRA)


SCHEMA_PARADA = T.StructType([
    T.StructField("versao", T.DateType()), T.StructField("shape_id", T.StringType()),
    T.StructField("stop_sequence", T.IntegerType()), T.StructField("stop_id", T.StringType()),
    T.StructField("d_m", T.DoubleType()), T.StructField("erro_m", T.DoubleType()),
    T.StructField("fora_de_ordem", T.BooleanType()), T.StructField("comprimento_m", T.DoubleType()),
])


def projetar_paradas(paradas: pd.DataFrame, shp: pd.DataFrame) -> pd.DataFrame:
    if paradas.empty or shp.empty:
        return pd.DataFrame(columns=SCHEMA_PARADA.fieldNames())
    shp = shp.sort_values("shape_pt_sequence")
    sx, sy = para_xy(shp.shape_pt_lat.values, shp.shape_pt_lon.values)
    sd = shp.shape_dist_traveled.values.astype(float)
    ax, ay, vx, vy = sx[:-1], sy[:-1], np.diff(sx), np.diff(sy)
    v2 = vx * vx + vy * vy
    v2[v2 == 0] = 1e-12
    d0, dlen = sd[:-1], np.diff(sd)

    paradas = paradas.sort_values("stop_sequence").reset_index(drop=True)
    px, py = para_xy(paradas.stop_lat.values, paradas.stop_lon.values)
    # matriz parada x segmento (~44 x ~1.000): pequena, cabe inteira
    t = np.clip(((px[:, None] - ax) * vx + (py[:, None] - ay) * vy) / v2, 0.0, 1.0)
    erro = np.hypot(px[:, None] - ax - t * vx, py[:, None] - ay - t * vy)
    dal = d0 + t * dlen

    d_out, e_out, fora = [], [], []
    ant = -np.inf
    for i in range(len(paradas)):
        adiante = dal[i] >= ant - VOLTA_M
        if adiante.any():
            boas = adiante & (erro[i] <= erro[i, adiante].min() + MARGEM_PARADA_M)
            j = np.flatnonzero(boas)[np.argmin(dal[i, boas])]
            fora.append(False)
        else:
            j = int(np.argmin(erro[i]))
            fora.append(True)
        d = max(dal[i, j], ant) if np.isfinite(ant) else dal[i, j]   # nunca anda para tras
        d_out.append(d); e_out.append(erro[i, j]); ant = d

    return pd.DataFrame({
        "versao": paradas.versao.values, "shape_id": paradas.shape_id.values,
        "stop_sequence": paradas.stop_sequence.values.astype("int32"),
        "stop_id": paradas.stop_id.astype(str).values,
        "d_m": d_out, "erro_m": e_out, "fora_de_ordem": fora, "comprimento_m": float(sd[-1])})


trips = spark.table("onibus.silver.gtfs_trips").select("versao", "trip_id", "route_id", "direction_id", "shape_id")
paradas = (spark.table("onibus.silver.gtfs_stop_times").select("versao", "trip_id", "stop_id", "stop_sequence")
           .join(trips, ["versao", "trip_id"])
           .join(spark.table("onibus.silver.gtfs_stops").select("versao", "stop_id", "stop_lat", "stop_lon"),
                 ["versao", "stop_id"])
           .select("versao", "shape_id", F.col("stop_id").cast("string").alias("stop_id"),
                   F.col("stop_sequence").cast("int").alias("stop_sequence"), "stop_lat", "stop_lon"))
pontos = spark.table("onibus.silver.gtfs_shapes").select(
    "versao", "shape_id", "shape_pt_sequence", "shape_pt_lat", "shape_pt_lon", "shape_dist_traveled")

proj = (paradas.groupBy("versao", "shape_id")
        .cogroup(pontos.groupBy("versao", "shape_id"))
        .applyInPandas(projetar_paradas, schema=SCHEMA_PARADA))

# COMMAND ----------

# MAGIC %md
# MAGIC ## A2. Paradas consecutivas viram trechos
# MAGIC
# MAGIC Trecho `k` = da parada `k` ate a `k+1`. Trechos de comprimento ~0 (duas paradas no mesmo ponto
# MAGIC projetado) saem — nao tem como medir velocidade em 0 m.

# COMMAND ----------

from pyspark.sql import Window

w = Window.partitionBy("versao", "shape_id").orderBy("stop_sequence")
trechos = (proj
           .withColumn("parada_ate", F.lead("stop_id").over(w))
           .withColumn("d_fim_m", F.lead("d_m").over(w))
           .withColumn("fora_de_ordem", F.col("fora_de_ordem") | F.coalesce(F.lead("fora_de_ordem").over(w), F.lit(False)))
           .filter(F.col("parada_ate").isNotNull())
           .withColumnRenamed("stop_id", "parada_de").withColumnRenamed("d_m", "d_ini_m")
           .withColumn("comprimento_trecho_m", F.col("d_fim_m") - F.col("d_ini_m"))
           .withColumn("trecho_seq", F.row_number().over(w))
           .join(trips.select("versao", "shape_id", "route_id", "direction_id").distinct(), ["versao", "shape_id"])
           .select("versao", "route_id", "direction_id", "shape_id", "trecho_seq", "parada_de", "parada_ate",
                   "d_ini_m", "d_fim_m", "comprimento_trecho_m", F.col("erro_m").alias("erro_parada_de_m"),
                   "fora_de_ordem", "comprimento_m"))

zero = trechos.filter("comprimento_trecho_m < 1").count()
total_pares_paradas = trechos.count()
trechos = trechos.filter("comprimento_trecho_m >= 1")
# O GTFS tem ~60 pares de paradas consecutivas a < 1 m. Muito mais que isso = projecao errada.
assert zero < 0.005 * total_pares_paradas, f"{zero} trechos de ~0 m de {total_pares_paradas}: projecao das paradas falhou"

(trechos.write.mode("overwrite").option("overwriteSchema", True).saveAsTable(TRECHOS))
tr = spark.table(TRECHOS)
resumo = tr.agg(F.count("*").alias("trechos"), F.countDistinct("versao", "shape_id").alias("shapes"),
                F.round(F.percentile_approx("comprimento_trecho_m", 0.5)).alias("comp_mediano_m"),
                F.round(F.percentile_approx("erro_parada_de_m", 0.5), 1).alias("erro_parada_mediano_m"),
                F.round(F.percentile_approx("erro_parada_de_m", 0.99), 1).alias("erro_parada_p99_m"),
                F.sum(F.col("fora_de_ordem").cast("int")).alias("fora_de_ordem")).first()
print(resumo, f"| trechos ~0 m removidos: {zero}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## B1. Ratear cada par entre os trechos que atravessou
# MAGIC
# MAGIC Um grupo = um shape num dia (os pares `ok` + os limites dos trechos). Dentro do grupo, com numpy:
# MAGIC 1. limites do shape `B = [d da parada 1, ..., d da ultima parada]`;
# MAGIC 2. para o par `[a, b]`, cada trecho `[B_k, B_k+1]` recebe a sobreposicao `max(0, min(b, B_k+1) − max(a, B_k))`
# MAGIC    de distancia e a mesma fracao do tempo;
# MAGIC 3. o pedaco vai para a janela de 10 min do seu instante medio.

# COMMAND ----------

SCHEMA_VEL = T.StructType([
    T.StructField("dt", T.StringType()), T.StructField("versao_gtfs", T.DateType()),
    T.StructField("shape_id", T.StringType()), T.StructField("tipo_dia", T.StringType()),
    T.StructField("trecho_seq", T.IntegerType()), T.StructField("janela_sp", T.TimestampType()),
    T.StructField("dist_m", T.DoubleType()), T.StructField("tempo_s", T.DoubleType()),
    T.StructField("n_pares", T.LongType()), T.StructField("n_onibus", T.LongType()),
])
JANELA_NS = JANELA_MIN * 60 * 10**9


def ratear(pr: pd.DataFrame, tc: pd.DataFrame) -> pd.DataFrame:
    if pr.empty or tc.empty:
        return pd.DataFrame(columns=SCHEMA_VEL.fieldNames())
    tc = tc.sort_values("trecho_seq")
    B = np.r_[tc.d_ini_m.values, tc.d_fim_m.values[-1]]        # n trechos -> n+1 limites
    seq = tc.trecho_seq.values

    a = pr.d_ini_m.values
    b = np.maximum(pr.d_fim_m.values, a)                       # recuo pequeno: distancia 0
    t0 = pr.ta_sp_ini.values.astype("datetime64[ns]").astype("int64")
    dur = pr.dt_s.values.astype(float)

    # trechos que cada par toca: do que contem a ate o que contem b
    k0 = np.clip(np.searchsorted(B, a, side="right") - 1, 0, len(seq) - 1)
    k1 = np.clip(np.searchsorted(B, b, side="left") - 1, 0, len(seq) - 1)
    dentro = (b > B[0]) & (a < B[-1]) | ((a == b) & (a >= B[0]) & (a < B[-1]))
    k0, k1 = np.where(dentro, k0, 0), np.where(dentro, np.maximum(k1, k0), -1)
    n = np.maximum(k1 - k0 + 1, 0)
    i = np.repeat(np.arange(len(pr)), n)                       # indice do par, repetido por trecho
    k = np.concatenate([np.arange(x, y + 1) for x, y in zip(k0, k1) if y >= x]) if n.sum() else np.array([], int)

    lo, hi = np.maximum(a[i], B[k]), np.minimum(b[i], B[k + 1])
    andou = b[i] - a[i]
    parado = andou <= 0
    dist = np.where(parado, 0.0, np.clip(hi - lo, 0, None))
    frac = np.where(parado, 1.0, dist / np.where(parado, 1.0, andou))
    tempo = dur[i] * frac
    # instante medio do pedaco -> janela de 10 min
    meio = np.where(parado, 0.5, ((lo + hi) / 2 - a[i]) / np.where(parado, 1.0, andou))
    janela = ((t0[i] + (meio * dur[i] * 1e9).astype("int64")) // JANELA_NS) * JANELA_NS

    out = pd.DataFrame({"trecho_seq": seq[k].astype("int32"), "janela_sp": janela.astype("datetime64[ns]"),
                        "dist_m": dist, "tempo_s": tempo, "p": pr.p.values[i]})
    out = out[out.tempo_s > 0]
    g = (out.groupby(["trecho_seq", "janela_sp"])
         .agg(dist_m=("dist_m", "sum"), tempo_s=("tempo_s", "sum"),
              n_pares=("p", "size"), n_onibus=("p", "nunique")).reset_index())
    primeira = pr.iloc[0]   # colchetes: primeira.dt seria o acessor de datas do pandas, nao a coluna
    return g.assign(dt=primeira["dt"], versao_gtfs=primeira["versao_gtfs"], shape_id=primeira["shape_id"],
                    tipo_dia=primeira["tipo_dia"])[SCHEMA_VEL.fieldNames()]


ok = spark.table(DESL).filter("situacao = 'ok'")
if DIAS:
    ok = ok.filter(F.col("dt").isin(DIAS))
if LINHAS:
    ok = ok.filter(F.col("route_id").isin(LINHAS))
ok = ok.select("dt", "versao_gtfs", "shape_id", "tipo_dia", "p", "ta_sp_ini", "d_ini_m", "d_fim_m", "dt_s")

grupos = ok.select("dt", "versao_gtfs", "shape_id").distinct()
lim = (tr.select(F.col("versao").alias("versao_gtfs"), "shape_id", "trecho_seq", "d_ini_m", "d_fim_m")
       .join(grupos, ["versao_gtfs", "shape_id"]))

vel = (ok.groupBy("dt", "versao_gtfs", "shape_id")
       .cogroup(lim.groupBy("dt", "versao_gtfs", "shape_id"))
       .applyInPandas(ratear, schema=SCHEMA_VEL)
       .join(tr.select(F.col("versao").alias("versao_gtfs"), "shape_id", "trecho_seq", "route_id", "direction_id",
                       "parada_de", "parada_ate", "comprimento_trecho_m"),
             ["versao_gtfs", "shape_id", "trecho_seq"])
       .withColumn("v_kmh", F.col("dist_m") / F.col("tempo_s") * 3.6)
       .select("dt", "janela_sp", "tipo_dia", "route_id", "direction_id", "shape_id", "versao_gtfs", "trecho_seq",
               "parada_de", "parada_ate", "comprimento_trecho_m", "dist_m", "tempo_s", "v_kmh", "n_pares", "n_onibus"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## B2. Gravar (so quando `linhas` esta vazio)

# COMMAND ----------

if ESCREVER:
    if DIAS and spark.catalog.tableExists(VEL):
        lista = ", ".join(f"'{d}'" for d in DIAS)
        vel.write.mode("overwrite").option("replaceWhere", f"dt IN ({lista})").saveAsTable(VEL)
    else:
        vel.write.mode("overwrite").option("overwriteSchema", True).partitionBy("dt").saveAsTable(VEL)
    vel = spark.table(VEL).filter(F.col("dt").isin(DIAS)) if DIAS else spark.table(VEL)
    print("gravado:", VEL)
else:
    print("modo teste: velocidade_trecho nao gravada")

# COMMAND ----------

# MAGIC %md
# MAGIC ## C. Checagens (falham o run)
# MAGIC
# MAGIC 1. Toda linha tem `tempo_s > 0`, `dist_m >= 0` e velocidade <= 80 km/h (o rateio nao cria velocidade
# MAGIC    maior que a do par, e nenhum par `ok` passa de 80).
# MAGIC 2. **Conservacao:** o tempo rateado nao pode passar do tempo dos pares `ok`. Mostra quanto do tempo e da
# MAGIC    distancia ficou dentro dos trechos (o resto e antes da 1a parada ou depois da ultima).
# MAGIC 3. Quase todo shape com pares `ok` tem trechos.

# COMMAND ----------

problemas = []
ruins = vel.filter((F.col("tempo_s") <= 0) | (F.col("dist_m") < 0) | (F.col("v_kmh") > 80.01)).count()
if ruins:
    problemas.append(f"{ruins} linhas com tempo <= 0, distancia < 0 ou > 80 km/h")

entrada = ok.agg(F.sum("dt_s").alias("t"), F.sum(F.greatest(F.col("d_fim_m") - F.col("d_ini_m"), F.lit(0))).alias("d")).first()
saida = vel.agg(F.sum("tempo_s").alias("t"), F.sum("dist_m").alias("d")).first()
pct_t, pct_d = 100 * saida.t / entrada.t, 100 * saida.d / entrada.d
if saida.t > entrada.t * 1.0001:
    problemas.append(f"tempo rateado ({saida.t:.0f} s) maior que o dos pares ({entrada.t:.0f} s)")

sem = grupos.select("versao_gtfs", "shape_id").distinct().join(
    tr.select(F.col("versao").alias("versao_gtfs"), "shape_id").distinct(), ["versao_gtfs", "shape_id"], "left_anti").count()
tot_shapes = grupos.select("versao_gtfs", "shape_id").distinct().count()
if sem > 0.02 * tot_shapes:
    problemas.append(f"{sem} de {tot_shapes} shapes sem trechos")

assert not problemas, "\n".join(problemas)
print(f"ok: dentro dos trechos ficaram {pct_t:.1f}% do tempo e {pct_d:.1f}% da distancia dos pares ok; "
      f"shapes sem trecho: {sem}/{tot_shapes}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## D. Como ficou (modo teste)
# MAGIC
# MAGIC **Mapa de calor trecho × hora** de um shape: cada coluna e um trecho (na ordem da rota), cada linha uma
# MAGIC janela de 10 min. Faixas escuras horizontais = a linha inteira lenta naquele horario (pico); colunas escuras =
# MAGIC um trecho sempre lento (gargalo fisico). E o formato do resultado que a gold vai cruzar com a chuva.

# COMMAND ----------

if not ESCREVER:
    import matplotlib.pyplot as plt

    alvo = vel.groupBy("route_id", "shape_id").agg(F.sum("n_pares").alias("n")).orderBy(F.desc("n")).first()
    h = vel.filter(F.col("shape_id") == alvo.shape_id).select("janela_sp", "trecho_seq", "v_kmh", "n_pares").toPandas()
    h = h[h.n_pares >= 2]
    mat = h.pivot_table(index="janela_sp", columns="trecho_seq", values="v_kmh")
    fig, ax = plt.subplots(figsize=(15, 8))
    im = ax.imshow(mat.values, aspect="auto", cmap="RdYlGn", vmin=0, vmax=40, interpolation="nearest")
    yt = np.arange(0, len(mat.index), 6)
    ax.set_yticks(yt, [mat.index[j].strftime("%H:%M") for j in yt])
    ax.set_xlabel("trecho (ordem da rota)"); ax.set_ylabel("janela (SP)")
    ax.set_title(f"{alvo.route_id} · shape {alvo.shape_id} · velocidade por trecho (km/h), janelas com ≥ 2 pares")
    fig.colorbar(im, ax=ax, label="km/h")
    plt.show()

    display(vel.groupBy(F.hour("janela_sp").alias("hora_sp"))
            .agg(F.round(F.sum("dist_m") / F.sum("tempo_s") * 3.6, 1).alias("v_kmh"),
                 F.sum("n_pares").alias("pedacos"))
            .orderBy("hora_sp"))

# COMMAND ----------

# MAGIC %run ./metadados

# COMMAND ----------

aplicar_metadados(TRECHOS)
if ESCREVER:
    aplicar_metadados(VEL)
