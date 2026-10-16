# Databricks notebook source
# MAGIC %md
# MAGIC # 04 — Silver: posicao_rota
# MAGIC
# MAGIC **Grao:** o mesmo da `posicao_limpa` — 1 posicao de 1 onibus, chave `(p, ta)`. Nenhuma linha entra
# MAGIC ou sai; so ganham colunas dizendo **onde a posicao esta na rota**:
# MAGIC
# MAGIC | Coluna | O que e |
# MAGIC |---|---|
# MAGIC | `d_m` | metro ao longo do shape, na regua do `shape_dist_traveled` do GTFS (0 = inicio) |
# MAGIC | `erro_lateral_m` | distancia da posicao ate o shape. ~0: a SPTrans ja publica a posicao sobre a rota |
# MAGIC | `n_candidatos` | quantas passagens do shape estavam ali (> 1 = rua percorrida duas vezes) |
# MAGIC | `comprimento_m` | comprimento do shape |
# MAGIC
# MAGIC **Como.** Projecao ortogonal no shape, num plano equirretangular centrado em SP (mesmo metodo da
# MAGIC `silver.py`; erro < 0,1% em 50 km). O metro sai da interpolacao do `shape_dist_traveled` no segmento.
# MAGIC
# MAGIC **O problema: shape que passa duas vezes pela mesma rua.** Medido no GTFS de 12/10:
# MAGIC nas linhas de dois sentidos so 0,7% do tracado e ambiguo (lacos de terminal); nas de **sentido unico**
# MAGIC (circulares) sao **41%**: ida e volta na mesma avenida. Ali, "o ponto mais proximo" escolhe a passagem
# MAGIC errada metade das vezes.
# MAGIC
# MAGIC **A solucao: candidatos + continuidade.** Cada posicao guarda as passagens a ate (melhor erro + 10 m)
# MAGIC e a mais de 150 m entre si ao longo da rota. Para cada onibus, em ordem de `ta`, escolhe-se a sequencia
# MAGIC de candidatos mais coerente (Viterbi): andar para frente a ate 80 km/h custa ~0; recomecar a volta
# MAGIC (do fim para o inicio) custa pouco; recuar ou teleportar custa muito. Mais de 5 min sem posicao quebra
# MAGIC a continuidade.
# MAGIC
# MAGIC **Teste** (08/10, 4 circulares + 2 linhas normais, 93 mil posicoes), % de pares consecutivos incoerentes:
# MAGIC
# MAGIC | | so o mais proximo | com continuidade |
# MAGIC |---|---|---|
# MAGIC | sentido unico | 20,4% | **4,2%** |
# MAGIC | dois sentidos | 2,9% | 2,9% |
# MAGIC
# MAGIC **O que sobra de incoerente nao e projecao** — e do dado, e fica para a `deslocamento`:
# MAGIC 1. **manobra no terminal**: `d` oscila perto de 0 ou do fim;
# MAGIC 2. **sentido atrasado**: o onibus ja voltou, mas a API ainda manda o `sl` antigo → `d` desce por minutos;
# MAGIC 3. **eco**: a API reenvia uma posicao antiga (coordenadas identicas a de 2+ pings antes) com `ta` novo
# MAGIC    — 1,1% das posicoes.

# COMMAND ----------

import math

import numpy as np
from pyspark.sql import Window, functions as F, types as T

spark.conf.set("spark.sql.session.timeZone", "UTC")

LIMPA = "onibus.silver.posicao_limpa"
ROTA = "onibus.silver.posicao_rota"

LAT0, LON0, R_TERRA = -23.55, -46.63, 6_371_000.0
MARGEM_M = 10.0        # candidatos: passagens ate (melhor erro + 10 m)
GAP_M = 150.0          # trechos a mais de 150 m ao longo da rota sao passagens distintas
K_MAX = 6              # no maximo 6 candidatos por posicao
BLOCO = 1000           # posicoes por bloco na matriz posicao x segmento (memoria)
VMAX_MS = 80 / 3.6     # 80 km/h
FOLGA_M = 100.0        # folga para frente
RECUO_M = 30.0         # recuo tolerado
BORDA_M = 300.0        # do fim para o inicio = nova volta no mesmo shape
DT_MAX_S = 300         # acima disso, sem continuidade
P_REINICIO = 50.0
P_INCOERENTE = 1000.0

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Geometria

# COMMAND ----------

def para_xy(lat, lon):
    """Equirretangular local: lat/lon -> metros num plano tangente a SP."""
    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)
    return (np.radians(lon - LON0) * R_TERRA * math.cos(math.radians(LAT0)),
            np.radians(lat - LAT0) * R_TERRA)


def candidatos(sx, sy, sdist, x, y):
    """Para cada posicao, ate K_MAX passagens do shape: (d ao longo, erro lateral), da melhor para a pior."""
    ax, ay = sx[:-1], sy[:-1]
    vx, vy = np.diff(sx), np.diff(sy)
    v2 = vx * vx + vy * vy
    v2[v2 == 0] = 1e-12                      # vertices repetidos (~10% no GTFS) nao quebram a conta
    d0, dlen = sdist[:-1], np.diff(sdist)
    n = len(x)
    C = np.full((n, K_MAX), np.nan)
    E = np.full((n, K_MAX), np.nan)
    for i0 in range(0, n, BLOCO):
        px, py = x[i0:i0 + BLOCO, None], y[i0:i0 + BLOCO, None]
        t = np.clip(((px - ax) * vx + (py - ay) * vy) / v2, 0.0, 1.0)
        d2 = (px - ax - t * vx) ** 2 + (py - ay - t * vy) ** 2
        dal = d0 + t * dlen
        lim = (np.sqrt(d2.min(axis=1)) + MARGEM_M) ** 2
        lin, col = np.nonzero(d2 <= lim[:, None])
        dv, ev = dal[lin, col], np.sqrt(d2[lin, col])
        # agrupa os segmentos proximos de cada posicao em passagens (quebra quando d salta > GAP_M)
        o = np.lexsort((dv, lin))
        lin, dv, ev = lin[o], dv[o], ev[o]
        grupo = np.cumsum(np.r_[True, (lin[1:] != lin[:-1]) | (np.diff(dv) > GAP_M)]) - 1
        # de cada passagem, o segmento de menor erro
        o = np.lexsort((ev, grupo))
        sel = o[np.r_[True, grupo[o][1:] != grupo[o][:-1]]]
        gl, gd, ge = lin[sel], dv[sel], ev[sel]
        # numera as passagens de cada posicao por erro
        o = np.lexsort((ge, gl))
        gl, gd, ge = gl[o], gd[o], ge[o]
        rank = np.arange(len(gl)) - np.searchsorted(gl, gl)
        ok = rank < K_MAX
        C[i0 + gl[ok], rank[ok]] = gd[ok]
        E[i0 + gl[ok], rank[ok]] = ge[ok]
    return C, E


def transicao(dprev, dcur, dt, comprimento):
    """Custo de cada candidato anterior (linhas) para cada atual (colunas)."""
    if dt > DT_MAX_S:
        return np.zeros((len(dprev), len(dcur)))
    a, b = dprev[:, None], dcur[None, :]
    dd = b - a
    ok = (dd >= -RECUO_M) & (dd <= VMAX_MS * dt + FOLGA_M)
    reinicio = (a >= comprimento - BORDA_M) & (b <= BORDA_M)
    custo = np.where(ok, 0.001 * np.abs(dd),
                     np.where(reinicio, P_REINICIO, P_INCOERENTE + np.abs(dd)))
    return np.nan_to_num(custo, nan=np.inf)


def resolver(t, C, E, comprimento):
    """Indice do candidato escolhido para cada posicao de UM onibus (t em segundos, ordenado)."""
    n = len(t)
    escolha = np.zeros(n, dtype=int)
    amb = np.flatnonzero(np.sum(~np.isnan(C), axis=1) > 1)
    if len(amb) == 0:
        return escolha
    # Viterbi so nos trechos ambiguos, ancorado na posicao vizinha de cada lado
    quebra = np.flatnonzero(np.diff(amb) > 1)
    for i0, i1 in zip(np.r_[amb[0], amb[quebra + 1]], np.r_[amb[quebra], amb[-1]]):
        s0, s1 = max(i0 - 1, 0), min(i1 + 1, n - 1)
        custo = np.nan_to_num(E[s0], nan=np.inf)
        volta = []
        for j in range(s0 + 1, s1 + 1):
            tot = custo[:, None] + transicao(C[j - 1], C[j], t[j] - t[j - 1], comprimento)
            volta.append(np.argmin(tot, axis=0))
            custo = tot[volta[-1], np.arange(tot.shape[1])] + np.nan_to_num(E[j], nan=np.inf)
        k = int(np.argmin(custo))
        for j in range(s1, s0, -1):
            if i0 <= j <= i1:
                escolha[j] = k
            k = int(volta[j - s0 - 1][k])
        if i0 <= s0 <= i1:
            escolha[s0] = k
    return escolha

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Um grupo = um shape num dia
# MAGIC
# MAGIC `cogroup` junta, para cada `(versao_gtfs, shape_id, dt)`, as posicoes e os pontos do shape. Os pontos
# MAGIC do shape sao repetidos para cada dia em que ele aparece (~50 M linhas pequenas) — mais simples que
# MAGIC mandar todos os shapes para todos os workers, e o grupo fica limitado a um dia (< ~60 mil posicoes).

# COMMAND ----------

NOVAS = [T.StructField("d_m", T.DoubleType()),
         T.StructField("erro_lateral_m", T.DoubleType()),
         T.StructField("n_candidatos", T.IntegerType()),
         T.StructField("comprimento_m", T.DoubleType())]
SCHEMA = T.StructType(spark.table(LIMPA).schema.fields + NOVAS)
COLUNAS = SCHEMA.fieldNames()


def projetar(pos, shp):
    if pos.empty:
        return pos.reindex(columns=COLUNAS)
    assert not shp.empty, f"shape sem pontos: {pos.shape_id.iloc[0]}"
    shp = shp.sort_values("shape_pt_sequence")
    sx, sy = para_xy(shp.shape_pt_lat.values, shp.shape_pt_lon.values)
    sd = shp.shape_dist_traveled.values.astype(float)

    pos = pos.sort_values(["p", "ta"]).reset_index(drop=True)
    x, y = para_xy(pos.py.values, pos.px.values)
    C, E = candidatos(sx, sy, sd, x, y)

    t = pos.ta.values.astype("datetime64[s]").astype("int64")
    p = pos.p.values
    k = np.zeros(len(pos), dtype=int)
    lim = np.flatnonzero(np.r_[True, p[1:] != p[:-1], True])
    for a, b in zip(lim[:-1], lim[1:]):
        k[a:b] = resolver(t[a:b], C[a:b], E[a:b], sd[-1])

    i = np.arange(len(pos))
    return pos.assign(d_m=C[i, k], erro_lateral_m=E[i, k],
                      n_candidatos=np.sum(~np.isnan(C), axis=1).astype("int32"),
                      comprimento_m=float(sd[-1]))[COLUNAS]


pos = spark.table(LIMPA)
grupos = pos.select("versao_gtfs", "shape_id", "dt").distinct()
pontos = (spark.table("onibus.silver.gtfs_shapes")
          .select(F.col("versao").alias("versao_gtfs"), "shape_id", "shape_pt_sequence",
                  "shape_pt_lat", "shape_pt_lon", "shape_dist_traveled")
          .join(grupos, ["versao_gtfs", "shape_id"]))

rota = (pos.groupBy("versao_gtfs", "shape_id", "dt")
        .cogroup(pontos.groupBy("versao_gtfs", "shape_id", "dt"))
        .applyInPandas(projetar, schema=SCHEMA))

(rota.write.mode("overwrite").option("overwriteSchema", True)
     .partitionBy("dt").saveAsTable(ROTA))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Checagens (falham o run)
# MAGIC
# MAGIC 1. Por dia: `posicao_rota = posicao_limpa` (nada entra, nada sai).
# MAGIC 2. Todo `d_m` preenchido e dentro do shape (0 ≤ `d_m` ≤ `comprimento_m`).

# COMMAND ----------

por_dia = lambda t, nome: spark.table(t).groupBy("dt").agg(F.count("*").alias(nome))
checagem = (por_dia(LIMPA, "limpa").join(por_dia(ROTA, "rota"), "dt", "full").fillna(0)
            .withColumn("dif", F.col("rota") - F.col("limpa")).orderBy("dt"))
problemas = [f"{r.dt}: dif {r.dif:+}" for r in checagem.filter("dif != 0").collect()]
fora = spark.table(ROTA).filter(F.col("d_m").isNull() | (F.col("d_m") < 0)
                                | (F.col("d_m") > F.col("comprimento_m") + 1)).count()
if fora:
    problemas.append(f"{fora} posicoes sem d_m ou fora do shape")
assert not problemas, "\n".join(problemas)
print(f"ok: {checagem.count()} dias, rota = limpa; d_m sempre dentro do shape")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3b. Metadados
# MAGIC
# MAGIC O `overwrite` com `overwriteSchema` apaga os comentarios das colunas; reaplica a partir de `metadados`.

# COMMAND ----------

# MAGIC %run ./metadados

# COMMAND ----------

aplicar_metadados(ROTA)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Relatorio
# MAGIC
# MAGIC **Erro lateral por dia.** No shape certo ele e ~0. Se subir antes de 12/10, o tracado mudou antes
# MAGIC do download e a versao de 26/08 ja estava velha naqueles dias.

# COMMAND ----------

display(spark.table(ROTA).groupBy("dt", "versao_gtfs").agg(
            F.count("*").alias("posicoes"),
            F.round(F.percentile_approx("erro_lateral_m", 0.99), 2).alias("erro_p99_m"),
            F.round(100 * F.avg((F.col("erro_lateral_m") > 10).cast("double")), 3).alias("pct_erro_10m"),
            F.round(100 * F.avg((F.col("n_candidatos") > 1).cast("double")), 2).alias("pct_ambiguas"))
        .orderBy("dt"))

# COMMAND ----------

# MAGIC %md
# MAGIC **Coerencia** nos ultimos 3 dias: pares consecutivos do mesmo onibus no mesmo shape (0 < Δt ≤ 5 min).
# MAGIC `recuo` = `d` desce mais de 30 m sem ser nova volta; `rapido` = mais de 80 km/h.

# COMMAND ----------

ultimos = [r.dt for r in spark.table(ROTA).select("dt").distinct().orderBy(F.desc("dt")).limit(3).collect()]
w = Window.partitionBy("p").orderBy("ta")
pares = (spark.table(ROTA).filter(F.col("dt").isin(ultimos))
         .withColumn("d_ant", F.lag("d_m").over(w))
         .withColumn("dt_s", F.col("ta").cast("long") - F.lag("ta").over(w).cast("long"))
         .withColumn("mesmo_shape", F.lag("shape_id").over(w) == F.col("shape_id"))
         .filter(F.col("mesmo_shape") & F.col("dt_s").between(1, DT_MAX_S))
         .withColumn("dd", F.col("d_m") - F.col("d_ant"))
         .withColumn("reinicio", (F.col("d_ant") >= F.col("comprimento_m") - BORDA_M) & (F.col("d_m") <= BORDA_M)))
display(pares.groupBy("sentido_unico").agg(
            F.count("*").alias("pares"),
            F.round(100 * F.avg(((F.col("dd") < -RECUO_M) & ~F.col("reinicio")).cast("double")), 2).alias("pct_recuo"),
            F.round(100 * F.avg((F.col("dd") > VMAX_MS * F.col("dt_s") + FOLGA_M).cast("double")), 2).alias("pct_rapido"),
            F.round(100 * F.avg(F.col("reinicio").cast("double")), 2).alias("pct_reinicio")))
