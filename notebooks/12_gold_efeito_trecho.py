# Databricks notebook source
# MAGIC %md
# MAGIC # 12 — Gold: efeito por trecho, ranking e infraestrutura (KR1, KR3 e KR4)
# MAGIC
# MAGIC Desce do nivel da cidade (notebook 10) para cada trecho, em **dia util, das 6h as 23h**, com chuva **moderada ou mais forte**
# MAGIC (≥ 2,5 mm/h). Desenho: `docs/gold_desenho.md`, secoes 2.7, 2.8 e 1.12.
# MAGIC
# MAGIC | Saida | Grao | Pergunta |
# MAGIC |---|---|---|
# MAGIC | `gold.efeito_trecho` | trecho | KR1 e KR3: quanto cada trecho perde, com que certeza, e com que frequencia fica entre os piores |
# MAGIC | `gold.estabilidade_ranking` | metrica | KR3: o ranking passa no criterio de estabilidade? |
# MAGIC | `gold.efeito_infra` | modelo × termo | KR4: o que a infraestrutura explica, comparando trechos parecidos |
# MAGIC | `gold.efeito_grupo` | dimensao × grupo × chuva | KR4: a queda de cada grupo de trechos, sem modelo |
# MAGIC
# MAGIC **Regra de dado minimo ([N] dos KRs):** chuva moderada+ em ≥ 8 dias e ≥ 30 janelas; postos DAEE; sem trechos atipicos.
# MAGIC
# MAGIC **Estagio 1, o efeito bruto.** `theta` = log(Σ distancia ÷ Σ distancia esperada na chuva) − o mesmo no seco do trecho. A
# MAGIC distancia esperada na chuva ja desconta a queda **da cidade** naquele periodo e classe de chuva. Sem isso, um trecho pareceria
# MAGIC pior so por ter pegado chuva forte no pico da tarde. `theta = 0` = perdeu o mesmo que a cidade; `theta < 0` = perdeu mais.
# MAGIC O erro vem da variacao **entre dias**, a unidade independente. Com ~13 dias por trecho esse erro e ruidoso, entao ele e
# MAGIC moderado com a tendencia de trechos parecidos, como no `limma` (Smyth 2004).
# MAGIC
# MAGIC **Estagio 2, o encolhimento.** Num ranking, os extremos sao em parte azar: quem tem pouco dado fica no topo por ruido. O efeito de
# MAGIC cada trecho e puxado para o esperado pelas suas caracteristicas, mais forte quanto maior o erro. O efeito verdadeiro segue uma
# MAGIC **mistura de normais** de larguras diferentes, como no `ashr` (Stephens 2017): com uma normal so, trechos muito ruins eram
# MAGIC achatados (−0,53 virava −0,13) e o ranking piorava (Jaccard 0,18 contra 0,33). Os coeficientes desse estagio respondem ao KR4.
# MAGIC
# MAGIC **Estabilidade (KR3).** Refaz os dois estagios em 500 reamostras de dias. Criterio fixado **antes** de ver o resultado: cada um dos
# MAGIC 10 primeiros no top-20 em ≥ 80% das reamostras e Jaccard mediano ≥ 0,5. O criterio nao muda aqui, mesmo que o ranking reprove.
# MAGIC `grupo_critico` e uma alternativa, a decidir com o Rafael: trechos entre os 5% piores em ≥ 80% das reamostras.
# MAGIC
# MAGIC **Validacoes.** *Metades:* divide os dias em duas metades e ve se quem foi mal numa vai mal na outra, sem nenhum modelo.
# MAGIC *Placebo:* ve se o trecho fica lento nas janelas **secas** dos mesmos dias. Se ficar, a causa e outra (obra, desvio), nao a chuva.
# MAGIC
# MAGIC Trechos se sobrepoem (linhas que pulam paradas geram pares diferentes na mesma rua), entao `local_critico` junta os trechos do
# MAGIC grupo critico a ate 300 m: e o numero de lugares, nao de trechos.
# MAGIC
# MAGIC **Testado e descartado na exploracao** (`docs/gold_desenho.md`, secao 1.12): agrupar em eixos de 1–4 km (fiabilidade 0,46 contra
# MAGIC 0,43), comparar so dentro do mesmo dia (0,43), estimadores robustos entre dias (0,31–0,42), ranking por local em grade de 200 m a
# MAGIC 1 km (Jaccard ate 0,43) e incluir a chuva fraca (Jaccard 0,33). Nenhuma alternativa passou no criterio.
# MAGIC
# MAGIC **Quando rodar:** a mao, depois dos notebooks 09 e 11, quando houver chuva nova. Fora do job diario.

# COMMAND ----------

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from pyspark.sql import functions as F
from scipy import sparse
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree
from scipy.special import digamma, polygamma
from scipy.stats import norm

spark.conf.set("spark.sql.session.timeZone", "UTC")

RAZAO = "onibus.gold.obs_razao"
TRECHO = "onibus.gold.trecho"
INFRA = "onibus.gold.trecho_infra"

EFEITO_TRECHO = "onibus.gold.efeito_trecho"
ESTABILIDADE = "onibus.gold.estabilidade_ranking"
EFEITO_INFRA = "onibus.gold.efeito_infra"
EFEITO_GRUPO = "onibus.gold.efeito_grupo"

CLASSES = ["moderada", "forte", "muito_forte"]
MIN_DIAS, MIN_JANELAS = 8, 30
REPS = 500
SEED = 350                  # MAE0350
METADES = 30
GRADE = np.array([0.0, 0.005, 0.01, 0.02, 0.04, 0.08, 0.16, 0.32, 0.64])    # larguras da mistura, em log

CRIT_TOP20, CRIT_JACCARD = 0.8, 0.5     # criterio de estabilidade: nao mudar depois de ver o resultado
PIOR_PCT = 0.05
FREQ_CRITICO = 0.8
RAIO_LOCAL_M = 300                      # trechos criticos a ate essa distancia sao o mesmo lugar
P_QUEDA = 0.95
MIN_DIAS_GRUPO = 8
GRADE_ESPACIAL_GRAUS = 0.018            # ~2 km: blocos para a incerteza espacial do KR4
TERMINAL = "Terminal|Term\\.|Garagem|Metrô|Estação"

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Agregar por trecho × dia

# COMMAND ----------

PERIODO = """CASE WHEN o.hora BETWEEN 6 AND 9 THEN 'manha' WHEN o.hora BETWEEN 10 AND 15 THEN 'meio'
                  WHEN o.hora BETWEEN 16 AND 19 THEN 'tarde' ELSE 'noite' END"""
FILTRO = "o.grupo_dia = 'util' AND NOT t.f_atipico AND t.fonte_chuva = 'daee' AND o.hora >= 6"

SQL_CHUVA = f"""
SELECT o.trecho_id, o.dt, {PERIODO} AS periodo, o.classe_chuva,
       sum(o.dist_m) AS d, sum(o.dist_esperada_m) AS e, count(*) AS janelas, sum(o.tempo_s) / 3600 AS horas
FROM {RAZAO} o JOIN {TRECHO} t USING (trecho_id)
WHERE {FILTRO} AND o.classe_chuva IN ('fraca', 'moderada', 'forte', 'muito_forte')
GROUP BY 1, 2, 3, 4
"""

SQL_SECO = f"""
SELECT o.trecho_id, o.dt, sum(o.dist_m) AS d, sum(o.dist_esperada_m) AS e, count(*) AS janelas, sum(o.tempo_s) / 3600 AS horas
FROM {RAZAO} o JOIN {TRECHO} t USING (trecho_id)
WHERE {FILTRO} AND o.classe_chuva = 'seco'
GROUP BY 1, 2
"""

SQL_TRECHO = f"""
SELECT t.trecho_id, t.nome_de, t.nome_ate, t.lat, t.lon, t.comprimento_m, t.n_linhas, t.horas_onibus, t.v_kmh_media, t.dist_posto_km,
       i.classe_dominante, i.frac_faixa, i.frac_faixa_longa, i.frac_faixa_via_dupla, i.frac_corredor, i.dias_alag_50m, i.dias_alag_100m
FROM {TRECHO} t JOIN {INFRA} i USING (trecho_id)
WHERE NOT t.f_atipico AND t.fonte_chuva = 'daee'
"""

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Estagio 1: efeito bruto e erro
# MAGIC
# MAGIC `erro_por_dia` usa a funcao de influencia de `theta`: quanto cada dia empurra a estimativa. A chuva e o seco do mesmo dia somam
# MAGIC antes de elevar ao quadrado, porque vem do mesmo dia. `matrizes` deixa pronta a conta de cada reamostra: com `w` = peso de cada
# MAGIC dia, `D @ w` da a soma de cada trecho de uma vez, e `theta_em(m, w)` refaz tudo, inclusive a queda da cidade.

# COMMAND ----------

def estagio1(ch, se, tr):
    c = ch[ch.classe_chuva.isin(CLASSES) & ch.trecho_id.isin(tr.index)].copy()
    se = se[se.trecho_id.isin(tr.index)]
    c["celula"] = c.periodo + "/" + c.classe_chuva
    soma = c.groupby("celula")[["d", "e"]].sum()
    c["e_adj"] = c.e * c.celula.map(soma.d / soma.e)

    dia = c.groupby(["trecho_id", "dt"])[["d", "e", "e_adj"]].sum().reset_index()
    t = dia.groupby("trecho_id").agg(d=("d", "sum"), e=("e", "sum"), e_adj=("e_adj", "sum"), n_dias=("dt", "nunique"))
    t = t.join(c.groupby("trecho_id")[["janelas", "horas"]].sum()).join(se.groupby("trecho_id")[["d", "e"]].sum().add_suffix("_seco"), how="inner")
    n_com_chuva = len(t)
    t = t[(t.n_dias >= MIN_DIAS) & (t.janelas >= MIN_JANELAS) & (t.d > 0)].copy()
    t["r_std"] = t.d / t.e_adj
    t["r_seco"] = t.d_seco / t.e_seco
    t["theta"] = np.log(t.r_std) - np.log(t.r_seco)
    t["s2"] = erro_por_dia(t, dia, se)
    t["s2m"], gl0 = moderar(t.s2.values, t.n_dias.values - 1.0, np.log(t.horas.values))
    r0 = c.d.sum() / c.e.sum()
    return t, c, r0, gl0, n_com_chuva


def erro_por_dia(t, dia, se):
    a = dia.merge(t[["r_std", "e_adj"]], left_on="trecho_id", right_index=True, suffixes=("", "_t"))
    a["u"] = (a.d - a.r_std * a.e_adj) / (a.r_std * a.e_adj_t)
    b = se.merge(t[["r_seco", "e_seco"]], left_on="trecho_id", right_index=True)
    b["u"] = -(b.d - b.r_seco * b.e) / (b.r_seco * b.e_seco)
    u = pd.concat([a[["trecho_id", "dt", "u"]], b[["trecho_id", "dt", "u"]]]).groupby(["trecho_id", "dt"]).u.sum()
    return (u ** 2).groupby("trecho_id").sum().reindex(t.index) * t.n_dias / (t.n_dias - 1)


def moderar(s2, gl, x):
    """Puxa cada variancia para a tendencia em x. gl0 = quantos graus de liberdade vale a tendencia (Smyth 2004)."""
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


def matrizes(t, c, se, dias):
    ids, n = t.index.values, len(t)
    pos, dia_pos = {x: k for k, x in enumerate(ids)}, {x: k for k, x in enumerate(dias)}
    celulas = sorted(c.celula.unique())
    r = c[c.trecho_id.isin(ids)]
    s = se[se.trecho_id.isin(ids)]
    ri, rt = r.trecho_id.map(pos).values, r.dt.map(dia_pos).values
    si, st = s.trecho_id.map(pos).values, s.dt.map(dia_pos).values

    def mat(v, i, j):
        return sparse.csr_matrix((v, (i, j)), shape=(n, len(dias)))

    return {"D": mat(r.d.values, ri, rt), "Ds": mat(s.d.values, si, st), "Es": mat(s.e.values, si, st),
            "E": [mat(r.e.values[r.celula == k], ri[r.celula == k], rt[r.celula == k]) for k in celulas],
            "cd": c.pivot_table(index="dt", columns="celula", values="d", aggfunc="sum").reindex(index=dias, columns=celulas).fillna(0.0).values,
            "ce": c.pivot_table(index="dt", columns="celula", values="e", aggfunc="sum").reindex(index=dias, columns=celulas).fillna(0.0).values}


def theta_em(m, w):
    """Efeito de cada trecho com os dias pesados por w. Devolve os trechos com dado e o efeito deles."""
    with np.errstate(divide="ignore", invalid="ignore"):
        rc = np.nan_to_num((w @ m["cd"]) / (w @ m["ce"]), nan=1.0)
    e = sum(rc[j] * (E @ w) for j, E in enumerate(m["E"]))
    d, ds, es = m["D"] @ w, m["Ds"] @ w, m["Es"] @ w
    idx = np.flatnonzero((d > 0) & (e > 0) & (ds > 0))
    return idx, np.log(d[idx] / e[idx]) - np.log(ds[idx] / es[idx])

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Estagio 2: encolhimento com covariaveis
# MAGIC
# MAGIC `ajustar` alterna dois passos: os coeficientes `g` por minimos quadrados ponderados, e a mistura `pi` pelo algoritmo EM.
# MAGIC `resp` = probabilidade de cada trecho vir de cada largura da mistura. A posterior de cada trecho e uma mistura de normais.

# COMMAND ----------

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


def ajustar(theta, s2, X, pi=None, voltas=4, em=100):
    v = s2[:, None] + GRADE ** 2
    pi = np.full(len(GRADE), 1 / len(GRADE)) if pi is None else pi
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
    return {"g": g, "pi": pi, "tau2": (pi * GRADE ** 2).sum(), "prior": X @ g, "media": X @ g + media_u,
            "dp": np.sqrt((resp * (vk + mk ** 2)).sum(axis=1) - media_u ** 2), "resp": resp, "mk": mk, "vk": vk}


def prob_abaixo(fit, limite):
    """P(efeito verdadeiro < limite), somando as normais da mistura."""
    z = (limite - fit["prior"][:, None] - fit["mk"]) / np.sqrt(np.maximum(fit["vk"], 1e-12))
    return (fit["resp"] * norm.cdf(z)).sum(axis=1)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Reamostragem: estabilidade e KR4
# MAGIC
# MAGIC Em cada reamostra de dias refaz os dois estagios e guarda quem ficou no topo. As variancias ficam fixas, porque nao da para
# MAGIC recalcular o erro por dia dentro de uma reamostra. Os modelos alternativos do KR4 reusam o mesmo efeito da reamostra.
# MAGIC Depois, uma segunda reamostragem por **blocos espaciais** de ~2 km: trechos vizinhos nao sao independentes.

# COMMAND ----------

def modelos_alternativos(x, X):
    a = X.copy()
    a["log_velocidade"] = np.log(x.v_kmh_media / 15)
    b = X.copy()
    b["alag_log1p_dias"] = np.log1p(x.dias_alag_50m)
    c = X.drop(columns="perto_terminal")
    d = X.copy()
    d["frac_faixa"] = x.frac_faixa_longa
    return {"principal": (X, np.ones(len(X), bool)), "ponderado_por_onibus": (X, np.ones(len(X), bool)),
            "com_velocidade": (a, np.ones(len(X), bool)), "alagamento_50m": (b, np.ones(len(X), bool)),
            "sem_terminais": (c, ~x.perto_terminal.values), "faixa_longa_mao_unica": (d, x.frac_faixa_via_dupla.values < 0.1)}


def reamostrar(m, t, fit0, x, X, dias):
    n = len(t)
    Xv, s2, horas = X.values, t.s2m.values, t.horas.values
    w_ = np.random.default_rng(SEED).multinomial(len(dias), np.full(len(dias), 1 / len(dias)), size=REPS).astype(float)
    k_pior1, k_pior5 = max(10, int(0.01 * n)), int(PIOR_PCT * n)
    conta = {"top10": np.zeros(n), "top20": np.zeros(n), "pior1": np.zeros(n), "pior5": np.zeros(n)}
    ranks = np.full((REPS, n), np.nan, dtype=np.float32)
    top10_0 = set(np.argsort(fit0["media"])[:10])
    alternativos = modelos_alternativos(x, X)
    coefs = {k: [] for k in alternativos}
    jaccard, no_top20, presentes = [], [], []
    for r in range(REPS):
        idx, th = theta_em(m, w_[r])
        presentes.append(len(idx) / n)
        fit = ajustar(th, s2[idx], Xv[idx], pi=fit0["pi"].copy(), voltas=2, em=10)
        ordem = idx[np.argsort(fit["media"])]
        for chave, k in [("top10", 10), ("top20", 20), ("pior1", k_pior1), ("pior5", k_pior5)]:
            conta[chave][ordem[:k]] += 1
        ranks[r, ordem] = np.arange(1, len(ordem) + 1)
        a = set(ordem[:10])
        jaccard.append(len(a & top10_0) / len(a | top10_0))
        no_top20.append(len(top10_0 & set(ordem[:20])))
        pesos = 1 / (s2[idx] + fit["tau2"])
        for nome, (Xa, mascara) in alternativos.items():
            ok = mascara[idx]
            coefs[nome].append(wls(th[ok], Xa.values[idx][ok], (horas[idx] if nome == "ponderado_por_onibus" else pesos)[ok]))
    return {"freq": {k: v / REPS for k, v in conta.items()}, "ranks": ranks, "coefs": {k: np.array(v) for k, v in coefs.items()},
            "jaccard": np.array(jaccard), "no_top20": np.array(no_top20), "presentes": min(presentes), "alternativos": alternativos}


def coeficientes(t, x, fit0, b):
    linhas = []
    pesos = 1 / (t.s2m.values + fit0["tau2"])
    bloco = (np.floor(x.lat.values / GRADE_ESPACIAL_GRAUS).astype(int).astype(str)
             + "/" + np.floor(x.lon.values / GRADE_ESPACIAL_GRAUS).astype(int).astype(str))
    codigos, n_blocos = pd.factorize(bloco)[0], len(np.unique(bloco))
    rng = np.random.default_rng(SEED)
    for nome, (Xa, mascara) in b["alternativos"].items():
        Xv = Xa.values[mascara]
        y, p = t.theta.values[mascara], (t.horas.values if nome == "ponderado_por_onibus" else pesos)[mascara]
        ponto = wls(y, Xv, p)
        lo, hi = np.percentile(b["coefs"][nome], [2.5, 97.5], axis=0)
        esp = []
        if nome in ("principal", "ponderado_por_onibus"):
            for _ in range(REPS):
                n_b = rng.multinomial(n_blocos, np.full(n_blocos, 1 / n_blocos))[codigos[mascara]].astype(float)
                ok = n_b > 0
                esp.append(wls(y[ok], Xv[ok], (p * n_b)[ok]))
            lo_e, hi_e = np.percentile(esp, [2.5, 97.5], axis=0)
        else:
            lo_e, hi_e = np.full(len(ponto), np.nan), np.full(len(ponto), np.nan)
        for j, termo in enumerate(Xa.columns):
            if termo != "constante":
                linhas.append({"modelo": nome, "termo": termo, "coef_log": ponto[j], "ic_inf": lo[j], "ic_sup": hi[j],
                               "ic_inf_espacial": lo_e[j], "ic_sup_espacial": hi_e[j], "n_trechos": int(mascara.sum())})
    return pd.DataFrame(linhas)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Validacoes sem modelo
# MAGIC
# MAGIC `metades`: para cada divisao aleatoria dos dias, compara o efeito do trecho numa metade e na outra. `fiabilidade` projeta a
# MAGIC correlacao para todos os dias (formula de Spearman-Brown), e `fiabilidade_dobro` para o dobro de dias de chuva.
# MAGIC `fora_da_amostra`: os 1% piores escolhidos numa metade, medidos na outra, contra a media dos trechos.
# MAGIC `placebo`: janelas secas nos dias em que choveu no trecho, contra as janelas secas nos outros dias.

# COMMAND ----------

def metades(m, t, x, X, dias):
    rng = np.random.default_rng(SEED)
    linhas = []
    k_pior = int(0.01 * len(t))
    for _ in range(METADES):
        sorteio = rng.permutation(len(dias))
        wa, wb = np.zeros(len(dias)), np.zeros(len(dias))
        wa[sorteio[: len(dias) // 2]] = 2.0
        wb[sorteio[len(dias) // 2:]] = 2.0
        ia, ta = theta_em(m, wa)
        ib, tb = theta_em(m, wb)
        a, b = pd.Series(ta, index=ia), pd.Series(tb, index=ib)
        j = pd.concat([a.rename("a"), b.rename("b")], axis=1, join="inner")
        rho = j.a.corr(j.b, method="spearman")
        fit = ajustar(j.a.values, 2 * t.s2m.values[j.index], X.values[j.index], voltas=2, em=20)
        grupo = j.index[np.argsort(fit["media"])[:k_pior]]
        pesos = 1 / (2 * t.s2m.values[j.index] + fit["tau2"])
        linhas.append({"rho": rho, "fora_da_amostra": j.b.loc[grupo].clip(-0.6, 0.6).mean() - np.average(j.b.clip(-0.6, 0.6), weights=pesos)})
    x_ = pd.DataFrame(linhas).median()
    rho = x_.rho
    return {"rho_metades": rho, "fiabilidade": 2 * rho / (1 + rho), "fiabilidade_dobro": 4 * rho / (1 + 3 * rho),
            "fora_da_amostra": x_.fora_da_amostra}


def placebo(c, se, t):
    s = se[se.trecho_id.isin(t.index)].merge(c[["trecho_id", "dt"]].drop_duplicates().assign(choveu=1), on=["trecho_id", "dt"], how="left")
    s["choveu"] = s.choveu.notna()
    a = s.groupby(["trecho_id", "choveu"])[["d", "e"]].sum().unstack("choveu")
    return np.log((a[("d", True)] / a[("e", True)]) / (a[("d", False)] / a[("e", False)])).reindex(t.index)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. KR4 sem modelo: a queda de cada grupo de trechos
# MAGIC
# MAGIC Junta todos os trechos de cada grupo. Tem muito mais dado que um trecho so, e deixa ver se o historico de alagamento pesa mais
# MAGIC quando a chuva e forte. `vs_referencia` = razao do grupo ÷ razao do grupo de referencia, na mesma chuva: < 1 = perde mais.
# MAGIC `alagamento_em_arterial` e `alagamento_em_coletora` repetem o alagamento **dentro** de uma classe de via, para separar os dois
# MAGIC efeitos sem modelo. A soma pondera pelo tempo dos onibus: mostra o que **o onibus** sente, e tempo preso pesa mais. O modelo
# MAGIC principal da o trecho tipico; `ponderado_por_onibus` usa o mesmo modelo com o peso do onibus, e liga as duas leituras.

# COMMAND ----------

def faixas_alag(x, classe):
    return pd.cut(x.dias_alag_100m, [-1, 0, 4, 10_000], labels=["0 dias", "1-4 dias", "5+ dias"]).astype(object).where(x.classe_dominante == classe)


GRUPOS = {
    "via": (lambda x: x.classe_dominante.replace({"VTR": "expressa", "RODOVIA": "expressa", "ARTERIAL": "arterial", "COLETORA": "coletora",
                                                  "LOCAL": "local", "SEM_CLASSE": "sem_classe"}), "coletora"),
    "alagamento": (lambda x: pd.cut(x.dias_alag_100m, [-1, 0, 4, 19, 10_000], labels=["0 dias", "1-4 dias", "5-19 dias", "20+ dias"]).astype(str), "0 dias"),
    "onibus": (lambda x: np.select([x.frac_corredor >= 0.5, x.frac_faixa >= 0.5], ["corredor", "faixa"], "sem faixa nem corredor"), "sem faixa nem corredor"),
    "alagamento_em_arterial": (lambda x: faixas_alag(x, "ARTERIAL"), "0 dias"),
    "alagamento_em_coletora": (lambda x: faixas_alag(x, "COLETORA"), "0 dias"),
}


def efeito_grupos(ch, se, tr, dias):
    w = np.random.default_rng(SEED).multinomial(len(dias), np.full(len(dias), 1 / len(dias)), size=REPS).astype(float)
    c = ch[ch.trecho_id.isin(tr.index)].assign(chuva=lambda z: z.classe_chuva.replace({"muito_forte": "forte+", "forte": "forte+"}))
    s = se[se.trecho_id.isin(tr.index)]
    linhas = []
    for dimensao, (regra, referencia) in GRUPOS.items():
        grupo = pd.Series(regra(tr), index=tr.index).dropna()
        g = c.assign(grupo=c.trecho_id.map(grupo)).dropna(subset=["grupo"])
        gs = s.assign(grupo=s.trecho_id.map(grupo)).dropna(subset=["grupo"])
        for chuva in ["fraca", "moderada", "forte+"]:
            a = g[g.chuva == chuva]
            d = a.pivot_table(index="dt", columns="grupo", values="d", aggfunc="sum").reindex(dias).fillna(0.0)
            e = a.pivot_table(index="dt", columns="grupo", values="e", aggfunc="sum").reindex(dias).fillna(0.0)[d.columns]
            ds = gs.pivot_table(index="dt", columns="grupo", values="d", aggfunc="sum").reindex(dias).fillna(0.0)[d.columns]
            es = gs.pivot_table(index="dt", columns="grupo", values="e", aggfunc="sum").reindex(dias).fillna(0.0)[d.columns]
            with np.errstate(divide="ignore", invalid="ignore"):
                rep = ((w @ d.values) / (w @ e.values)) / ((w @ ds.values) / (w @ es.values))
            ponto = (d.sum() / e.sum()) / (ds.sum() / es.sum())
            j_ref = list(d.columns).index(referencia)
            for j, nome in enumerate(d.columns):
                n_dias = int((d[nome] > 0).sum())
                fragil = n_dias < MIN_DIAS_GRUPO
                lo, hi = (np.nan, np.nan) if fragil else np.nanpercentile(rep[:, j], [2.5, 97.5])
                lo_r, hi_r = (np.nan, np.nan) if fragil else np.nanpercentile(rep[:, j] / rep[:, j_ref], [2.5, 97.5])
                linhas.append({"dimensao": dimensao, "grupo": nome, "chuva": chuva, "razao": ponto[nome], "ic_inf": lo, "ic_sup": hi,
                               "vs_referencia": ponto[nome] / ponto[referencia], "ref_ic_inf": lo_r, "ref_ic_sup": hi_r,
                               "n_trechos": int((grupo == nome).sum()), "n_dias": n_dias, "janelas": int(a[a.grupo == nome].janelas.sum()),
                               "fragil": fragil})
    return pd.DataFrame(linhas)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. Calcular

# COMMAND ----------

def locais(lat, lon):
    """Componentes conexas: trechos ligados por distancias de ate RAIO_LOCAL_M viram um local."""
    xy = np.c_[lat * 111_000, lon * 111_000 * np.cos(np.radians(lat.mean()))]
    pares = cKDTree(xy).query_pairs(RAIO_LOCAL_M, output_type="ndarray")
    grafo = sparse.coo_matrix((np.ones(len(pares)), (pares[:, 0], pares[:, 1])), shape=(len(xy), len(xy)))
    return connected_components(grafo, directed=False)[1]


def calcular(ch, se, tr):
    tr = tr.set_index("trecho_id") if "trecho_id" in tr else tr
    tr = tr.assign(perto_terminal=tr.nome_de.str.contains(TERMINAL, case=False, regex=True)
                   | tr.nome_ate.str.contains(TERMINAL, case=False, regex=True))
    t, c, r0, gl0, n_com_chuva = estagio1(ch, se, tr)
    x = tr.reindex(t.index)
    X = desenho(x)
    dias = sorted(set(c.dt) | set(se.dt))
    m = matrizes(t, c, se, dias)
    fit = ajustar(t.theta.values, t.s2m.values, X.values)
    b = reamostrar(m, t, fit, x, X, dias)
    ordem = np.argsort(fit["media"])

    # theta + log(r0) = efeito do trecho na mistura de chuva da cidade
    saida = pd.DataFrame({
        "trecho_id": t.index, "nome_de": x.nome_de.values, "nome_ate": x.nome_ate.values, "n_dias": t.n_dias.values, "janelas": t.janelas.values,
        "horas_chuva": t.horas.values, "razao_bruta": ((t.d / t.e) / t.r_seco).values,
        "razao_padronizada": np.exp(t.theta.values) * r0, "se_log": np.sqrt(t.s2m.values),
        "razao_encolhida": np.exp(fit["media"]) * r0, "ic_inf": np.exp(fit["media"] - 1.96 * fit["dp"]) * r0,
        "ic_sup": np.exp(fit["media"] + 1.96 * fit["dp"]) * r0, "p_queda": prob_abaixo(fit, -np.log(r0)),
        "rank": pd.Series(fit["media"]).rank(method="first").astype(int).values,
        "rank_ic_inf": np.nanpercentile(b["ranks"], 2.5, axis=0), "rank_ic_sup": np.nanpercentile(b["ranks"], 97.5, axis=0),
        "freq_top10": b["freq"]["top10"], "freq_top20": b["freq"]["top20"], "freq_pior1": b["freq"]["pior1"], "freq_pior5": b["freq"]["pior5"],
        "placebo_seco": placebo(c, se, t).values, "perto_terminal": x.perto_terminal.values, "classe_dominante": x.classe_dominante.values,
        "dias_alag_100m": x.dias_alag_100m.values, "v_kmh_media": x.v_kmh_media.values, "comprimento_m": x.comprimento_m.values,
        "lat": x.lat.values, "lon": x.lon.values})
    saida["grupo_critico"] = saida.freq_pior5 >= FREQ_CRITICO
    saida["local_critico"] = -1
    saida.loc[saida.grupo_critico, "local_critico"] = locais(saida.lat[saida.grupo_critico].values, saida.lon[saida.grupo_critico].values)

    val = metades(m, t, x, X, dias)
    f20 = b["freq"]["top20"][ordem[:10]]
    n_critico = int(saida.grupo_critico.sum())
    estab = pd.DataFrame([
        ("jaccard_mediano", np.median(b["jaccard"]), CRIT_JACCARD, "sim" if np.median(b["jaccard"]) >= CRIT_JACCARD else "nao"),
        ("top10_no_top20_em_80pct", float((f20 >= CRIT_TOP20).sum()), 10.0, "sim" if (f20 >= CRIT_TOP20).all() else "nao"),
        ("top10_no_top20_mediana_por_reamostra", float(np.median(b["no_top20"])), np.nan, ""),
        ("freq_media_top20_do_top10", float(f20.mean()), np.nan, ""),
        ("trechos_em_algum_top10", float((b["freq"]["top10"] > 0).sum()), np.nan, ""),
        ("rho_metades", val["rho_metades"], np.nan, ""), ("fiabilidade", val["fiabilidade"], np.nan, ""),
        ("fiabilidade_com_o_dobro_de_dias", val["fiabilidade_dobro"], np.nan, ""),
        ("grupo_critico_trechos", float(n_critico), np.nan, ""),
        ("grupo_critico_locais", float(saida[saida.grupo_critico].local_critico.nunique()), np.nan, ""),
        ("pior1pct_fora_da_amostra_log", val["fora_da_amostra"], np.nan, ""),
    ], columns=["metrica", "valor", "limiar", "passou"])

    coefs = coeficientes(t, x, fit, b)
    coefs["pct"] = 100 * (np.exp(coefs.coef_log) - 1)
    return {"trecho": saida, "estabilidade": estab, "coefs": coefs, "grupos": efeito_grupos(ch, se, tr, dias), "fit": fit, "t": t, "b": b,
            "info": {"r0": r0, "gl0": gl0, "n_com_chuva": n_com_chuva, "pi": dict(zip(GRADE, fit["pi"])), "presentes": b["presentes"],
                     "dias": len(dias)}}

# COMMAND ----------

ch = spark.sql(SQL_CHUVA).toPandas()
se = spark.sql(SQL_SECO).toPandas()
tr = spark.sql(SQL_TRECHO).toPandas()
res = calcular(ch, se, tr)

def gravar(t, tabela):
    s = spark.createDataFrame(t)
    for coluna, tipo in s.dtypes:
        if tipo == "double":
            s = s.withColumn(coluna, F.nanvl(coluna, F.lit(None).cast("double")))   # nan vira nulo
    s.write.mode("overwrite").option("overwriteSchema", True).saveAsTable(tabela)


gravar(res["trecho"], EFEITO_TRECHO)
gravar(res["estabilidade"], ESTABILIDADE)
gravar(res["coefs"], EFEITO_INFRA)
gravar(res["grupos"], EFEITO_GRUPO)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 8. Checagens (falham o run)
# MAGIC
# MAGIC 1. `theta_em` com todos os dias reproduz o estagio 1.
# MAGIC 2. O seco de cada trecho fica perto de 1 (±3%): a linha de base do notebook 09 esta valendo.
# MAGIC 3. Em toda reamostra, pelo menos 95% dos trechos tem dado.
# MAGIC 4. **Placebo:** no grupo critico, a queda nao aparece nas janelas secas dos mesmos dias (media acima de −0,05) e, no geral, o
# MAGIC    efeito quase nao se relaciona com o placebo (correlacao de Spearman abaixo de 0,2).
# MAGIC
# MAGIC O criterio de estabilidade do KR3 **nao** e checagem: reprovar e resultado, nao erro.

# COMMAND ----------

def validar(res, ch, se, tr):
    problemas = []
    t, s = res["t"], res["trecho"]
    if s.trecho_id.duplicated().any():
        problemas.append("trecho repetido")
    if (t.r_seco - 1).abs().max() > 0.03:
        problemas.append(f"seco fora de 1: {t.r_seco.min():.3f} a {t.r_seco.max():.3f}")
    if res["info"]["presentes"] < 0.95:
        problemas.append(f"reamostra com so {100 * res['info']['presentes']:.1f}% dos trechos")
    critico = s[s.grupo_critico]
    if len(critico) and critico.placebo_seco.mean() < -0.05:
        problemas.append(f"placebo no grupo critico: {critico.placebo_seco.mean():.3f}")
    rho = s.razao_padronizada.corr(s.placebo_seco, method="spearman")
    if abs(rho) > 0.2:
        problemas.append(f"efeito correlacionado com o placebo: {rho:.3f}")
    return problemas, rho


problemas, rho_placebo = validar(res, ch, se, tr)
tr_ok = tr.set_index("trecho_id")
c_ = ch[ch.classe_chuva.isin(CLASSES) & ch.trecho_id.isin(tr_ok.index)].assign(celula=lambda z: z.periodo + "/" + z.classe_chuva)
dias_ = sorted(set(c_.dt) | set(se.dt))
idx, th = theta_em(matrizes(res["t"], c_, se[se.trecho_id.isin(tr_ok.index)], dias_), np.ones(len(dias_)))
if np.abs(th - res["t"].theta.values[idx]).max() > 1e-6:
    problemas.append("theta_em nao reproduz o estagio 1")
assert not problemas, "\n".join(problemas)
print(f"ok: {len(res['trecho']):,} trechos no ranking, de {res['info']['n_com_chuva']:,} com chuva moderada+; {res['info']['dias']} dias; "
      f"placebo x efeito: {rho_placebo:.3f}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 9. Resultado

# COMMAND ----------

def relatorio(res):
    pd.set_option("display.width", 220, "display.max_columns", 40, "display.max_rows", 300, "display.max_colwidth", 34)
    s, e = res["trecho"], res["estabilidade"]
    print(f"KR1: {len(s):,} trechos com a regra de dado minimo; cidade nessa chuva: razao {res['info']['r0']:.3f}")
    print(f"     {(s.p_queda >= P_QUEDA).sum():,} trechos ({100 * (s.p_queda >= P_QUEDA).mean():.1f}%) com P(queda) >= {P_QUEDA}")
    print(f"     razao encolhida, quantis 5/50/95%: {np.round(s.razao_encolhida.quantile([.05, .5, .95]).values, 3)}")
    print("\nKR3: estabilidade (criterio: Jaccard >= 0,5 e os 10 no top-20 em >= 80%)")
    print(e.round(3).to_string(index=False))
    colunas = ["rank", "nome_de", "nome_ate", "razao_encolhida", "ic_inf", "ic_sup", "n_dias", "freq_top10", "freq_top20", "freq_pior5",
               "placebo_seco", "v_kmh_media", "classe_dominante", "dias_alag_100m"]
    print("\ntop 15 pelo efeito encolhido (a ordem exata nao e estavel)")
    print(s.sort_values("rank")[colunas].head(15).round(3).to_string(index=False))
    g = s[s.grupo_critico]
    print(f"\ngrupo critico: {len(g)} trechos | razao mediana {g.razao_encolhida.median():.3f} | {g.comprimento_m.sum() / 1000:.0f} km | "
          f"perto de terminal {100 * g.perto_terminal.mean():.0f}% (geral {100 * s.perto_terminal.mean():.0f}%)")
    print(g.classe_dominante.value_counts().to_dict())
    lugares = (g.sort_values("rank").groupby("local_critico")
               .agg(primeiro=("nome_de", "first"), ate=("nome_ate", "first"), trechos=("rank", "size"), melhor_rank=("rank", "min"),
                    razao=("razao_encolhida", "median"), v_kmh=("v_kmh_media", "median"), dias_alag=("dias_alag_100m", "max"))
               .sort_values("melhor_rank"))
    print(f"\n{len(lugares)} locais (trechos a ate {RAIO_LOCAL_M} m juntos); os 15 primeiros:")
    print(lugares.head(15).round(3).to_string(index=False))
    print("\nKR4: modelo (coeficientes em %; compare com as linhas de referencia: coletora, sem faixa)")
    c = res["coefs"]
    print(c[c.modelo == "principal"].drop(columns=["modelo", "n_trechos"]).round(4).to_string(index=False))
    print("\nponderado por onibus")
    print(c[c.modelo == "ponderado_por_onibus"].drop(columns=["modelo", "n_trechos"]).round(4).to_string(index=False))
    print("\nsensibilidade: coeficiente em % em cada modelo")
    print(c.pivot(index="termo", columns="modelo", values="pct").round(2).to_string())
    print("\nKR4: razao por grupo (vs_referencia < 1 = perde mais que a referencia)")
    q = res["grupos"].assign(txt=lambda z: z.razao.map("{:.3f}".format) + " | " + z.vs_referencia.map("{:.3f}".format)
                             + " [" + z.ref_ic_inf.map("{:.3f}".format) + "-" + z.ref_ic_sup.map("{:.3f}".format) + "]")
    print(q.pivot(index=["dimensao", "grupo"], columns="chuva", values="txt").reindex(columns=["fraca", "moderada", "forte+"]).to_string())
    print(q[q.chuva == "forte+"][["dimensao", "grupo", "n_trechos", "n_dias", "janelas"]].to_string(index=False))


relatorio(res)

s = res["trecho"]
fig, ax = plt.subplots(figsize=(7, 7))
ax.scatter(s.lon, s.lat, s=0.3, color="#d8d8d8")
g = s[s.grupo_critico]
ax.scatter(g.lon, g.lat, s=14, color="#c0392b", label=f"grupo critico ({len(g)})")
ax.legend()
ax.set_title("Trechos entre os 5% piores em pelo menos 80% das reamostras")
plt.show()

# COMMAND ----------

# MAGIC %run ./metadados

# COMMAND ----------

for tabela in [EFEITO_TRECHO, ESTABILIDADE, EFEITO_INFRA, EFEITO_GRUPO]:
    aplicar_metadados(tabela)
