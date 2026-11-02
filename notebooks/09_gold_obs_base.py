# Databricks notebook source
# MAGIC %md
# MAGIC # 09 — Gold: observacoes por trecho e linha de base
# MAGIC
# MAGIC Junta os dois lados do projeto: para cada **trecho fisico × janela de 10 min**, a velocidade dos onibus, a chuva nos
# MAGIC postos do trecho e **quanto a velocidade difere do normal**. Desenho: `docs/gold_desenho.md`, secoes 2.2 e 2.4.
# MAGIC
# MAGIC | Saida | Grao | O que e |
# MAGIC |---|---|---|
# MAGIC | `gold.obs_trecho_10min` | trecho × janela | distancia, tempo, chuva do trecho, classe de chuva |
# MAGIC | `gold.linha_base` | trecho × hora × grupo de dia | velocidade normal do trecho em periodo seco |
# MAGIC | `gold.ajuste_dia_hora` | grupo × dia da semana × hora | fator de dia da semana, estimado na cidade |
# MAGIC | `gold.ajuste_semana` | semana | fator da semana, estimado na cidade |
# MAGIC | `gold.obs_razao` (view) | trecho × janela | observacoes + velocidade esperada + razao |
# MAGIC
# MAGIC **Chuva do trecho.** Media dos postos do trecho com peso 1/d² (so os postos com leitura naquele slot). O trecho so e
# MAGIC seco se **todos** os seus postos estiverem secos.
# MAGIC
# MAGIC **Classe de chuva** (intensidade `mm_h_30`, nos ultimos 30 min; primeira que se aplica):
# MAGIC
# MAGIC | Classe | Regra |
# MAGIC |---|---|
# MAGIC | `sem_dado` | menos de metade do peso dos postos com leitura, ou nao da para saber se esta seco |
# MAGIC | `seco` | todos os postos em seco estrito (3 h sem chuva e cidade predominantemente seca) |
# MAGIC | `transbordamento` | postos secos ha 3 h, mas ≥ 25% da cidade chovendo agora |
# MAGIC | `pos_chuva` | sem chuva nos ultimos 30 min, mas choveu nas ultimas 3 h |
# MAGIC | `traco` | < 0,4 mm/h: menos que uma batida do pluviometro em 30 min; em geral um posto distante do trecho |
# MAGIC | `fraca` / `moderada` / `forte` / `muito_forte` | 0,4–2,5 / 2,5–10 / 10–25 / ≥ 25 mm/h |
# MAGIC
# MAGIC **Linha de base** = `v_base(trecho, grupo de dia, hora) × fator(grupo, dia da semana, hora) × fator(semana)`:
# MAGIC - `v_base`: Σ distancia ÷ Σ tempo nas janelas `seco` daquele trecho, hora e grupo (`util`, `sabado`, `domingo_feriado`);
# MAGIC - os fatores sao estimados **na cidade**, nas janelas secas. Separar assim evita estimar trecho × hora × dia da semana ×
# MAGIC   semana direto, o que deixaria celulas quase vazias. Motivo dos fatores: segunda e ~3–4% mais rapida, sexta mais lenta,
# MAGIC   e a semana varia de 0,985 a 1,015.
# MAGIC
# MAGIC **Razao** = distancia ÷ (tempo × velocidade esperada): 1 = normal; 0,90 = 10% mais lento que o normal. Para agregar,
# MAGIC sempre `sum(dist_m) / sum(dist_esperada_m)`, nunca a media das razoes: janela com um onibus nao pesa igual a janela com dez.
# MAGIC
# MAGIC **Quando rodar:** a mao, depois do notebook 08, quando houver chuva nova. Fora do job diario.

# COMMAND ----------

from pyspark.sql import functions as F

spark.conf.set("spark.sql.session.timeZone", "UTC")

VEL = "onibus.silver.velocidade_trecho"
LIMPA = "onibus.silver.posicao_limpa"
TRECHO = "onibus.gold.trecho"
TRECHO_POSTO = "onibus.gold.trecho_posto"
CHUVA_POSTO = "onibus.gold.chuva_posto_10min"
EVENTO = "onibus.gold.evento_chuva"

OBS = "onibus.gold.obs_trecho_10min"
LINHA_BASE = "onibus.gold.linha_base"
AJUSTE_DIA_HORA = "onibus.gold.ajuste_dia_hora"
AJUSTE_SEMANA = "onibus.gold.ajuste_semana"
RAZAO = "onibus.gold.obs_razao"

INICIO = "2026-08-25"       # 1o dia com onibus
TRACO_MM_H = 0.4            # 0,2 mm (uma batida do pluviometro) em 30 min = 0,4 mm/h
FRACA, MODERADA, FORTE = 2.5, 10.0, 25.0
PESO_MIN = 0.5              # abaixo disso, a chuva do trecho vem de postos que pesam pouco
MIN_JANELAS_UTIL = 30       # janelas secas para a linha de base de trecho × hora em dia util
MIN_JANELAS_FDS = 15        # sabado, domingo e feriado tem bem menos dias
POS_CHUVA_MIN = 180         # ate quando uma chuva que acabou conta como evento recente do trecho

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Observacoes: velocidade + chuva do trecho
# MAGIC
# MAGIC `v` junta as linhas de cada trecho fisico na janela. O `dt` aqui e o dia da **janela**, nao o da coleta: uma janela das
# MAGIC 23:50 pode ter pares nas duas particoes da silver, e agrupar pelo dia da coleta duplicaria a janela.
# MAGIC `cal` da o tipo de cada dia. Ele vem da `posicao_limpa` porque o `tipo_dia` da `velocidade_trecho` e o do primeiro par de
# MAGIC cada shape × dia: perto da meia-noite pode ser o do dia vizinho.
# MAGIC `c` calcula a chuva do trecho em cada slot: media ponderada so com os postos que tem leitura, e `peso_valido` diz
# MAGIC quanto do peso estava disponivel. Trecho sem posto nao entra. `min_desde_fim` so existe se nenhum posto do trecho
# MAGIC esta em evento. `pico_evento_mm_h` e o maior pico entre os eventos em andamento ou recentes dos postos do trecho.

# COMMAND ----------

def media(col):
    """Media ponderada pelos pesos dos postos que tem valor em `col`."""
    return f"sum(tp.peso * ch.{col}) / sum(CASE WHEN ch.{col} IS NOT NULL THEN tp.peso END) AS {col}"


SQL_OBS = f"""
WITH cal AS (
  SELECT DISTINCT date_format(ta_sp, 'yyyy-MM-dd') AS dt, tipo_dia FROM {LIMPA} WHERE dt >= '{INICIO}'),
v AS (
  SELECT concat(parada_de, '>', parada_ate) AS trecho_id, janela_sp, date_format(janela_sp, 'yyyy-MM-dd') AS dt,
         sum(dist_m) AS dist_m, sum(tempo_s) AS tempo_s, sum(n_pares) AS n_pares, sum(n_onibus) AS n_onibus,
         count(DISTINCT route_id) AS n_linhas
  FROM {VEL} WHERE dt >= '{INICIO}'
  GROUP BY 1, 2, 3),
c AS (
  SELECT tp.trecho_id, ch.slot_sp,
         {media('mm')}, {media('mm_h_30')}, {media('mm_h_60')}, {media('mm_3h')},
         sum(CASE WHEN ch.mm_h_30 IS NOT NULL THEN tp.peso END) AS peso_valido,
         bool_and(ch.seco_estrito) AS seco_estrito,
         bool_and(ch.seco_3h) AS seco_3h,
         bool_or(ch.em_evento) AS em_evento,
         CASE WHEN bool_or(ch.em_evento) THEN NULL ELSE min(ch.min_desde_fim) END AS min_desde_fim,
         min(ch.min_ate_proximo) AS min_ate_proximo,
         max(ch.frac_cidade_chuva) AS frac_cidade_chuva,
         max(CASE WHEN ch.em_evento OR ch.min_desde_fim <= {POS_CHUVA_MIN} THEN e.pico_mm_h_30 END) AS pico_evento_mm_h
  FROM {TRECHO_POSTO} tp JOIN {CHUVA_POSTO} ch USING (prefixo)
  LEFT JOIN {EVENTO} e ON e.evento_id = ch.evento_id
  WHERE ch.dt >= '{INICIO}'
  GROUP BY 1, 2)
SELECT v.*, cal.tipo_dia,
       hour(v.janela_sp) AS hora, dayofweek(v.janela_sp) AS dia_semana, weekofyear(v.janela_sp) AS semana,
       CASE cal.tipo_dia WHEN 'util' THEN 'util' WHEN 'sabado' THEN 'sabado' ELSE 'domingo_feriado' END AS grupo_dia,
       c.mm, c.mm_h_30, c.mm_h_60, c.mm_3h, c.peso_valido, c.seco_estrito, c.seco_3h, c.em_evento,
       c.min_desde_fim, c.min_ate_proximo, c.frac_cidade_chuva, c.pico_evento_mm_h,
       CASE WHEN c.mm_h_30 IS NULL OR c.peso_valido < {PESO_MIN} THEN 'sem_dado'
            WHEN c.seco_estrito THEN 'seco'
            WHEN c.seco_3h THEN 'transbordamento'
            WHEN c.mm_h_30 = 0 AND c.min_desde_fim <= 180 THEN 'pos_chuva'
            WHEN c.mm_h_30 = 0 THEN 'sem_dado'
            WHEN c.mm_h_30 < {TRACO_MM_H} THEN 'traco'
            WHEN c.mm_h_30 < {FRACA} THEN 'fraca'
            WHEN c.mm_h_30 < {MODERADA} THEN 'moderada'
            WHEN c.mm_h_30 < {FORTE} THEN 'forte'
            ELSE 'muito_forte' END AS classe_chuva
FROM v JOIN cal USING (dt) JOIN c ON c.trecho_id = v.trecho_id AND c.slot_sp = v.janela_sp
"""

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Linha de base
# MAGIC
# MAGIC Na ordem: velocidade normal do trecho → fator de dia da semana × hora → fator de semana. Cada passo olha so as janelas
# MAGIC `seco` e o que sobrou do passo anterior. Trecho × hora com poucas janelas secas fica sem linha de base (nao entra na view).

# COMMAND ----------

SQL_LINHA_BASE = f"""
SELECT trecho_id, grupo_dia, hora, sum(dist_m) / sum(tempo_s) AS v_base_ms,
       count(*) AS n_janelas_secas, count(DISTINCT dt) AS n_dias_secos, sum(tempo_s) / 3600 AS horas_onibus_secas
FROM obs WHERE classe_chuva = 'seco'
GROUP BY 1, 2, 3
HAVING count(*) >= CASE WHEN grupo_dia = 'util' THEN {MIN_JANELAS_UTIL} ELSE {MIN_JANELAS_FDS} END
"""

SQL_AJUSTE_DIA_HORA = """
SELECT o.grupo_dia, o.dia_semana, o.hora,
       sum(o.dist_m) / sum(o.tempo_s * b.v_base_ms) AS fator_dia_hora, count(*) AS n_janelas
FROM obs o JOIN base b USING (trecho_id, grupo_dia, hora)
WHERE o.classe_chuva = 'seco'
GROUP BY 1, 2, 3
"""

SQL_AJUSTE_SEMANA = """
SELECT o.semana, min(to_date(o.janela_sp)) AS inicio_semana,
       sum(o.dist_m) / sum(o.tempo_s * b.v_base_ms * f.fator_dia_hora) AS fator_semana, count(*) AS n_janelas
FROM obs o JOIN base b USING (trecho_id, grupo_dia, hora)
JOIN fator_dh f USING (grupo_dia, dia_semana, hora)
WHERE o.classe_chuva = 'seco'
GROUP BY 1
"""

spark.sql(SQL_OBS).write.mode("overwrite").option("overwriteSchema", True).partitionBy("dt").saveAsTable(OBS)
spark.table(OBS).createOrReplaceTempView("obs")

spark.sql(SQL_LINHA_BASE).write.mode("overwrite").option("overwriteSchema", True).saveAsTable(LINHA_BASE)
spark.table(LINHA_BASE).createOrReplaceTempView("base")

spark.sql(SQL_AJUSTE_DIA_HORA).write.mode("overwrite").option("overwriteSchema", True).saveAsTable(AJUSTE_DIA_HORA)
spark.table(AJUSTE_DIA_HORA).createOrReplaceTempView("fator_dh")

spark.sql(SQL_AJUSTE_SEMANA).write.mode("overwrite").option("overwriteSchema", True).saveAsTable(AJUSTE_SEMANA)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. View com a razao
# MAGIC
# MAGIC View, nao tabela: junta tres tabelas pequenas na hora e nao duplica centenas de milhoes de linhas. O join e `INNER`:
# MAGIC janela sem linha de base (ou de semana sem fator) nao aparece.

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE VIEW {RAZAO} AS
SELECT o.*,
       b.v_base_ms * 3.6 AS v_base_kmh, f.fator_dia_hora, s.fator_semana,
       b.v_base_ms * f.fator_dia_hora * s.fator_semana * 3.6 AS v_esperada_kmh,
       o.tempo_s * b.v_base_ms * f.fator_dia_hora * s.fator_semana AS dist_esperada_m,
       o.dist_m / (o.tempo_s * b.v_base_ms * f.fator_dia_hora * s.fator_semana) AS razao
FROM {OBS} o
JOIN {LINHA_BASE} b USING (trecho_id, grupo_dia, hora)
JOIN {AJUSTE_DIA_HORA} f USING (grupo_dia, dia_semana, hora)
JOIN {AJUSTE_SEMANA} s USING (semana)
""")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Checagens (falham o run)
# MAGIC
# MAGIC 1. `(trecho_id, janela_sp)` unico.
# MAGIC 2. **Conservacao:** ate o penultimo dia com chuva, a distancia na `obs` + a dos trechos sem posto = a da
# MAGIC    `velocidade_trecho`.
# MAGIC 3. **A linha de base descreve o seco:** nas janelas `seco`, a razao agregada e 1 no total (±0,2%), por dia da semana e
# MAGIC    por semana (±0,5%). Por construcao tem que dar; se nao der, ha erro nos joins.
# MAGIC 4. Pelo menos 90% do tempo de onibus tem linha de base.
# MAGIC 5. O grupo de dia combina com o dia da semana (dia util nao cai em domingo).

# COMMAND ----------

problemas = []
o = spark.table(OBS)
if o.groupBy("trecho_id", "janela_sp").count().filter("count > 1").count():
    problemas.append("(trecho_id, janela_sp) repetido")

fim = o.agg(F.max("dt")).first()[0]
ate = o.filter(F.col("dt") < fim).agg(F.max("dt")).first()[0]
vel = (spark.table(VEL).filter(f"dt >= '{INICIO}' AND date_format(janela_sp, 'yyyy-MM-dd') <= '{ate}'")
       .withColumn("trecho_id", F.concat("parada_de", F.lit(">"), "parada_ate"))
       .join(spark.table(TRECHO).select("trecho_id", "fonte_chuva"), "trecho_id"))
d_vel = vel.filter("fonte_chuva != 'sem_posto'").agg(F.sum("dist_m")).first()[0]
d_obs = o.filter(f"dt <= '{ate}'").agg(F.sum("dist_m")).first()[0]
if abs(d_obs / d_vel - 1) > 1e-6:
    problemas.append(f"conservacao: obs {d_obs:,.0f} m, velocidade {d_vel:,.0f} m")

r = spark.table(RAZAO)
seco = r.filter("classe_chuva = 'seco'")
total = seco.agg(F.sum("dist_m") / F.sum("dist_esperada_m")).first()[0]
if abs(total - 1) > 0.002:
    problemas.append(f"razao no seco = {total:.4f}")
for col in ("dia_semana", "semana"):
    ruins = (seco.groupBy(col).agg((F.sum("dist_m") / F.sum("dist_esperada_m")).alias("x"))
             .filter("abs(x - 1) > 0.005").collect())
    if ruins:
        problemas.append(f"razao no seco por {col} fora de 1: {[(x[col], round(x.x, 4)) for x in ruins]}")

t_obs = o.agg(F.sum("tempo_s")).first()[0]
t_raz = r.agg(F.sum("tempo_s")).first()[0]
print(f"tempo de onibus com linha de base: {100 * t_raz / t_obs:.1f}%")
if t_raz / t_obs < 0.90:
    problemas.append(f"so {100 * t_raz / t_obs:.1f}% do tempo tem linha de base")

if o.filter("(grupo_dia = 'util' AND dia_semana IN (1, 7)) OR (grupo_dia = 'sabado' AND dia_semana <> 7)").count():
    problemas.append("grupo de dia incoerente com o dia da semana")

assert not problemas, "\n".join(problemas)
print(f"ok: {o.count():,} observacoes ate {fim}; conservacao ok; razao no seco = {total:.4f}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Relatorio
# MAGIC
# MAGIC **Efeito por classe de chuva**, agora com a linha de base ajustada. E a tabela da exploracao (secao 1.4 do desenho)
# MAGIC refeita com a chuva dos 3 postos. Em `dia util`. Os intervalos de confianca vem no notebook 10.

# COMMAND ----------

periodo = (F.when(F.col("hora").between(6, 9), "1 pico manha")
            .when(F.col("hora").between(16, 19), "3 pico tarde")
            .when(F.col("hora").between(10, 15), "2 meio do dia")
            .when(F.col("hora").between(20, 23), "4 noite")
            .otherwise("5 madrugada"))
ordem = F.array_position(F.array(*[F.lit(c) for c in ["sem_dado", "seco", "transbordamento", "pos_chuva", "traco", "fraca",
                                                      "moderada", "forte", "muito_forte"]]), F.col("classe_chuva"))
display(r.filter("grupo_dia = 'util'").withColumn("periodo", periodo).withColumn("ordem", ordem)
        .groupBy("ordem", "classe_chuva", "periodo")
        .agg(F.round(F.sum("dist_m") / F.sum("dist_esperada_m"), 3).alias("razao"),
             F.count("*").alias("janelas"), F.countDistinct("dt").alias("dias"))
        .orderBy("ordem", "periodo"))

# COMMAND ----------

# MAGIC %md
# MAGIC **Fatores da linha de base.** Dia da semana (2 = segunda ... 6 = sexta) e semana, para conferir que fazem sentido.

# COMMAND ----------

display(spark.table(AJUSTE_DIA_HORA).filter("grupo_dia = 'util'").groupBy("dia_semana")
        .agg(F.round(F.sum(F.col("fator_dia_hora") * F.col("n_janelas")) / F.sum("n_janelas"), 4).alias("fator_medio"))
        .orderBy("dia_semana"))
display(spark.table(AJUSTE_SEMANA).orderBy("semana"))

# COMMAND ----------

# MAGIC %run ./metadados

# COMMAND ----------

for tabela in [OBS, LINHA_BASE, AJUSTE_DIA_HORA, AJUSTE_SEMANA]:
    aplicar_metadados(tabela)
