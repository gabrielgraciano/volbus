# Databricks notebook source
# MAGIC %md
# MAGIC # 13 — Gold: recuperacao por trecho e por grupo (KR2)
# MAGIC
# MAGIC O notebook 10 mediu a recuperacao da cidade. Aqui ela desce para os trechos, em **dia util, das 6h as 23h**, depois de eventos com
# MAGIC pico **moderado ou mais forte** (≥ 2,5 mm/h). Desenho: `docs/gold_desenho.md`, secoes 2.6 e 1.13.
# MAGIC
# MAGIC | Saida | Grao | Pergunta |
# MAGIC |---|---|---|
# MAGIC | `gold.recuperacao_trecho` | trecho | KR2: em que faixa de tempo o trecho volta, e quanto perde nas 2 h seguintes |
# MAGIC | `gold.tempo_recuperacao_grupo` | dimensao × grupo × periodo | KR2: tempo e perda de cada grupo de trechos |
# MAGIC | `gold.recuperacao_grupo` | dimensao × grupo × periodo × minutos | a curva de cada grupo |
# MAGIC | `gold.validacao_recuperacao` | metrica | as medidas por trecho se repetem em outros dias? |
# MAGIC
# MAGIC **Por que nao ha um "tempo de recuperacao" exato por trecho.** Uma janela isolada varia ±23%, porque tem ~3 pares de posicoes. Um
# MAGIC trecho com deficit constante de 5%, que **nunca** recupera, seria marcado como recuperado na 1a hora em 30% dos eventos. Por isso o
# MAGIC primeiro cruzamento por trecho × evento, e a analise de sobrevivencia prevista no desenho, mediriam ruido. Ficaram fora.
# MAGIC
# MAGIC **Por trecho: faixas de tempo.** Junta as janelas de cada hora depois do fim, em todos os eventos do trecho: 1a hora, 2a hora e 3a
# MAGIC hora. Cada janela desconta o que a cidade perde naquela faixa, periodo do fim e intensidade, para o trecho nao parecer lento so por
# MAGIC ter pegado chuva terminando no pico. Depois encolhe como no notebook 12, com mistura de normais, e calcula a probabilidade de a
# MAGIC razao verdadeira estar abaixo de 0,99.
# MAGIC
# MAGIC | `classe_recuperacao` | Regra (abaixo = P ≥ 0,8; normal = P ≤ 0,2) |
# MAGIC |---|---|
# MAGIC | `ate_1h` | normal na 2a hora |
# MAGIC | `1h_a_2h` | abaixo na 2a hora, normal na 3a |
# MAGIC | `mais_de_2h` | abaixo na 2a e na 3a hora |
# MAGIC | `mais_de_1h` | abaixo na 2a hora, 3a sem dado ou indefinida |
# MAGIC | `indefinido` | nao da para dizer |
# MAGIC
# MAGIC As razoes por trecho estao na mistura de chuva da cidade. Um trecho `ate_1h` pode demorar mais depois de uma chuva no pico: o
# MAGIC periodo em que a chuva acaba pesa mais que o trecho (notebook 10). `perda_2h_min` = minutos de operacao normal perdidos por onibus
# MAGIC nas 2 h depois do fim.
# MAGIC
# MAGIC **Por grupo: tempo de verdade.** Juntando trechos ha dado para repetir a regra do notebook 10 (razao ≥ 0,99 por 3 janelas seguidas),
# MAGIC com intervalo por 1.000 reamostras de dias.
# MAGIC
# MAGIC **Cuidado com o grupo critico.** Ele foi escolhido pela queda durante a chuva, nos mesmos dias da recuperacao. Por isso
# MAGIC `gold.validacao_recuperacao` traz o teste limpo: os 1% piores escolhidos numa metade dos dias, medidos na outra metade.
# MAGIC
# MAGIC **Quando rodar:** a mao, depois do notebook 12, quando houver chuva nova. Fora do job diario.

# COMMAND ----------

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from pyspark.sql import functions as F
from scipy.special import digamma, polygamma
from scipy.stats import norm

spark.conf.set("spark.sql.session.timeZone", "UTC")

RAZAO = "onibus.gold.obs_razao"
TRECHO = "onibus.gold.trecho"
INFRA = "onibus.gold.trecho_infra"
EFEITO_TRECHO = "onibus.gold.efeito_trecho"
RECUP_CIDADE = "onibus.gold.recuperacao_cidade"

RECUP_TRECHO = "onibus.gold.recuperacao_trecho"
RECUP_GRUPO = "onibus.gold.recuperacao_grupo"
TEMPO_GRUPO = "onibus.gold.tempo_recuperacao_grupo"
VALIDACAO = "onibus.gold.validacao_recuperacao"

MODERADA, FORTE = 2.5, 10.0     # mm/h: mesmas fronteiras dos notebooks 09 e 10
ANTECIPACAO_MIN = 40            # a velocidade comeca a cair ~30 min antes de o posto registrar a chuva
TAU_MAX = 170
PASSO_MIN = 10
BANDA = 0.01                    # recuperado = razao >= 1 - BANDA
JANELAS_ESTAVEIS = 3
PERDA_ATE_MIN = 120
JANELAS = {"h1": (0, 60), "h2": (60, 120), "h3": (120, 180)}
JANELA_PERDA = (0, PERDA_ATE_MIN)
MIN_DIAS, MIN_JANELAS = 8, 30   # regra [N], por janela de tempo
P_ABAIXO = 0.8
REPS = 1000
METADES = 12
SEED = 350                      # MAE0350
MIN_DIAS_GRUPO = 8
GRADE = np.array([0.0, 0.005, 0.01, 0.02, 0.04, 0.08, 0.16, 0.32, 0.64])
TERMINAL = "Terminal|Term\\.|Garagem|Metrô|Estação"

TAUS = np.arange(0, TAU_MAX + 1, PASSO_MIN)
DIMENSOES = {"via": "coletora", "alagamento": "0 dias", "onibus": "sem faixa nem corredor", "critico": "resto"}
PERIODOS = {"todos": None, "pico": ["manha", "tarde"], "fora_do_pico": ["meio", "noite"]}

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Agregar

# COMMAND ----------

HORA_FIM = "hour(o.janela_sp - make_interval(0, 0, 0, 0, 0, CAST(o.min_desde_fim AS INT), 0))"
PERIODO_FIM = f"""CASE WHEN {HORA_FIM} BETWEEN 6 AND 9 THEN 'manha' WHEN {HORA_FIM} BETWEEN 10 AND 15 THEN 'meio'
                       WHEN {HORA_FIM} BETWEEN 16 AND 19 THEN 'tarde' WHEN {HORA_FIM} BETWEEN 20 AND 23 THEN 'noite' ELSE 'madrugada' END"""
FILTRO_POS = f"""o.grupo_dia = 'util' AND o.hora >= 6 AND o.min_desde_fim <= {TAU_MAX} AND o.pico_evento_mm_h >= {MODERADA}
                 AND coalesce(o.min_ate_proximo, 1200) > {ANTECIPACAO_MIN}"""

SQL_POS = f"""
SELECT o.trecho_id, o.dt, CAST(floor(o.min_desde_fim / 30) * 30 AS INT) AS faixa,
       CASE WHEN o.pico_evento_mm_h >= {FORTE} THEN 'forte' ELSE 'moderada' END AS classe_evento, {PERIODO_FIM} AS periodo_fim,
       sum(o.dist_m) AS d, sum(o.dist_esperada_m) AS e, count(*) AS janelas, sum(o.tempo_s) / 3600 AS horas
FROM {RAZAO} o JOIN {TRECHO} t USING (trecho_id)
WHERE {FILTRO_POS} AND NOT t.f_atipico AND t.fonte_chuva = 'daee'
GROUP BY 1, 2, 3, 4, 5
"""

SQL_CHUVA = f"""
SELECT o.trecho_id, o.dt, CASE WHEN o.hora BETWEEN 6 AND 9 THEN 'manha' WHEN o.hora BETWEEN 10 AND 15 THEN 'meio'
                               WHEN o.hora BETWEEN 16 AND 19 THEN 'tarde' ELSE 'noite' END AS periodo, o.classe_chuva,
       sum(o.dist_m) AS d, sum(o.dist_esperada_m) AS e, count(*) AS janelas
FROM {RAZAO} o JOIN {TRECHO} t USING (trecho_id)
WHERE o.grupo_dia = 'util' AND o.hora >= 6 AND NOT t.f_atipico AND t.fonte_chuva = 'daee'
  AND o.classe_chuva IN ('moderada', 'forte', 'muito_forte')
GROUP BY 1, 2, 3, 4
"""

SQL_TRECHO = f"""
SELECT t.trecho_id, t.nome_de, t.nome_ate, t.lat, t.lon, t.comprimento_m, t.n_linhas, t.horas_onibus, t.dist_posto_km,
       i.classe_dominante, i.frac_faixa, i.frac_corredor, i.dias_alag_100m, e.grupo_critico
FROM {TRECHO} t JOIN {INFRA} i USING (trecho_id) LEFT JOIN {EFEITO_TRECHO} e USING (trecho_id)
WHERE NOT t.f_atipico AND t.fonte_chuva = 'daee'
"""

CTE_GRUPOS = f"""
WITH cl AS (
  SELECT t.trecho_id,
         CASE i.classe_dominante WHEN 'VTR' THEN 'expressa' WHEN 'RODOVIA' THEN 'expressa' WHEN 'ARTERIAL' THEN 'arterial'
                                 WHEN 'LOCAL' THEN 'local' ELSE 'coletora' END AS via,
         CASE WHEN i.dias_alag_100m = 0 THEN '0 dias' WHEN i.dias_alag_100m <= 4 THEN '1-4 dias' ELSE '5+ dias' END AS alagamento,
         CASE WHEN i.frac_corredor >= 0.5 THEN 'corredor' WHEN i.frac_faixa >= 0.5 THEN 'faixa' ELSE 'sem faixa nem corredor' END AS onibus,
         CASE WHEN e.grupo_critico THEN 'critico' WHEN e.grupo_critico IS NOT NULL THEN 'resto' END AS critico
  FROM {TRECHO} t JOIN {INFRA} i USING (trecho_id) LEFT JOIN {EFEITO_TRECHO} e USING (trecho_id)
  WHERE NOT t.f_atipico AND t.fonte_chuva = 'daee')
"""

SQL_GRUPOS = CTE_GRUPOS + f"""
SELECT o.dt, CAST(o.min_desde_fim AS INT) AS tau_min, {PERIODO_FIM} AS periodo_fim, cl.via, cl.alagamento, cl.onibus, cl.critico,
       sum(o.dist_m) AS d, sum(o.dist_esperada_m) AS e, count(*) AS janelas
FROM {RAZAO} o JOIN cl USING (trecho_id)
WHERE {FILTRO_POS}
GROUP BY 1, 2, 3, 4, 5, 6, 7
"""

SQL_N_TRECHOS = CTE_GRUPOS + """
SELECT dimensao, grupo, count(*) AS n_trechos FROM (
  SELECT stack(4, 'via', via, 'alagamento', alagamento, 'onibus', onibus, 'critico', critico) AS (dimensao, grupo) FROM cl)
WHERE grupo IS NOT NULL GROUP BY 1, 2
"""

SQL_CIDADE = f"""
SELECT sum(janelas) AS janelas FROM {RECUP_CIDADE} WHERE periodo_fim = 'todos' AND classe_evento IN ('moderada', 'forte')
"""

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Por trecho: efeito por janela de tempo
# MAGIC
# MAGIC `moderar`, `desenho`, `wls`, `ajustar` e `prob_abaixo` sao as mesmas do notebook 12, onde estao explicadas.

# COMMAND ----------

def moderar(s2, gl, x):
    z = np.log(s2) - digamma(gl / 2) + np.log(gl / 2)
    A = np.c_[np.ones(len(x)), x, x ** 2]
    b = np.linalg.lstsq(A, z, rcond=None)[0]
    resto = z - A @ b
    alvo = np.mean(resto ** 2) * len(resto) / (len(resto) - A.shape[1]) - np.mean(polygamma(1, gl / 2))
    lo, hi = 1e-2, 1e4
    for _ in range(60):
        gl0 = np.sqrt(lo * hi)
        lo, hi = (gl0, hi) if polygamma(1, gl0 / 2) > alvo else (lo, gl0)
    s0 = np.exp(A @ b + digamma(gl0 / 2) - np.log(gl0 / 2))
    return (gl0 * s0 + gl * s2) / (gl0 + gl), gl0


def desenho(x):
    via = x.classe_dominante.replace({"VTR": "EXPRESSA", "RODOVIA": "EXPRESSA", "SEM_CLASSE": "COLETORA"})
    return pd.DataFrame({"constante": 1.0, "via_expressa": (via == "EXPRESSA") * 1.0, "via_arterial": (via == "ARTERIAL") * 1.0,
                         "via_local": (via == "LOCAL") * 1.0, "alag_log1p_dias": np.log1p(x.dias_alag_100m), "frac_faixa": x.frac_faixa,
                         "frac_corredor": x.frac_corredor, "perto_terminal": x.perto_terminal * 1.0,
                         "log_comprimento": np.log(x.comprimento_m / 300), "log_horas_onibus": np.log(x.horas_onibus / x.horas_onibus.median()),
                         "dist_posto_km": x.dist_posto_km}, index=x.index)


def wls(y, X, w):
    Xw = X * w[:, None]
    return np.linalg.solve(Xw.T @ X, Xw.T @ y)


def ajustar(theta, s2, X, voltas=4, em=100):
    v = s2[:, None] + GRADE ** 2
    pi = np.full(len(GRADE), 1 / len(GRADE))
    for _ in range(voltas):
        tau2 = (pi * GRADE ** 2).sum()
        g = wls(theta, X, 1 / (s2 + tau2))
        r = theta - X @ g
        ll = -0.5 * r[:, None] ** 2 / v - 0.5 * np.log(v)
        lik = np.exp(ll - ll.max(axis=1, keepdims=True))
        for _ in range(em):
            resp = pi * lik
            resp /= resp.sum(axis=1, keepdims=True)
            pi = resp.mean(axis=0)
    b = GRADE ** 2 / v
    mk, vk = b * r[:, None], b * s2[:, None]
    media_u = (resp * mk).sum(axis=1)
    return {"pi": pi, "prior": X @ g, "media": X @ g + media_u, "dp": np.sqrt((resp * (vk + mk ** 2)).sum(axis=1) - media_u ** 2),
            "resp": resp, "mk": mk, "vk": vk}


def prob_abaixo(fit, limite):
    z = (limite - fit["prior"][:, None] - fit["mk"]) / np.sqrt(np.maximum(fit["vk"], 1e-12))
    return (fit["resp"] * norm.cdf(z)).sum(axis=1)


def estagio(c, min_dias=MIN_DIAS, min_janelas=MIN_JANELAS):
    """Efeito de cada trecho nas janelas de `c`, relativo ao que a cidade perde na mesma faixa, periodo e intensidade."""
    soma = c.groupby(["faixa", "periodo_fim", "classe_evento"])[["d", "e"]].transform("sum")
    c = c.assign(e_adj=c.e * soma.d / soma.e)
    r0 = c.d.sum() / c.e.sum()
    dia = c.groupby(["trecho_id", "dt"])[["d", "e_adj", "janelas", "horas"]].sum().reset_index()
    t = dia.groupby("trecho_id").agg(d=("d", "sum"), e=("e_adj", "sum"), janelas=("janelas", "sum"), horas=("horas", "sum"), n_dias=("dt", "nunique"))
    t = t[(t.n_dias >= min_dias) & (t.janelas >= min_janelas) & (t.d > 0)].copy()
    t["r"] = t.d / t.e
    t["theta"] = np.log(t.r)
    a = dia[dia.trecho_id.isin(t.index)].merge(t[["r", "e"]], left_on="trecho_id", right_index=True, suffixes=("", "_t"))
    a["u"] = (a.d - a.r * a.e_adj) / (a.r * a.e)
    t["s2"] = (a.u ** 2).groupby(a.trecho_id).sum().reindex(t.index) * t.n_dias / (t.n_dias - 1)
    t["s2m"], _ = moderar(t.s2.values, t.n_dias.values - 1.0, np.log(t.horas.values))
    return t, r0


def ajusta_janela(c, tr, min_dias=MIN_DIAS, min_janelas=MIN_JANELAS, **kw):
    t, r0 = estagio(c, min_dias, min_janelas)
    fit = ajustar(t.theta.values, t.s2m.values, desenho(tr.reindex(t.index)).values, **kw)
    t["razao"] = np.exp(fit["media"]) * r0
    t["ic_inf"] = np.exp(fit["media"] - 1.96 * fit["dp"]) * r0
    t["ic_sup"] = np.exp(fit["media"] + 1.96 * fit["dp"]) * r0
    t["p_abaixo"] = prob_abaixo(fit, np.log((1 - BANDA) / r0))
    return t, r0


def recorte(pos, janela):
    return pos[(pos.faixa >= janela[0]) & (pos.faixa < janela[1])]


def classificar(p2, p3):
    abaixo2, normal2 = p2 >= P_ABAIXO, p2 <= 1 - P_ABAIXO
    abaixo3, normal3 = p3 >= P_ABAIXO, p3 <= 1 - P_ABAIXO
    return np.select([normal2, abaixo2 & normal3, abaixo2 & abaixo3, abaixo2], ["ate_1h", "1h_a_2h", "mais_de_2h", "mais_de_1h"], "indefinido")


def por_trecho(pos, tr):
    h = {nome: ajusta_janela(recorte(pos, j), tr)[0] for nome, j in JANELAS.items()}
    perda = ajusta_janela(recorte(pos, JANELA_PERDA), tr)[0]
    base = h["h2"]
    s = pd.DataFrame({"n_dias_h2": base.n_dias, "janelas_h2": base.janelas})
    for nome, t in h.items():
        s[f"razao_{nome}"] = t.razao.reindex(base.index)
        s[f"p_abaixo_{nome}"] = t.p_abaixo.reindex(base.index)
    s["classe_recuperacao"] = classificar(s.p_abaixo_h2.values, s.p_abaixo_h3.values)
    s["perda_2h_min"] = PERDA_ATE_MIN * (1 - perda.razao.reindex(base.index))
    s["perda_ic_inf"] = PERDA_ATE_MIN * (1 - perda.ic_sup.reindex(base.index))
    s["perda_ic_sup"] = PERDA_ATE_MIN * (1 - perda.ic_inf.reindex(base.index))
    x = tr.reindex(base.index)
    for coluna in ("nome_de", "nome_ate", "classe_dominante", "dias_alag_100m", "lat", "lon"):
        s[coluna] = x[coluna].values
    s["grupo_critico"] = x.grupo_critico.fillna(False).astype(bool).values
    return s.reset_index()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Validacao: isso se repete em outros dias?
# MAGIC
# MAGIC Divide os dias em duas metades, varias vezes. `rho` = correlacao de postos do efeito entre as metades. `fiabilidade` projeta para
# MAGIC todos os dias (Spearman-Brown). `razao_abaixo` e `razao_normal`: classifica os trechos numa metade e mede a razao na **outra**.
# MAGIC `piores_*`: os 1% piores **durante a chuva** numa metade, com a recuperacao medida na outra, sem nenhum dia em comum.

# COMMAND ----------

def validar_metades(pos, ch, tr):
    rng = np.random.default_rng(SEED)
    dias = np.array(sorted(set(pos.dt) | set(ch.dt)))
    faixas = sorted(pos.faixa.unique())
    linhas, curvas = [], []
    for _ in range(METADES):
        s = rng.permutation(dias)
        a, b = set(s[: len(s) // 2]), set(s[len(s) // 2:])
        for nome, janela in list(JANELAS.items()) + [("h1_h2", JANELA_PERDA)]:
            c = recorte(pos, janela)
            ta, _ = ajusta_janela(c[c.dt.isin(a)], tr, min_dias=4, min_janelas=15, voltas=2, em=20)
            tb, r0b = estagio(c[c.dt.isin(b)], 3, 10)
            j = ta.join(tb[["theta"]], rsuffix="_b", how="inner")
            r_b = np.exp(j.theta_b.clip(-0.6, 0.6)) * r0b
            linhas.append({"janela": nome, "rho": j.theta.corr(j.theta_b, method="spearman"), "razao_abaixo": r_b[j.p_abaixo >= P_ABAIXO].mean(),
                           "razao_normal": r_b[j.p_abaixo <= 1 - P_ABAIXO].mean(), "n_abaixo": int((j.p_abaixo >= P_ABAIXO).sum())})
        q = ch[ch.dt.isin(a)]
        soma = q.groupby(["periodo", "classe_chuva"])[["d", "e"]].transform("sum")
        t = q.assign(e_adj=q.e * soma.d / soma.e).groupby("trecho_id").agg(d=("d", "sum"), e=("e_adj", "sum"), j=("janelas", "sum"), n=("dt", "nunique"))
        t = t[(t.j >= 15) & (t.n >= 4)]
        piores = set(np.log(t.d.clip(lower=1) / t.e).sort_values().index[: max(10, int(0.01 * len(t)))])
        p = pos[pos.dt.isin(b)]
        marca = p.trecho_id.isin(piores)
        for rotulo, parte in [("piores", p[marca]), ("resto", p[~marca])]:
            soma_f = parte.groupby("faixa")[["d", "e"]].sum()
            curvas.append(pd.Series((soma_f.d / soma_f.e).reindex(faixas).values, index=faixas, name=rotulo))

    r = pd.DataFrame(linhas).groupby("janela").median()
    saida = []
    for nome, x in r.iterrows():
        saida += [(f"rho_{nome}", x.rho), (f"fiabilidade_{nome}", 2 * x.rho / (1 + x.rho)), (f"razao_abaixo_{nome}", x.razao_abaixo),
                  (f"razao_normal_{nome}", x.razao_normal), (f"n_abaixo_{nome}", x.n_abaixo)]
    c = pd.DataFrame(curvas)
    for rotulo, g in c.groupby(level=0):
        for f, v in g.median().items():
            saida.append((f"{rotulo}_fora_da_amostra_{f}min", v))
    return pd.DataFrame(saida, columns=["metrica", "valor"])

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Por grupo: curva, tempo e perda
# MAGIC
# MAGIC Mesma regra do notebook 10. `perda_vs_ref` = perda do grupo menos a do grupo de referencia, com intervalo na mesma reamostragem:
# MAGIC acima de 0 = perde mais.

# COMMAND ----------

def pesos(dias):
    rng = np.random.default_rng(SEED)
    return rng.multinomial(len(dias), np.full(len(dias), 1 / len(dias)), size=REPS).astype(float)


def recuperou_em(curva):
    ok = curva >= 1 - BANDA
    for i in range(len(ok) - JANELAS_ESTAVEIS + 1):
        if ok[i:i + JANELAS_ESTAVEIS].all():
            return float(TAUS[i])
    return np.nan


def por_grupo(g, n_trechos):
    dias = sorted(g.dt.unique())
    w = pesos(dias)
    n_perda = PERDA_ATE_MIN // PASSO_MIN
    curvas, tempos = [], []
    for dimensao, referencia in DIMENSOES.items():
        h = g.dropna(subset=[dimensao])
        for periodo, quais in PERIODOS.items():
            parte = h if quais is None else h[h.periodo_fim.isin(quais)]
            blocos = {}
            for grupo, x in parte.groupby(dimensao):
                d = x.pivot_table(index="dt", columns="tau_min", values="d", aggfunc="sum").reindex(index=dias, columns=TAUS).fillna(0.0).values
                e = x.pivot_table(index="dt", columns="tau_min", values="e", aggfunc="sum").reindex(index=dias, columns=TAUS).fillna(0.0).values
                with np.errstate(divide="ignore", invalid="ignore"):
                    reps = (w @ d) / (w @ e)
                ponto = d.sum(axis=0) / e.sum(axis=0)
                blocos[grupo] = (ponto, reps, ((1 - reps[:, :n_perda]) * PASSO_MIN).sum(axis=1), x)
            perda_ref = blocos[referencia][2]
            ponto_ref = blocos[referencia][0]
            for grupo, (ponto, reps, perda, x) in blocos.items():
                n_dias = x.dt.nunique()
                fragil = n_dias < MIN_DIAS_GRUPO
                ic = np.full((2, len(TAUS)), np.nan) if fragil else np.nanpercentile(reps, [2.5, 97.5], axis=0)
                curvas.append(pd.DataFrame({"dimensao": dimensao, "grupo": grupo, "periodo": periodo, "tau_min": TAUS.astype(int), "razao": ponto,
                                            "ic_inf": ic[0], "ic_sup": ic[1], "fragil": fragil}))
                t = np.array([recuperou_em(r) for r in reps])
                censurado = np.isnan(t)
                inf, sup = np.percentile(np.where(censurado, np.inf, t), [2.5, 97.5], method="nearest")
                p_inf, p_sup = np.nanpercentile(perda, [2.5, 97.5])
                r_inf, r_sup = np.nanpercentile(perda - perda_ref, [2.5, 97.5])
                pp = float(((1 - ponto[:n_perda]) * PASSO_MIN).sum())
                tempos.append({"dimensao": dimensao, "grupo": grupo, "periodo": periodo, "tempo_rec_min": recuperou_em(ponto),
                               "ic_inf": np.nan if fragil else inf, "ic_sup": np.nan if fragil or np.isinf(sup) else sup,
                               "frac_censurada": float(censurado.mean()), "perda_min": pp, "perda_ic_inf": np.nan if fragil else p_inf,
                               "perda_ic_sup": np.nan if fragil else p_sup, "perda_vs_ref": pp - float(((1 - ponto_ref[:n_perda]) * PASSO_MIN).sum()),
                               "ref_ic_inf": np.nan if fragil else r_inf, "ref_ic_sup": np.nan if fragil else r_sup,
                               "n_trechos": int(n_trechos.get((dimensao, grupo), 0)), "n_dias": n_dias, "janelas": int(x.janelas.sum()), "fragil": fragil})
    return pd.concat(curvas, ignore_index=True), pd.DataFrame(tempos)


def calcular(pos, ch, tr, g, n_trechos):
    tr = tr.set_index("trecho_id")
    tr = tr.assign(perto_terminal=tr.nome_de.str.contains(TERMINAL, case=False, regex=True)
                   | tr.nome_ate.str.contains(TERMINAL, case=False, regex=True))
    pos = pos[pos.trecho_id.isin(tr.index)]
    ch = ch[ch.trecho_id.isin(tr.index)]
    n = {(a, b): c for a, b, c in n_trechos[["dimensao", "grupo", "n_trechos"]].itertuples(index=False)}
    curvas, tempos = por_grupo(g, n)
    return {"trecho": por_trecho(pos, tr), "validacao": validar_metades(pos, ch, tr), "curvas": curvas, "tempos": tempos}

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Calcular e gravar

# COMMAND ----------

def gravar(t, tabela):
    s = spark.createDataFrame(t)
    for coluna, tipo in s.dtypes:
        if tipo == "double":
            s = s.withColumn(coluna, F.nanvl(coluna, F.lit(None).cast("double")))   # nan vira nulo
    s.write.mode("overwrite").option("overwriteSchema", True).saveAsTable(tabela)


pos = spark.sql(SQL_POS).toPandas()
ch = spark.sql(SQL_CHUVA).toPandas()
tr = spark.sql(SQL_TRECHO).toPandas()
g = spark.sql(SQL_GRUPOS).toPandas()
n_trechos = spark.sql(SQL_N_TRECHOS).toPandas()
janelas_cidade = spark.sql(SQL_CIDADE).first()[0]

res = calcular(pos, ch, tr, g, n_trechos)
gravar(res["trecho"], RECUP_TRECHO)
gravar(res["curvas"], RECUP_GRUPO)
gravar(res["tempos"], TEMPO_GRUPO)
gravar(res["validacao"], VALIDACAO)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Checagens (falham o run)
# MAGIC
# MAGIC 1. Um trecho por linha.
# MAGIC 2. Os grupos somam o mesmo total em toda dimensao, e esse total bate com a `recuperacao_cidade` do notebook 10 (±0,5%).
# MAGIC 3. **A classificacao prediz outros dias:** na 1a e na 2a hora, quem foi marcado abaixo numa metade fica abaixo de quem foi marcado
# MAGIC    normal, na outra metade.
# MAGIC 4. A soma das classes de recuperacao bate com o numero de trechos.

# COMMAND ----------

def validar(res, g, janelas_cidade):
    problemas = []
    s, v = res["trecho"], res["validacao"].set_index("metrica").valor
    if s.trecho_id.duplicated().any():
        problemas.append("trecho repetido")
    totais = {d: int(g.dropna(subset=[d]).janelas.sum()) for d in ("via", "alagamento", "onibus")}
    if len(set(totais.values())) > 1:
        problemas.append(f"grupos com totais diferentes: {totais}")
    if abs(totais["via"] / float(janelas_cidade) - 1) > 0.005:
        problemas.append(f"janelas: {totais['via']:,} nos grupos, {int(janelas_cidade):,} no notebook 10")
    for j in ("h1", "h2"):
        if not v[f"razao_abaixo_{j}"] < v[f"razao_normal_{j}"]:
            problemas.append(f"classificacao nao prediz outros dias em {j}: {v[f'razao_abaixo_{j}']:.3f} x {v[f'razao_normal_{j}']:.3f}")
    if s.classe_recuperacao.value_counts().sum() != len(s):
        problemas.append("classes nao somam os trechos")
    return problemas


problemas = validar(res, g, janelas_cidade)
assert not problemas, "\n".join(problemas)
print(f"ok: {len(res['trecho']):,} trechos com a regra de dado minimo na 2a hora")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. Resultado

# COMMAND ----------

def relatorio(res):
    pd.set_option("display.width", 220, "display.max_columns", 40, "display.max_rows", 300, "display.max_colwidth", 34)
    s, v, t = res["trecho"], res["validacao"], res["tempos"]
    print(f"KR2 por trecho: {len(s):,} trechos com a regra [N]")
    c = s.classe_recuperacao.value_counts()
    print(c.to_string())
    print(f"classificados: {int(c.drop('indefinido', errors='ignore').sum()):,} ({100 * c.drop('indefinido', errors='ignore').sum() / len(s):.1f}%)")
    print(f"perda nas 2 h, quantis 5/50/95%: {np.round(s.perda_2h_min.quantile([.05, .5, .95]).values, 1)} min")
    print(pd.crosstab(s.classe_recuperacao, s.grupo_critico).to_string())
    print("\nvalidacao")
    print(v.round(3).to_string(index=False))
    print("\ntrechos com mais perda nas 2 h depois da chuva")
    print(s.sort_values("perda_2h_min", ascending=False)[["nome_de", "nome_ate", "perda_2h_min", "razao_h1", "razao_h2", "razao_h3", "classe_recuperacao",
                                                          "classe_dominante", "dias_alag_100m", "grupo_critico"]].head(15).round(3).to_string(index=False))
    print("\npor grupo: tempo e perda (perda_vs_ref > 0 = perde mais que a referencia)")
    colunas = ["periodo", "dimensao", "grupo", "tempo_rec_min", "ic_inf", "ic_sup", "frac_censurada", "perda_min", "perda_ic_inf", "perda_ic_sup",
               "perda_vs_ref", "ref_ic_inf", "ref_ic_sup", "n_trechos", "n_dias"]
    print(t[colunas].sort_values(["periodo", "dimensao", "grupo"]).round(2).to_string(index=False))


relatorio(res)

fig, eixos = plt.subplots(2, 4, figsize=(16, 7), sharex=True, sharey=True)
for linha, periodo in zip(eixos, ("pico", "fora_do_pico")):
    for ax, dimensao in zip(linha, DIMENSOES):
        c = res["curvas"][(res["curvas"].periodo == periodo) & (res["curvas"].dimensao == dimensao)]
        for grupo, x in c.groupby("grupo"):
            ax.plot(x.tau_min, x.razao, ls="--" if x.fragil.iloc[0] else "-", label=grupo)
            ax.fill_between(x.tau_min, x.ic_inf, x.ic_sup, alpha=0.12, lw=0)
        ax.axhline(1 - BANDA, color="gray", ls=":", lw=1)
        ax.axhline(1, color="gray", lw=0.5)
        ax.set_title(f"{dimensao}, {periodo}")
        ax.legend(fontsize=7)
for ax in eixos[1]:
    ax.set_xlabel("minutos depois do fim")
plt.show()

# COMMAND ----------

# MAGIC %run ./metadados

# COMMAND ----------

for tabela in [RECUP_TRECHO, RECUP_GRUPO, TEMPO_GRUPO, VALIDACAO]:
    aplicar_metadados(tabela)
