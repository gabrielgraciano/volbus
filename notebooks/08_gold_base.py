# Databricks notebook source
# MAGIC %md
# MAGIC # 08 — Gold: base (trechos, postos, chuva por posto, eventos)
# MAGIC
# MAGIC Desenho completo: `docs/gold_desenho.md`. Este notebook prepara as peças que os proximos usam:
# MAGIC
# MAGIC | Tabela | Grao | O que e |
# MAGIC |---|---|---|
# MAGIC | `gold.trecho` | trecho fisico | par de paradas consecutivas, juntando as linhas: coordenadas, comprimento, marcas de trecho atipico, quais postos de chuva usa |
# MAGIC | `gold.trecho_posto` | trecho × posto | ate 3 postos de cada trecho, com distancia e peso |
# MAGIC | `gold.chuva_posto_10min` | posto × slot | chuva e variaveis derivadas: intensidade em 30 e 60 min, acumulado de 3 h, seco ou nao, tempo desde o fim da chuva |
# MAGIC | `gold.evento_chuva` | evento | inicio, fim, duracao, total e pico de cada evento de chuva por posto |
# MAGIC
# MAGIC **Trecho fisico** = `(parada_de, parada_ate)`, sem olhar a linha. Paradas sao cadastradas por lado da rua, entao o
# MAGIC trecho tem sentido. Junta as linhas que usam a mesma rua e e a unidade natural para a infraestrutura (KR4).
# MAGIC
# MAGIC **Postos de cada trecho.** Ate 3 postos DAEE confiaveis a ate 5 km do ponto medio, com peso 1/d². Se nao houver DAEE
# MAGIC a 5 km, o posto confiavel mais proximo de outra rede a ate 5 km. Por que (exploracao de 25/10):
# MAGIC - a correlacao da chuva a 10 min entre postos DAEE e 0,89 ate 2 km, 0,72 em 3–5 km e 0,52 em 8–12 km;
# MAGIC - a rede CEMADEN so entra como reserva: quando volta a chover depois de uma hora seca, a 1a leitura cobre a hora
# MAGIC   inteira e a silver reparte essa chuva em 6 slots, ate 50 min antes de ela comecar. O tempo dela nao e confiavel.
# MAGIC
# MAGIC **Evento de chuva (por posto).** Comeca no 1o slot com ≥ 0,2 mm (resolucao do pluviometro de bascula) e termina no
# MAGIC ultimo slot com chuva antes de **≥ 60 min secos**. O periodo seco minimo muda muito a contagem (por posto DAEE:
# MAGIC 147 eventos com 30 min, 105 com 60, 72 com 120), entao e parametro.
# MAGIC
# MAGIC **Seco estrito** (define a linha de base no notebook 09): nenhuma chuva no posto nas 3 h anteriores, com as 18
# MAGIC leituras validas, e menos de 25% dos postos DAEE da cidade chovendo no slot (o congestionamento se espalha:
# MAGIC com ≥ 25% da cidade chovendo, trechos secos ficam 3–4% mais lentos fora do pico da manha).
# MAGIC
# MAGIC **Quando rodar:** a mao, depois de cada novo download da chuva (notebook 07). Fica fora do job diario.

# COMMAND ----------

import numpy as np
import pandas as pd
from pyspark.sql import functions as F

spark.conf.set("spark.sql.session.timeZone", "UTC")

VEL = "onibus.silver.velocidade_trecho"
STOPS = "onibus.silver.gtfs_stops"
POSTOS = "onibus.silver.postos"
CHUVA = "onibus.silver.chuva_10min"

TRECHO = "onibus.gold.trecho"
TRECHO_POSTO = "onibus.gold.trecho_posto"
CHUVA_POSTO = "onibus.gold.chuva_posto_10min"
EVENTO = "onibus.gold.evento_chuva"

RAIO_KM = 5.0          # alem disso a chuva do posto ja nao representa o trecho
K_POSTOS = 3
DIST_MIN_KM = 0.1      # piso da distancia no peso 1/d²: posto colado no trecho nao vira peso infinito
LIMIAR_MM = 0.2        # resolucao do pluviometro: chove = slot com pelo menos isso
MIT_MIN = 60           # periodo seco minimo entre eventos (minimum inter-event time)
FRAC_CIDADE_MAX = 0.25 # acima disso, a chuva no resto da cidade contamina o "seco"
SLOTS_30, SLOTS_60, SLOTS_3H = 3, 6, 18

# Trecho atipico: fica nas tabelas, mas marcado. Fora do ranking (KR3). ~4% dos trechos, ~2% das horas-onibus.
COMP_MIN_M, COMP_MAX_M = 30, 3000      # curtos demais (projecao) ou longos demais para serem "um trecho"
SINUOSIDADE_MIN, SINUOSIDADE_MAX = 0.5, 3  # comprimento na rota / distancia em linha reta entre as paradas

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Trechos fisicos
# MAGIC
# MAGIC Tudo que aparece na `velocidade_trecho`, com as coordenadas das duas paradas (versao mais recente do GTFS em que a
# MAGIC parada existe). **Sinuosidade** = comprimento na rota ÷ distancia em linha reta entre as paradas: ~1 numa rua
# MAGIC reta. Muito acima de 1 e laco ou erro de projecao (ha trecho de 32 km com as paradas a 175 m); abaixo de 1 e
# MAGIC impossivel na pratica (o trecho e mais curto que a reta) e tambem indica projecao ruim.

# COMMAND ----------

SQL_TRECHO_BASE = f"""
WITH st AS (SELECT stop_id, stop_name, stop_lat, stop_lon FROM {STOPS}
            QUALIFY row_number() OVER (PARTITION BY stop_id ORDER BY versao DESC) = 1),
     v AS (SELECT parada_de, parada_ate,
                  percentile_approx(comprimento_trecho_m, 0.5) AS comprimento_m,
                  count(DISTINCT route_id) AS n_linhas,
                  concat_ws(',', sort_array(collect_set(route_id))) AS linhas,
                  sum(tempo_s) / 3600 AS horas_onibus,
                  sum(dist_m) / sum(tempo_s) * 3.6 AS v_kmh_media
           FROM {VEL} GROUP BY 1, 2)
SELECT concat(v.parada_de, '>', v.parada_ate) AS trecho_id, v.*,
       a.stop_name AS nome_de, b.stop_name AS nome_ate,
       a.stop_lat AS lat_de, a.stop_lon AS lon_de, b.stop_lat AS lat_ate, b.stop_lon AS lon_ate
FROM v LEFT JOIN st a ON a.stop_id = v.parada_de LEFT JOIN st b ON b.stop_id = v.parada_ate
"""

SQL_POSTOS = f"SELECT prefixo, rede, lat, lon FROM {POSTOS} WHERE status = 'ok' AND duplicata_de IS NULL"


def dist_km(lat1, lon1, lat2, lon2):
    """Haversine vetorizada, em km."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371 * np.arcsin(np.sqrt(a))


def preparar_trechos(tr: pd.DataFrame) -> pd.DataFrame:
    """Ponto medio, distancia em linha reta, sinuosidade e marca de trecho atipico."""
    tr = tr.copy()
    tr["lat"] = (tr.lat_de + tr.lat_ate) / 2
    tr["lon"] = (tr.lon_de + tr.lon_ate) / 2
    tr["dist_reta_m"] = 1000 * dist_km(tr.lat_de, tr.lon_de, tr.lat_ate, tr.lon_ate)
    tr["sinuosidade"] = tr.comprimento_m / tr.dist_reta_m.clip(lower=1.0)
    tr["f_atipico"] = ((tr.comprimento_m < COMP_MIN_M) | (tr.comprimento_m > COMP_MAX_M)
                       | (tr.sinuosidade < SINUOSIDADE_MIN) | (tr.sinuosidade > SINUOSIDADE_MAX))
    return tr


def atribuir_postos(tr: pd.DataFrame, po: pd.DataFrame) -> pd.DataFrame:
    """Para cada trecho: ate K_POSTOS DAEE a <= RAIO_KM (peso 1/d²); senao, o mais proximo de outra rede a <= RAIO_KM."""
    D = dist_km(tr.lat.values[:, None], tr.lon.values[:, None], po.lat.values[None, :], po.lon.values[None, :])
    daee = po.rede.values == "daee"
    linhas = []
    for i, tid in enumerate(tr.trecho_id.values):
        d = D[i]
        idx = np.flatnonzero(daee & (d <= RAIO_KM))
        fonte = "daee"
        if len(idx):
            idx = idx[np.argsort(d[idx])[:K_POSTOS]]
        else:
            idx = np.flatnonzero(d <= RAIO_KM)
            idx = idx[np.argsort(d[idx])[:1]]
            fonte = "outra_rede"
        if not len(idx):
            continue
        w = 1 / np.maximum(d[idx], DIST_MIN_KM) ** 2
        w = w / w.sum()
        for ordem, (j, peso) in enumerate(zip(idx, w), start=1):
            linhas.append((tid, po.prefixo.values[j], po.rede.values[j], fonte, ordem, float(d[j]), float(peso)))
    return pd.DataFrame(linhas, columns=["trecho_id", "prefixo", "rede", "fonte_chuva", "ordem", "dist_km", "peso"])


tr = preparar_trechos(spark.sql(SQL_TRECHO_BASE).toPandas())
po = spark.sql(SQL_POSTOS).toPandas()
tp = atribuir_postos(tr, po)

resumo = tp.groupby("trecho_id").agg(fonte_chuva=("fonte_chuva", "first"), n_postos=("prefixo", "size"),
                                     dist_posto_km=("dist_km", "min"))
tr = tr.join(resumo, on="trecho_id")
tr["fonte_chuva"] = tr.fonte_chuva.fillna("sem_posto")
tr["n_postos"] = tr.n_postos.fillna(0).astype(int)

colunas = ["trecho_id", "parada_de", "parada_ate", "nome_de", "nome_ate", "lat_de", "lon_de", "lat_ate", "lon_ate",
           "lat", "lon", "comprimento_m", "dist_reta_m", "sinuosidade", "f_atipico", "n_linhas", "linhas",
           "horas_onibus", "v_kmh_media", "fonte_chuva", "n_postos", "dist_posto_km"]
(spark.createDataFrame(tr[colunas]).write.mode("overwrite").option("overwriteSchema", True).saveAsTable(TRECHO))
(spark.createDataFrame(tp).write.mode("overwrite").option("overwriteSchema", True).saveAsTable(TRECHO_POSTO))
print(f"{len(tr):,} trechos; {len(tp):,} ligacoes trecho-posto; {int(tr.f_atipico.sum()):,} trechos atipicos")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Chuva por posto: janelas moveis
# MAGIC
# MAGIC So postos `ok` sem duplicata (94). Para cada slot, olhando para tras: mm nos ultimos 30 min, 60 min e 3 h. As
# MAGIC intensidades (`mm_h_30`, `mm_h_60`) ficam nulas se faltar alguma leitura na janela: nulo e "nao sei", nunca 0.
# MAGIC Os slots vem da silver, um por posto a cada 10 min, sem buraco; por isso a janela movel conta linhas.

# COMMAND ----------

SQL_BASE = f"""
SELECT c.prefixo, p.rede, c.slot_utc, c.slot_sp, c.dt, c.mm, c.resolucao_min,
       c.f_faltante, c.f_negativo, c.f_intervalo_longo, c.f_pico_implausivel,
       coalesce(c.mm, 0) >= {LIMIAR_MM} AS chove
FROM {CHUVA} c JOIN {POSTOS} p USING (prefixo)
WHERE p.status = 'ok' AND p.duplicata_de IS NULL
"""

SQL_ROLL = f"""
SELECT b.*,
       sum(mm) OVER w30 AS s30, count(mm) OVER w30 AS n30,
       sum(mm) OVER w60 AS s60, count(mm) OVER w60 AS n60,
       sum(mm) OVER w3h AS s3h, count(mm) OVER w3h AS n3h,
       sum(CAST(chove AS INT)) OVER w3h AS chuvas_3h
FROM chuva_base b
WINDOW w30 AS (PARTITION BY prefixo ORDER BY slot_utc ROWS BETWEEN {SLOTS_30 - 1} PRECEDING AND CURRENT ROW),
       w60 AS (PARTITION BY prefixo ORDER BY slot_utc ROWS BETWEEN {SLOTS_60 - 1} PRECEDING AND CURRENT ROW),
       w3h AS (PARTITION BY prefixo ORDER BY slot_utc ROWS BETWEEN {SLOTS_3H - 1} PRECEDING AND CURRENT ROW)
"""

SQL_CIDADE = f"""
SELECT slot_utc, avg(CAST(chove AS DOUBLE)) AS frac_cidade_chuva
FROM chuva_base WHERE rede = 'daee' AND mm IS NOT NULL GROUP BY slot_utc
"""

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Eventos de chuva
# MAGIC
# MAGIC Entre os slots com chuva de cada posto, um evento novo comeca quando o slot anterior com chuva esta a mais de
# MAGIC `MIT_MIN` min. `sum(...) OVER` numera os eventos. `fim_utc` e o **fim** do ultimo slot com chuva. Slots secos dentro
# MAGIC do evento contam na duracao. `tempo_confiavel` = so a rede DAEE (CEMADEN e INMET tem resolucao horaria quando seco).
# MAGIC `seco_antes_min` e `seco_depois_min` dizem quanto seco ha em volta, para escolher eventos isolados no estudo de evento (KR2).

# COMMAND ----------

SQL_SLOTS_EVENTO = f"""
WITH r AS (SELECT prefixo, rede, slot_utc, lag(slot_utc) OVER (PARTITION BY prefixo ORDER BY slot_utc) AS ant
           FROM chuva_base WHERE chove)
SELECT prefixo, rede, slot_utc,
       sum(CASE WHEN ant IS NULL OR unix_timestamp(slot_utc) - unix_timestamp(ant) > {MIT_MIN} * 60 THEN 1 ELSE 0 END)
         OVER (PARTITION BY prefixo ORDER BY slot_utc) AS seq
FROM r
"""

SQL_EVENTO = """
WITH e AS (SELECT prefixo, rede, seq, min(slot_utc) AS inicio_utc, max(slot_utc) + INTERVAL 10 MINUTES AS fim_utc,
                  count(*) AS slots_chuva
           FROM slots_evento GROUP BY 1, 2, 3),
     m AS (SELECT e.prefixo, e.seq, sum(r.mm) AS mm_total, count(*) AS slots, count(r.mm) AS slots_validos,
                  max(r.mm) * 6 AS pico_mm_h_10, max(CASE WHEN r.n30 = 3 THEN r.s30 * 2 END) AS pico_mm_h_30
           FROM e JOIN chuva_roll r ON r.prefixo = e.prefixo AND r.slot_utc >= e.inicio_utc AND r.slot_utc < e.fim_utc
           GROUP BY 1, 2)
SELECT concat(e.prefixo, '-', lpad(CAST(e.seq AS STRING), 4, '0')) AS evento_id,
       e.prefixo, e.rede, e.rede = 'daee' AS tempo_confiavel, e.seq,
       e.inicio_utc, e.fim_utc,
       from_utc_timestamp(e.inicio_utc, 'America/Sao_Paulo') AS inicio_sp,
       from_utc_timestamp(e.fim_utc, 'America/Sao_Paulo') AS fim_sp,
       (unix_timestamp(e.fim_utc) - unix_timestamp(e.inicio_utc)) / 60 AS duracao_min,
       m.mm_total, m.mm_total >= 1 AS relevante, m.pico_mm_h_10, m.pico_mm_h_30,
       e.slots_chuva, m.slots, m.slots_validos,
       lead(e.inicio_utc) OVER (PARTITION BY e.prefixo ORDER BY e.seq) AS proximo_inicio_utc,
       (unix_timestamp(e.inicio_utc) - unix_timestamp(lag(e.fim_utc) OVER (PARTITION BY e.prefixo ORDER BY e.seq))) / 60 AS seco_antes_min,
       (unix_timestamp(lead(e.inicio_utc) OVER (PARTITION BY e.prefixo ORDER BY e.seq)) - unix_timestamp(e.fim_utc)) / 60 AS seco_depois_min
FROM e JOIN m USING (prefixo, seq)
"""

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Tabela final por posto × slot
# MAGIC
# MAGIC Cada slot herda o evento mais recente que ja comecou (`last_value`): esta dentro dele (`em_evento`) ou depois dele
# MAGIC (`min_desde_fim`, 0 = o slot logo apos o fim). `min_ate_proximo` = minutos ate o proximo evento comecar, usado no
# MAGIC teste de antecipacao.

# COMMAND ----------

SQL_FINAL = f"""
WITH marc AS (SELECT r.*, e.seq AS seq_inicio FROM chuva_roll r
              LEFT JOIN evento_v e ON e.prefixo = r.prefixo AND e.inicio_utc = r.slot_utc),
     atual AS (SELECT *, last_value(seq_inicio, true) OVER (PARTITION BY prefixo ORDER BY slot_utc
                         ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS seq FROM marc)
SELECT a.prefixo, a.rede, a.slot_utc, a.slot_sp, a.dt, a.mm, a.resolucao_min,
       a.f_faltante, a.f_negativo, a.f_intervalo_longo, a.f_pico_implausivel, a.chove,
       CASE WHEN a.n30 = {SLOTS_30} THEN a.s30 * 2 END AS mm_h_30,
       CASE WHEN a.n60 = {SLOTS_60} THEN a.s60 END AS mm_h_60,
       CASE WHEN a.n3h = {SLOTS_3H} THEN a.s3h END AS mm_3h,
       a.n3h = {SLOTS_3H} AND a.chuvas_3h = 0 AS seco_3h,
       c.frac_cidade_chuva,
       a.n3h = {SLOTS_3H} AND a.chuvas_3h = 0 AND coalesce(c.frac_cidade_chuva, 0) < {FRAC_CIDADE_MAX} AS seco_estrito,
       e.evento_id,
       coalesce(a.slot_utc < e.fim_utc, false) AS em_evento,
       CASE WHEN a.slot_utc >= e.fim_utc THEN (unix_timestamp(a.slot_utc) - unix_timestamp(e.fim_utc)) / 60 END AS min_desde_fim,
       (unix_timestamp(e.proximo_inicio_utc) - unix_timestamp(a.slot_utc)) / 60 AS min_ate_proximo
FROM atual a
LEFT JOIN cidade c ON c.slot_utc = a.slot_utc
LEFT JOIN evento_v e ON e.prefixo = a.prefixo AND e.seq = a.seq
"""

spark.sql(SQL_BASE).createOrReplaceTempView("chuva_base")
spark.sql(SQL_ROLL).createOrReplaceTempView("chuva_roll")
spark.sql(SQL_CIDADE).createOrReplaceTempView("cidade")
spark.sql(SQL_SLOTS_EVENTO).createOrReplaceTempView("slots_evento")
spark.sql(SQL_EVENTO).createOrReplaceTempView("evento_v")

spark.sql("SELECT * FROM evento_v").write.mode("overwrite").option("overwriteSchema", True).saveAsTable(EVENTO)
(spark.sql(SQL_FINAL).write.mode("overwrite").option("overwriteSchema", True)
      .partitionBy("dt").saveAsTable(CHUVA_POSTO))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Checagens (falham o run)
# MAGIC
# MAGIC **Trechos:** 1 linha por `trecho_id`; todo trecho da `velocidade_trecho` presente; todos com coordenadas.
# MAGIC **Postos:** pesos somam 1 por trecho; no maximo 3 postos, todos a ate 5 km.
# MAGIC **Chuva:** `(prefixo, slot_utc)` unico; mesma quantidade de linhas e mesma chuva da silver, posto a posto.
# MAGIC **Eventos:** todo slot com chuva esta dentro de um evento; eventos do mesmo posto nao se sobrepoem e ficam a pelo
# MAGIC menos `MIT_MIN` min um do outro; `seco_estrito` nunca e verdadeiro com chuva nas 3 h.

# COMMAND ----------

problemas = []
t, l, c, e = spark.table(TRECHO), spark.table(TRECHO_POSTO), spark.table(CHUVA_POSTO), spark.table(EVENTO)

if t.groupBy("trecho_id").count().filter("count > 1").count():
    problemas.append("trecho_id repetido")
faltam = (spark.table(VEL).select("parada_de", "parada_ate").distinct()
          .join(t.select("parada_de", "parada_ate"), ["parada_de", "parada_ate"], "left_anti").count())
if faltam:
    problemas.append(f"{faltam} trechos da velocidade_trecho fora da gold.trecho")
if t.filter("lat IS NULL OR lon IS NULL").count():
    problemas.append("trecho sem coordenada")

pesos = l.groupBy("trecho_id").agg(F.sum("peso").alias("s"), F.count("*").alias("n"), F.max("dist_km").alias("d"))
if pesos.filter(f"abs(s - 1) > 1e-6 OR n > {K_POSTOS} OR d > {RAIO_KM}").count():
    problemas.append("pesos que nao somam 1, ou mais de 3 postos, ou posto alem do raio")

if c.groupBy("prefixo", "slot_utc").count().filter("count > 1").count():
    problemas.append("(prefixo, slot_utc) repetido")
orig = (spark.table(CHUVA).join(spark.table(POSTOS).filter("status = 'ok' AND duplicata_de IS NULL").select("prefixo"), "prefixo")
        .groupBy("prefixo").agg(F.count("*").alias("n0"), F.sum("mm").alias("mm0")))
dif = (orig.join(c.groupBy("prefixo").agg(F.count("*").alias("n1"), F.sum("mm").alias("mm1")), "prefixo", "full")
       .filter("n0 IS NULL OR n1 IS NULL OR n0 != n1 OR abs(mm0 - mm1) > 0.01"))
if dif.count():
    problemas.append(f"{dif.count()} postos com linhas ou chuva diferentes da silver")

if c.filter("chove AND NOT em_evento").count():
    problemas.append("slot com chuva fora de evento")
if e.filter(f"seco_depois_min < {MIT_MIN}").count():
    problemas.append("eventos do mesmo posto a menos de MIT_MIN min")
if c.filter("seco_estrito AND NOT seco_3h").count():
    problemas.append("seco_estrito sem seco_3h")

assert not problemas, "\n".join(problemas)
print(f"ok: {t.count():,} trechos, {l.count():,} ligacoes, {c.count():,} slots, {e.count():,} eventos")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Relatorio
# MAGIC
# MAGIC **Cobertura de chuva dos trechos.** Esperado: ~96% com DAEE, ~2,5% com outra rede, ~2% sem posto.

# COMMAND ----------

display(t.groupBy("fonte_chuva", "n_postos").agg(
            F.count("*").alias("trechos"),
            F.round(F.sum("horas_onibus")).alias("horas_onibus"),
            F.round(F.percentile_approx("dist_posto_km", 0.5), 2).alias("dist_mediana_km"),
            F.sum(F.col("f_atipico").cast("int")).alias("atipicos"))
        .orderBy("fonte_chuva", "n_postos"))

# COMMAND ----------

# MAGIC %md
# MAGIC **Eventos por rede.** Esperado na DAEE: ~105 eventos por posto em 86 dias, duracao mediana ~40 min, ~50% com ≥ 1 mm.

# COMMAND ----------

display(e.groupBy("rede").agg(
            F.count("*").alias("eventos"),
            F.countDistinct("prefixo").alias("postos"),
            F.round(F.percentile_approx("duracao_min", 0.5)).alias("duracao_mediana_min"),
            F.round(F.percentile_approx("mm_total", 0.5), 1).alias("mm_mediano"),
            F.round(100 * F.avg(F.col("relevante").cast("double")), 1).alias("pct_ge_1mm"),
            F.round(F.max("pico_mm_h_30"), 1).alias("pico_max_mm_h_30"))
        .orderBy("rede"))

# COMMAND ----------

# MAGIC %md
# MAGIC **Quanto do tempo e seco?** Fracao dos slots DAEE em cada situacao, desde 25/08 (periodo com onibus).

# COMMAND ----------

display(c.filter("rede = 'daee' AND dt >= '2026-08-25'").agg(
            F.round(100 * F.avg(F.col("chove").cast("double")), 2).alias("pct_slots_chovendo"),
            F.round(100 * F.avg(F.col("em_evento").cast("double")), 2).alias("pct_em_evento"),
            F.round(100 * F.avg(F.col("seco_3h").cast("double")), 2).alias("pct_seco_3h"),
            F.round(100 * F.avg(F.col("seco_estrito").cast("double")), 2).alias("pct_seco_estrito")))

# COMMAND ----------

# MAGIC %run ./metadados

# COMMAND ----------

aplicar_objetos()
for tabela in [TRECHO, TRECHO_POSTO, CHUVA_POSTO, EVENTO]:
    aplicar_metadados(tabela)
