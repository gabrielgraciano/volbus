# Databricks notebook source
# MAGIC %md
# MAGIC # 10 — Gold: efeito da chuva na cidade (KR1 e KR2)
# MAGIC
# MAGIC Usa a razao do notebook 09 (1 = normal; 0,90 = 10% mais lento) e responde, para a cidade, em **dia util, das 6h as 23h**.
# MAGIC Desenho: `docs/gold_desenho.md`, secoes 2.5 e 2.6. Efeito por trecho e ranking ficam para o notebook 11.
# MAGIC
# MAGIC | Saida | Grao | Pergunta |
# MAGIC |---|---|---|
# MAGIC | `gold.efeito_cidade` | recorte × periodo × classe de chuva | KR1: quanto a velocidade cai durante a chuva? |
# MAGIC | `gold.recuperacao_cidade` | periodo do fim × classe do evento × minutos | KR2: como a velocidade volta depois da chuva? |
# MAGIC | `gold.tempo_recuperacao` | periodo do fim × classe do evento | KR2: quanto tempo leva e quanto se perde? |
# MAGIC
# MAGIC **Por que reamostrar dias.** Janelas do mesmo dia nao sao independentes: a mesma frente fria atinge milhares de trechos ao
# MAGIC mesmo tempo. A unidade independente e o **dia**, entao o intervalo de confianca sai de 2.000 reamostras de dias inteiros,
# MAGIC com reposicao. Todas as celulas usam as mesmas reamostras, o que permite comparar uma celula com outra. Em cada reamostra
# MAGIC a razao e dividida pela do seco, para a variacao entre dias da linha de base entrar no intervalo. A incerteza de `v_base`
# MAGIC por trecho nao entra; os modelos com efeitos fixos (secao 2.5 do desenho) cobrem isso depois.
# MAGIC
# MAGIC **Frageis.** Celula com menos de 8 dias (a regra [N] dos KRs) mostra a razao, mas fica sem intervalo: com poucos dias, parte
# MAGIC das reamostras nem contem a celula. `jk_min` e `jk_max` sao a razao tirando um dia por vez.
# MAGIC
# MAGIC **Recuperacao.** `tau_min` = minutos depois do fim do evento (0 = a janela logo apos o fim). So entram trechos com postos
# MAGIC DAEE (as outras redes nao marcam bem inicio e fim) e janelas a mais de 40 min da proxima chuva, porque a velocidade comeca a
# MAGIC cair antes de o posto registrar. Tempo de recuperacao = primeiro `tau` em que a razao fica **≥ 0,99 por 3 janelas seguidas**,
# MAGIC buscando ate 170 min. Quem passa de 1 tambem esta recuperado, por isso a banda so olha para baixo. Reamostra que nao recupera
# MAGIC ate 170 min conta como censurada, e o limite superior do intervalo fica vazio se elas passam de 2,5%.
# MAGIC
# MAGIC **A curva depende da hora em que a chuva acaba** (mais em `gold_desenho`, secao 1.11), por isso o resultado sai por periodo do fim.
# MAGIC
# MAGIC **Quando rodar:** a mao, depois do notebook 09. Fora do job diario.

# COMMAND ----------

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from pyspark.sql import functions as F

spark.conf.set("spark.sql.session.timeZone", "UTC")

RAZAO = "onibus.gold.obs_razao"
TRECHO = "onibus.gold.trecho"

EFEITO = "onibus.gold.efeito_cidade"
RECUPERACAO = "onibus.gold.recuperacao_cidade"
TEMPO = "onibus.gold.tempo_recuperacao"

REPS = 2000
SEED = 350                  # MAE0350
MIN_DIAS = 8                # regra [N] dos KRs: abaixo disso a celula e fragil
CORTE_1MIN = "2026-09-21"   # 1o dia inteiro com coleta a 1 min
MODERADA, FORTE = 2.5, 10.0 # mm/h: mesmas fronteiras do notebook 09
ANTECIPACAO_MIN = 40        # a velocidade comeca a cair ~30 min antes de o posto registrar a chuva
TAU_MAX = 170               # a ultima janela antes de o trecho voltar a contar como seco (3 h)
PASSO_MIN = 10
BANDA = 0.01                # recuperado = razao >= 1 - BANDA
JANELAS_ESTAVEIS = 3        # ... por 30 min seguidos
PERDA_ATE_MIN = 120         # a perda acumulada olha as 2 h depois do fim
LEAD_MAX = 120

TAUS = np.arange(0, TAU_MAX + 1, PASSO_MIN)
PERIODOS = ["manha", "meio", "tarde", "noite"]
CLASSES_CHUVA = ["sem_dado", "seco", "transbordamento", "pos_chuva", "traco", "fraca", "moderada", "forte", "muito_forte"]
CLASSES_EVENTO = ["fraca", "moderada", "forte"]
CONTRASTES = [("tarde", "fraca", "meio", "fraca"), ("tarde", "moderada", "meio", "moderada"),
              ("tarde", "forte", "meio", "forte"), ("todos", "moderada", "todos", "fraca"),
              ("todos", "forte", "todos", "moderada"), ("todos", "muito_forte", "todos", "forte")]

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Agregar por dia
# MAGIC
# MAGIC Tudo que o bootstrap precisa e `(Σ dist, Σ dist esperada)` por dia e celula: poucos milhares de linhas, que cabem no driver.
# MAGIC Fica fora quem e `f_atipico` (trecho de geometria estranha) e a madrugada (operacao diferente). No KR2, `periodo_fim` e o
# MAGIC periodo em que a chuva **acabou**, nao o da janela; evento que acaba de madrugada so entra em `todos`.

# COMMAND ----------

def periodo_sql(hora):
    return f"""CASE WHEN {hora} BETWEEN 6 AND 9 THEN 'manha' WHEN {hora} BETWEEN 10 AND 15 THEN 'meio'
                    WHEN {hora} BETWEEN 16 AND 19 THEN 'tarde' WHEN {hora} BETWEEN 20 AND 23 THEN 'noite' END"""


FILTRO = "o.grupo_dia = 'util' AND NOT t.f_atipico AND o.hora >= 6"
HORA_FIM = "hour(o.janela_sp - make_interval(0, 0, 0, 0, 0, CAST(o.min_desde_fim AS INT), 0))"

SQL_EFEITO = f"""
SELECT o.dt, o.classe_chuva, {periodo_sql('o.hora')} AS periodo,
       sum(o.dist_m) AS d, sum(o.dist_esperada_m) AS e, count(*) AS janelas
FROM {RAZAO} o JOIN {TRECHO} t USING (trecho_id)
WHERE {FILTRO}
GROUP BY 1, 2, 3
"""

SQL_RECUPERACAO = f"""
SELECT o.dt, CAST(o.min_desde_fim AS INT) AS tau_min,
       CASE WHEN o.pico_evento_mm_h >= {FORTE} THEN 'forte' WHEN o.pico_evento_mm_h >= {MODERADA} THEN 'moderada'
            ELSE 'fraca' END AS classe_evento,
       {periodo_sql(HORA_FIM)} AS periodo_fim,
       sum(o.dist_m) AS d, sum(o.dist_esperada_m) AS e, count(*) AS janelas
FROM {RAZAO} o JOIN {TRECHO} t USING (trecho_id)
WHERE {FILTRO} AND t.fonte_chuva = 'daee' AND o.min_desde_fim <= {TAU_MAX} AND o.pico_evento_mm_h IS NOT NULL
  AND coalesce(o.min_ate_proximo, {10 * LEAD_MAX}) > {ANTECIPACAO_MIN}
GROUP BY 1, 2, 3, 4
"""

SQL_LEADS = f"""
SELECT o.dt, -CAST(o.min_ate_proximo AS INT) AS tau_min,
       sum(o.dist_m) AS d, sum(o.dist_esperada_m) AS e, count(*) AS janelas
FROM {RAZAO} o JOIN {TRECHO} t USING (trecho_id)
WHERE {FILTRO} AND t.fonte_chuva = 'daee' AND o.classe_chuva = 'seco' AND o.min_ate_proximo <= {LEAD_MAX}
GROUP BY 1, 2
"""

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Funcoes do bootstrap
# MAGIC
# MAGIC `pesos` diz quantas vezes cada dia saiu em cada reamostra. Com a matriz `w` (reamostras × dias) e as matrizes `d` e `e`
# MAGIC (dias × celulas), `w @ d` da a soma da reamostra de uma vez, sem laco.

# COMMAND ----------

def pesos(dias):
    rng = np.random.default_rng(SEED)
    return rng.multinomial(len(dias), np.full(len(dias), 1 / len(dias)), size=REPS).astype(float)


def razao(w, d, e):
    """Σ d / Σ e por reamostra. Celula sem nenhum dia na reamostra vira nan."""
    with np.errstate(divide="ignore", invalid="ignore"):
        return (w @ d) / (w @ e)


def matrizes(df, chave, dias, celulas=None):
    d = df.pivot_table(index="dt", columns=chave, values="d", aggfunc="sum")
    e = df.pivot_table(index="dt", columns=chave, values="e", aggfunc="sum")
    celulas = d.columns if celulas is None else celulas
    return d.reindex(index=dias, columns=celulas).fillna(0.0), e.reindex(index=dias, columns=celulas).fillna(0.0)


def intervalo(x):
    return np.nanpercentile(x, [2.5, 97.5])


def efeito(a, recorte):
    """Razao por periodo × classe, relativa ao seco do mesmo periodo. Devolve a tabela e as reamostras."""
    a = pd.concat([a, a.assign(periodo="todos")])
    dias = sorted(a.dt.unique())
    d, e = matrizes(a, ["periodo", "classe_chuva"], dias)
    reps = pd.DataFrame(razao(pesos(dias), d.values, e.values), columns=d.columns)
    ponto = d.sum() / e.sum()
    janelas = a.groupby(["periodo", "classe_chuva"]).janelas.sum()

    linhas, relativas = [], {}
    for periodo, classe in d.columns:
        c, s = (periodo, classe), (periodo, "seco")
        relativas[c] = reps[c] / reps[s]
        com_dado = d[c] > 0
        sem_um = (d[c].sum() - d[c][com_dado]) / (e[c].sum() - e[c][com_dado]) / ponto[s]
        n_dias = int(com_dado.sum())
        fragil = n_dias < MIN_DIAS
        inf, sup = (np.nan, np.nan) if fragil else intervalo(relativas[c])
        linhas.append({"recorte": recorte, "periodo": periodo, "classe_chuva": classe, "razao": ponto[c] / ponto[s],
                       "ic_inf": inf, "ic_sup": sup, "jk_min": sem_um.min(), "jk_max": sem_um.max(),
                       "n_dias": n_dias, "janelas": int(janelas[c]), "fragil": fragil})
    return pd.DataFrame(linhas), relativas, ponto


def contrastes(relativas, ponto):
    """Razao entre duas celulas: < 1 = a primeira perde mais. Intervalo que nao inclui 1 = diferenca clara."""
    linhas = []
    for p1, c1, p2, c2 in CONTRASTES:
        rel = relativas[(p1, c1)] / relativas[(p2, c2)]
        pt = (ponto[(p1, c1)] / ponto[(p1, "seco")]) / (ponto[(p2, c2)] / ponto[(p2, "seco")])
        inf, sup = intervalo(rel)
        linhas.append({"contraste": f"{p1}/{c1} vs {p2}/{c2}", "razao": pt, "ic_inf": inf, "ic_sup": sup})
    return pd.DataFrame(linhas)


def recuperou_em(curva):
    """Primeiro tau com a razao >= 1 - BANDA por JANELAS_ESTAVEIS janelas seguidas; nan se nao recuperou."""
    ok = curva >= 1 - BANDA
    for i in range(len(ok) - JANELAS_ESTAVEIS + 1):
        if ok[i:i + JANELAS_ESTAVEIS].all():
            return float(TAUS[i])
    return np.nan


def recuperacao(a, b, leads):
    """Curvas e tempos de recuperacao. `a` so entra para dar o seco de cada reamostra."""
    dias = sorted(a.dt.unique())
    w = pesos(dias)
    seco = a[a.classe_chuva == "seco"].groupby("dt")[["d", "e"]].sum().reindex(dias)
    seco_rep = razao(w, seco.d.values, seco.e.values)
    seco_ponto = seco.d.sum() / seco.e.sum()
    n_perda = PERDA_ATE_MIN // PASSO_MIN

    def curva(g, taus):
        d, e = matrizes(g, "tau_min", dias, taus)
        return (d.sum() / e.sum()).values / seco_ponto, razao(w, d.values, e.values) / seco_rep[:, None]

    def linhas_curva(periodo, classe, g, taus, ponto, reps, fragil):
        ic = np.full((2, len(taus)), np.nan) if fragil else np.nanpercentile(reps, [2.5, 97.5], axis=0)
        n = g.groupby("tau_min").agg(n_dias=("dt", "nunique"), janelas=("janelas", "sum")).reindex(taus).fillna(0).astype(int)
        return pd.DataFrame({"periodo_fim": periodo, "classe_evento": classe, "tau_min": [int(t) for t in taus], "razao": ponto,
                             "ic_inf": ic[0], "ic_sup": ic[1], "n_dias": n.n_dias.values, "janelas": n.janelas.values,
                             "fragil": fragil})

    curvas, tempos = [], []
    for periodo in ["todos"] + PERIODOS:
        parte = b if periodo == "todos" else b[b.periodo_fim == periodo]
        for classe in CLASSES_EVENTO:
            g = parte[parte.classe_evento == classe]
            n_dias = g.dt.nunique()
            fragil = n_dias < MIN_DIAS
            ponto, reps = curva(g, TAUS)
            curvas.append(linhas_curva(periodo, classe, g, TAUS, ponto, reps, fragil))

            t = np.array([recuperou_em(r) for r in reps])
            censurado = np.isnan(t)
            inf, sup = np.percentile(np.where(censurado, np.inf, t), [2.5, 97.5], method="nearest")
            perda = ((1 - reps[:, :n_perda]) * PASSO_MIN).sum(axis=1)
            p_inf, p_sup = intervalo(perda)
            tempos.append({"periodo_fim": periodo, "classe_evento": classe, "tempo_rec_min": recuperou_em(ponto),
                           "ic_inf": np.nan if fragil else inf, "ic_sup": np.nan if fragil or np.isinf(sup) else sup,
                           "frac_censurada": float(censurado.mean()),
                           "perda_min": float(((1 - ponto[:n_perda]) * PASSO_MIN).sum()),
                           "perda_ic_inf": np.nan if fragil else p_inf, "perda_ic_sup": np.nan if fragil else p_sup,
                           "n_dias": n_dias, "janelas": int(g.janelas.sum()), "fragil": fragil})

    taus = np.sort(leads.tau_min.unique())
    ponto, reps = curva(leads, taus)
    curvas.append(linhas_curva("todos", "antecipacao", leads, taus, ponto, reps, False))
    return pd.concat(curvas, ignore_index=True), pd.DataFrame(tempos)


def quadro(t):
    """Classes × periodos, em texto; celula fragil traz o numero de dias no lugar do intervalo."""
    txt = [f"{x.razao:.3f} ({x.n_dias} dias)" if x.fragil else f"{x.razao:.3f} [{x.ic_inf:.3f}-{x.ic_sup:.3f}]"
           for x in t.itertuples()]
    return (t.assign(txt=txt).pivot(index="classe_chuva", columns="periodo", values="txt")
            .reindex(index=CLASSES_CHUVA, columns=PERIODOS + ["todos"]).fillna("-"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Calcular e gravar
# MAGIC
# MAGIC `recorte` separa a coleta a 2 min (`ate_20_09`) da coleta a 1 min (`desde_21_09`): se o efeito so aparecesse num dos dois,
# MAGIC seria sinal de artefato.

# COMMAND ----------

def gravar(t, tabela):
    s = spark.createDataFrame(t)
    for coluna, tipo in s.dtypes:
        if tipo == "double":
            s = s.withColumn(coluna, F.nanvl(coluna, F.lit(None).cast("double")))   # nan vira nulo
    s.write.mode("overwrite").option("overwriteSchema", True).saveAsTable(tabela)


a = spark.sql(SQL_EFEITO).toPandas()
b = spark.sql(SQL_RECUPERACAO).toPandas()
leads = spark.sql(SQL_LEADS).toPandas()

t_efeito, relativas, ponto = efeito(a, "tudo")
t_ate, _, _ = efeito(a[a.dt < CORTE_1MIN], "ate_20_09")
t_desde, _, _ = efeito(a[a.dt >= CORTE_1MIN], "desde_21_09")
t_efeito_todos = pd.concat([t_efeito, t_ate, t_desde], ignore_index=True)
t_contrastes = contrastes(relativas, ponto)
t_curvas, t_tempos = recuperacao(a, b, leads)

gravar(t_efeito_todos, EFEITO)
gravar(t_curvas, RECUPERACAO)
gravar(t_tempos, TEMPO)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Checagens (falham o run)
# MAGIC
# MAGIC 1. Todo dia da analise e de segunda a sexta.
# MAGIC 2. Nas janelas `seco` a razao bruta e 1 em todo periodo (±0,2%).
# MAGIC 3. **Antecipacao:** de 60 a 120 min antes de a chuva chegar ao posto, a velocidade esta normal (±1%). Com erro de fuso, a
# MAGIC    queda apareceria horas antes.
# MAGIC 4. Reamostras: com pelo menos 8 dias, a celula aparece em quase todas (≥ 99%).

# COMMAND ----------

problemas = []
if pd.to_datetime(a.dt).dt.dayofweek.max() > 4:
    problemas.append("dia de fim de semana na analise de dia util")

seco = ponto.xs("seco", level="classe_chuva")
if (seco - 1).abs().max() > 0.002:
    problemas.append(f"razao no seco fora de 1: {seco.round(4).to_dict()}")

antes = t_curvas[(t_curvas.classe_evento == "antecipacao") & (t_curvas.tau_min <= -60)]
if (antes.razao - 1).abs().max() > 0.01:
    problemas.append(f"antecipacao fora de 1: {antes.set_index('tau_min').razao.round(4).to_dict()}")

for c, rel in relativas.items():
    n_dias = t_efeito[(t_efeito.periodo == c[0]) & (t_efeito.classe_chuva == c[1])].n_dias.iloc[0]
    if n_dias >= MIN_DIAS and rel.notna().mean() < 0.99:
        problemas.append(f"reamostras sem a celula {c}: {rel.notna().mean():.3f}")

assert not problemas, "\n".join(problemas)
print(f"ok: {a.dt.nunique()} dias uteis; {a.janelas.sum():,} janelas no KR1; {b.janelas.sum():,} no KR2")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Resultado
# MAGIC
# MAGIC **KR1.** Razao [IC 95%] por classe e periodo. `muito_forte` tem poucos dias: leia como indicativo.

# COMMAND ----------

pd.set_option("display.width", 200, "display.max_columns", 30, "display.max_rows", 200)
print(quadro(t_efeito).to_string())
print("\nsensibilidade: coleta a 2 min (ate 20/09)")
print(quadro(t_ate).to_string())
print("\nsensibilidade: coleta a 1 min (desde 21/09)")
print(quadro(t_desde).to_string())
print("\ncontrastes")
print(t_contrastes.round(3).to_string(index=False))

# COMMAND ----------

# MAGIC %md
# MAGIC **KR2.** Tempo de recuperacao e perda acumulada: `perda_min` = minutos de operacao normal perdidos por onibus nas 2 h depois
# MAGIC do fim (area entre 1 e a curva). Tempo vazio = nao recuperou ate 170 min. `ic_sup` vazio = mais de 2,5% das reamostras nao
# MAGIC recuperaram. No grafico, tracejado = fragil; a linha pontilhada e 0,99.

# COMMAND ----------

print(t_tempos.drop(columns="janelas").round(3).to_string(index=False))

cores = {"fraca": "#7fb3d5", "moderada": "#2e86c1", "forte": "#1b4f72"}
fig, eixos = plt.subplots(1, 4, figsize=(15, 3.4), sharey=True)
for ax, periodo in zip(eixos, PERIODOS):
    for classe, cor in cores.items():
        c = t_curvas[(t_curvas.periodo_fim == periodo) & (t_curvas.classe_evento == classe)]
        fragil = c.fragil.iloc[0]
        ax.plot(c.tau_min, c.razao, color=cor, ls="--" if fragil else "-", label=f"{classe} ({c.n_dias.max()} dias)")
        if not fragil:
            ax.fill_between(c.tau_min, c.ic_inf, c.ic_sup, color=cor, alpha=0.15, lw=0)
    ax.axhline(1 - BANDA, color="gray", ls=":", lw=1)
    ax.axhline(1, color="gray", lw=0.5)
    ax.set_title(f"chuva acabou: {periodo}")
    ax.set_xlabel("minutos depois do fim")
    ax.legend(fontsize=8)
eixos[0].set_ylabel("razao")
plt.show()

# COMMAND ----------

# MAGIC %md
# MAGIC **Antecipacao.** Razao nas janelas secas, pelos minutos que faltam para a chuva chegar ao posto.

# COMMAND ----------

print(t_curvas[t_curvas.classe_evento == "antecipacao"][["tau_min", "razao", "ic_inf", "ic_sup", "janelas"]].round(4).to_string(index=False))

# COMMAND ----------

# MAGIC %run ./metadados

# COMMAND ----------

for tabela in [EFEITO, RECUPERACAO, TEMPO]:
    aplicar_metadados(tabela)
