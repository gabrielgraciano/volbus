# Databricks notebook source
# MAGIC %md
# MAGIC # 05 — Silver: deslocamento
# MAGIC
# MAGIC **Grao:** 1 par de posicoes consecutivas do mesmo onibus no mesmo dia: de onde (`d_ini_m`) para onde
# MAGIC (`d_fim_m`) na regua da rota, em quanto tempo (`dt_s`). E a unidade de observacao da velocidade: a 1 min,
# MAGIC um par anda 200–700 m, mais que um trecho entre paradas (~300–400 m).
# MAGIC
# MAGIC **Classificar, nao apagar.** Todo par fica na tabela com uma `situacao`; so os `ok` seguem para a
# MAGIC `velocidade_trecho`. Cada par recebe a primeira situacao que se aplica, nesta ordem:
# MAGIC
# MAGIC | `situacao` | Regra | Por que |
# MAGIC |---|---|---|
# MAGIC | `buraco` | Δt > 5 min | coleta perdida; interpolar seria inventar |
# MAGIC | `nova_viagem` | mudou de shape, ou foi do fim (≥ comprimento − 300 m) para o inicio (≤ 300 m) do mesmo shape | o onibus terminou uma viagem e comecou outra (ex.: o 48874 no Term. Sapopemba). Nas linhas de sentido unico, trocar `sl` nao muda o shape: nao e viagem nova |
# MAGIC | `terminal` | as duas pontas a ate 200 m do inicio (ou do fim) **e** andou menos de 50 m | onibus parado ou manobrando no terminal: velocidade ~0 que nao tem a ver com transito. Teste 08/10: 91% dos pares assim tinham |Δd| < 10 m. Quem esta saindo/chegando (anda mais) fica `ok` |
# MAGIC | `recuo` | Δd < −30 m | inclui o **sentido atrasado**: o onibus ja voltou, a API ainda manda o `sl` antigo e `d` desce por minutos |
# MAGIC | `rapido` | > 80 km/h | implausivel para onibus urbano |
# MAGIC | `ok` | o resto | vai para a velocidade |
# MAGIC
# MAGIC **O que NAO e descartado:** onibus parado ou lento **no meio da rota**. Velocidade ~0 num engarrafamento
# MAGIC e exatamente o sinal que queremos medir com e sem chuva. (O artigo de Niteroi corta < 2 km/h — aqui nao.)
# MAGIC Recuos pequenos (entre −30 e 0 m) sao ruido e ficam `ok`; a `velocidade_trecho` conta a distancia como 0.
# MAGIC
# MAGIC **Ecos saem antes de formar os pares.** A API as vezes reenvia uma posicao antiga com `ta` novo
# MAGIC (~1,1% das posicoes). Eco = coordenadas identicas as de 2 ou 3 pings antes, mas diferentes do ping
# MAGIC anterior. Nao e uma observacao: entra na conta da checagem, mas nao vira par.
# MAGIC
# MAGIC **Pares sao formados dentro do dia** (`p`, `dt`). O par que cruza a meia-noite se perde — horario de
# MAGIC pouco onibus, e cada dia fica independente (da para reprocessar um dia sozinho).
# MAGIC
# MAGIC **Checagem (por dia):** `posicoes = pares + ecos + onibus` — cada onibus-dia tem uma posicao a mais que
# MAGIC pares (a primeira nao tem anterior).

# COMMAND ----------

from pyspark.sql import Window, functions as F

spark.conf.set("spark.sql.session.timeZone", "UTC")

ROTA = "onibus.silver.posicao_rota"
DESL = "onibus.silver.deslocamento"

# Teste: um dia e poucas linhas -> so mostra, nao grava.
# Producao: linhas vazio -> grava. dias vazio = todos (overwrite total); com dias, so esses (replaceWhere).
dbutils.widgets.text("dias", "2026-10-08")
dbutils.widgets.text("linhas", "2290-10,6000-10,516N-10,4113-10")
DIAS = [d.strip() for d in dbutils.widgets.get("dias").split(",") if d.strip()]
LINHAS = [l.strip() for l in dbutils.widgets.get("linhas").split(",") if l.strip()]
ESCREVER = not LINHAS

DT_MAX_S = 300        # buraco
BORDA_M = 300.0       # fim -> inicio = nova volta (mesmo valor do notebook 04)
TERMINAL_M = 200.0    # as duas pontas perto do inicio ou do fim...
PARADO_M = 50.0       # ...e quase sem andar = terminal
RECUO_M = 30.0
VMAX_KMH = 80.0

print(f"dias={DIAS or 'todos'} linhas={LINHAS or 'todas'} escrever={ESCREVER}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Marcar os ecos
# MAGIC
# MAGIC `lag(x, k)` = valor de `x` k posicoes antes, na ordem de `ta`, para o mesmo onibus no mesmo dia.

# COMMAND ----------

pos = spark.table(ROTA)
if DIAS:
    pos = pos.filter(F.col("dt").isin(DIAS))
if LINHAS:
    pos = pos.filter(F.col("route_id").isin(LINHAS))

w = Window.partitionBy("p", "dt").orderBy("ta")

def mesma_coord(k):
    return (F.col("py") == F.lag("py", k).over(w)) & (F.col("px") == F.lag("px", k).over(w))

pos = pos.withColumn(
    "eco",
    F.coalesce((mesma_coord(2) | mesma_coord(3)) & ~mesma_coord(1), F.lit(False)))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Formar os pares e classificar
# MAGIC
# MAGIC Sem os ecos, cada posicao vira o **fim** de um par cujo **inicio** e a posicao anterior do mesmo onibus.

# COMMAND ----------

ant = lambda c: F.lag(c).over(w)

pares = (
    pos.filter(~F.col("eco"))
    .select(
        "dt", "p", "route_id", "direction_id", "shape_id", "sentido_unico", "versao_gtfs", "tipo_dia", "formato",
        ant("ta").alias("ta_ini"), F.col("ta").alias("ta_fim"),
        ant("ta_sp").alias("ta_sp_ini"), F.col("ta_sp").alias("ta_sp_fim"),
        ant("shape_id").alias("shape_ini"),
        ant("d_m").alias("d_ini_m"), F.col("d_m").alias("d_fim_m"), "comprimento_m",
        ant("py").alias("py_ini"), ant("px").alias("px_ini"),
        F.col("py").alias("py_fim"), F.col("px").alias("px_fim"))
    .filter(F.col("ta_ini").isNotNull())                       # a 1a posicao de cada onibus-dia nao tem par
    .withColumn("dt_s", F.col("ta_fim").cast("long") - F.col("ta_ini").cast("long"))
    .withColumn("dd_m", F.col("d_fim_m") - F.col("d_ini_m"))
    .withColumn("v_kmh", F.col("dd_m") / F.col("dt_s") * 3.6)
)

c = F.col("comprimento_m")
reinicio = (F.col("d_ini_m") >= c - BORDA_M) & (F.col("d_fim_m") <= BORDA_M)
terminal = ((((F.col("d_ini_m") <= TERMINAL_M) & (F.col("d_fim_m") <= TERMINAL_M))
             | ((F.col("d_ini_m") >= c - TERMINAL_M) & (F.col("d_fim_m") >= c - TERMINAL_M)))
            & (F.abs(F.col("dd_m")) < PARADO_M))

pares = (pares.withColumn(
            "situacao",
            F.when(F.col("dt_s") > DT_MAX_S, "buraco")
             .when(F.col("shape_ini") != F.col("shape_id"), "nova_viagem")
             .when(reinicio, "nova_viagem")
             .when(terminal, "terminal")
             .when(F.col("dd_m") < -RECUO_M, "recuo")
             .when(F.col("v_kmh") > VMAX_KMH, "rapido")
             .otherwise("ok"))
         .drop("shape_ini"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Quanto cai em cada situacao
# MAGIC
# MAGIC Esperado: `ok` bem acima de 90%; `recuo` na casa de 2–3% (o notebook 04 mediu 2,0% / 2,7%);
# MAGIC `nova_viagem` ~1 par por viagem.

# COMMAND ----------

tot = Window.partitionBy("sentido_unico")
display(pares.groupBy("sentido_unico", "situacao").count()
        .withColumn("pct", F.round(100 * F.col("count") / F.sum("count").over(tot), 2))
        .orderBy("sentido_unico", F.desc("count")))

ecos = pos.agg(F.sum(F.col("eco").cast("int")).alias("ecos"), F.count("*").alias("posicoes")).first()
print(f"ecos: {ecos.ecos} de {ecos.posicoes} posicoes ({100 * ecos.ecos / max(ecos.posicoes, 1):.2f}%)")

# COMMAND ----------

# MAGIC %md
# MAGIC **Velocidade dos pares `ok` por hora** (horario de SP). Tem que cair nos picos (7–9h e 17–19h) —
# MAGIC o que tambem confere o fuso mais uma vez.

# COMMAND ----------

display(pares.filter("situacao = 'ok'")
        .groupBy(F.hour("ta_sp_ini").alias("hora_sp"))
        .agg(F.count("*").alias("pares"),
             F.round(F.percentile_approx("v_kmh", 0.5), 1).alias("v_mediana_kmh"),
             F.round(F.sum("dd_m") / F.sum("dt_s") * 3.6, 1).alias("v_media_ponderada_kmh"))
        .orderBy("hora_sp"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Diagrama de Marey (so no modo teste)
# MAGIC
# MAGIC Uma linha de cada onibus: hora (x) × metro da rota (y), num sentido, de manha. Viagens sao diagonais
# MAGIC (mais inclinada = mais rapido); onibus parado e um trecho horizontal; dois onibus colados = comboio.
# MAGIC Os pares que **nao** sao `ok` aparecem coloridos — da para ver se a regra pegou a coisa certa.

# COMMAND ----------

if not ESCREVER:
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.collections import LineCollection

    alvo = (pares.filter("NOT sentido_unico").groupBy("route_id", "shape_id").count()
            .orderBy(F.desc("count")).first())
    m = (pares.filter((F.col("shape_id") == alvo.shape_id) & F.hour("ta_sp_ini").between(6, 9))
         .select("p", "ta_sp_ini", "ta_sp_fim", "d_ini_m", "d_fim_m", "situacao").toPandas())

    cores = {"ok": "#9aa3ad", "terminal": "#2f6fb0", "recuo": "#d9480f", "nova_viagem": "#2b8a3e",
             "buraco": "#7048e8", "rapido": "#e8590c"}
    fig, ax = plt.subplots(figsize=(14, 7))
    # cada par vira um segmento (hora_ini, km_ini) -> (hora_fim, km_fim); um LineCollection por situacao
    for sit, g in m.groupby("situacao"):
        x0, x1 = mdates.date2num(g.ta_sp_ini), mdates.date2num(g.ta_sp_fim)
        segs = np.stack([np.c_[x0, g.d_ini_m / 1000], np.c_[x1, g.d_fim_m / 1000]], axis=1)
        ax.add_collection(LineCollection(segs, colors=cores.get(sit, "black"),
                                         linewidths=0.8 if sit == "ok" else 1.8, label=f"{sit} ({len(g)})"))
    ax.autoscale()
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.set_title(f"{alvo.route_id} · shape {alvo.shape_id} · 6h–10h (SP)")
    ax.set_xlabel("hora (SP)"); ax.set_ylabel("km da rota")
    ax.legend(loc="upper left")
    plt.show()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Gravar (so quando `linhas` esta vazio)

# COMMAND ----------

if ESCREVER:
    if DIAS and spark.catalog.tableExists(DESL):
        lista = ", ".join(f"'{d}'" for d in DIAS)
        (pares.write.mode("overwrite").option("replaceWhere", f"dt IN ({lista})")
              .saveAsTable(DESL))
    else:
        (pares.write.mode("overwrite").option("overwriteSchema", True)
              .partitionBy("dt").saveAsTable(DESL))
    print("gravado:", DESL)
else:
    print("modo teste: nada gravado")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Checagens (falham o run)
# MAGIC
# MAGIC 1. Por dia: `posicoes = pares + ecos + onibus`.
# MAGIC 2. Todo par tem `situacao` e `dt_s > 0`.

# COMMAND ----------

if ESCREVER:
    gravado = spark.table(DESL)
    if DIAS:
        gravado = gravado.filter(F.col("dt").isin(DIAS))
    esperado = pos.groupBy("dt").agg(F.count("*").alias("posicoes"),
                                     F.sum(F.col("eco").cast("long")).alias("ecos"),
                                     F.countDistinct("p").alias("onibus"))
    checagem = (esperado.join(gravado.groupBy("dt").agg(F.count("*").alias("pares")), "dt", "full")
                .fillna(0)
                .withColumn("dif", F.col("posicoes") - F.col("pares") - F.col("ecos") - F.col("onibus"))
                .orderBy("dt"))
    problemas = [f"{r.dt}: dif {r.dif:+}" for r in checagem.filter("dif != 0").collect()]
    ruins = gravado.filter(F.col("situacao").isNull() | (F.col("dt_s") <= 0)).count()
    if ruins:
        problemas.append(f"{ruins} pares sem situacao ou com dt_s <= 0")
    assert not problemas, "\n".join(problemas)
    print(f"ok: {checagem.count()} dias, posicoes = pares + ecos + onibus")

# COMMAND ----------

# MAGIC %run ./metadados

# COMMAND ----------

if ESCREVER:
    aplicar_metadados(DESL)
