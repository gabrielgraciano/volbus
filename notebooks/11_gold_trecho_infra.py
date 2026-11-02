# Databricks notebook source
# MAGIC %md
# MAGIC # 11 — Gold: infraestrutura por trecho (KR4)
# MAGIC
# MAGIC Para cada trecho fisico: em que tipo de via ele esta, se tem faixa ou corredor de onibus e quantos dias alagou por perto.
# MAGIC Desenho: `docs/gold_desenho.md`, secao 2.8. Fontes e downloads: `docs/gold_fontes_infra.md`.
# MAGIC
# MAGIC | Saida | Grao | O que e |
# MAGIC |---|---|---|
# MAGIC | `gold.trecho_infra` | trecho fisico | fracao do trecho por classe de via, faixa, corredor, historico de alagamento |
# MAGIC
# MAGIC **Entrada.** Arquivos do GeoSampa (Fonte: GeoSampa/PMSP, CC BY-SA 4.0) baixados no PC, porque o Databricks nao alcanca
# MAGIC esses servidores, e guardados em `/Volumes/onibus/bronze/raw/infra/versao=AAAA-MM-DD/` com um `manifesto.csv`.
# MAGIC
# MAGIC **Como juntar.** Cada trecho vira pontos a cada ~20 m ao longo do seu tracado mais usado, com o rumo local. Cada ponto procura
# MAGIC a linha mais proxima da camada dentro de um raio, exigindo rumo parecido (ate 30°), para nao pegar a rua transversal num
# MAGIC cruzamento. Fracao do trecho = fracao dos pontos. Raios medidos com os dados, nao escolhidos a olho:
# MAGIC
# MAGIC | Camada | Distancia mediana ate o tracado | Raio | Por que |
# MAGIC |---|---|---|---|
# MAGIC | Classificacao viaria CET | 0,6 m | 15 m | 98,6% dos pontos casam; subir para 60 m so chega a 99,3% |
# MAGIC | Faixas de onibus | 0,8 m | 15 m | desenhadas no eixo da via, como a CET |
# MAGIC | Corredores | 7 m | 25 m | desenhados ao lado do tracado; 15 m perde 11% dos pontos |
# MAGIC
# MAGIC **Faixas: o que a geometria nao diz.** Faixa fica no eixo da via e seu desenho nao indica o sentido (53% no mesmo sentido do
# MAGIC tracado, 47% no oposto). Em via de mao unica nao ha duvida. Em via de **mao dupla**, o trecho pode estar do outro lado da rua,
# MAGIC por isso `frac_faixa_via_dupla` mostra quanto de `frac_faixa` tem essa duvida. Muitas faixas valem so no pico:
# MAGIC `frac_faixa_longa` conta so as de pelo menos 10 h por dia util. So entram as faixas `EXCLUSIVA` (7.003 de 7.378).
# MAGIC
# MAGIC **Alagamento.** Ocorrencias de `ALAGAMENTO` e `INUNDACAO` da Defesa Civil desde 2013, contando **dias distintos** num raio do
# MAGIC trecho, e nao registros: ha bloco de chamados (uma coordenada aparece 482 vezes; 3 dias de 2016 somam 3.115 de 12.625
# MAGIC ocorrencias), e um temporal so nao e historico. So entra o que veio **antes de 25/08/2026**: a chuva do periodo estudado nao
# MAGIC pode explicar a si mesma. A ocorrencia fica no endereco do chamado, por isso o raio principal e 100 m, com 50 m como sensibilidade.
# MAGIC
# MAGIC **Quando rodar:** a mao, quando baixar nova versao do GeoSampa (mude `VERSAO`). Fora do job diario.

# COMMAND ----------

# MAGIC %pip install geopandas pyogrio

# COMMAND ----------

import csv
import glob
import hashlib
import os
import re
import shutil
import warnings
import zipfile

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import shapely
from pyproj import Transformer
from scipy.spatial import cKDTree

VEL = "onibus.silver.velocidade_trecho"
GTFS_TRECHOS = "onibus.silver.gtfs_trechos"
GTFS_SHAPES = "onibus.silver.gtfs_shapes"
TRECHO = "onibus.gold.trecho"
INFRA = "onibus.gold.trecho_infra"

VERSAO = "2026-11-02"
ORIGEM = f"/Volumes/onibus/bronze/raw/infra/versao={VERSAO}"
TMP = "/tmp/infra"          # GeoPackage e SQLite: mais seguro ler de disco local que do volume

CRS = 31983                 # SIRGAS 2000 / UTM 23S, em metros: o das camadas
PASSO_M = 20
RAIO_VIA, RAIO_FAIXA, RAIO_CORREDOR = 15, 15, 25
RUMO_MAX = 30               # graus
FAIXA_LONGA_H = 10
RAIOS_ALAG = (50, 100)
INICIO_ANALISE = "2026-08-25"
INICIO_ALAG = "2013-01-01"
MIN_PONTOS_COM_CLASSE = 0.95
MIN_TRECHOS = 0.999

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Arquivos
# MAGIC
# MAGIC Copia o volume para o disco local, confere cada arquivo contra o hash do manifesto e abre os zips.

# COMMAND ----------

def preparar(origem, tmp):
    """Copia, confere os hashes e descompacta. Devolve o manifesto."""
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    with open(f"{origem}/manifesto.csv", encoding="utf-8") as f:
        manifesto = list(csv.DictReader(f))
    for m in manifesto:
        destino = shutil.copy(f"{origem}/{m['arquivo']}", tmp)
        h = hashlib.sha256(open(destino, "rb").read()).hexdigest()
        assert h == m["sha256"], f"hash diferente do manifesto: {m['arquivo']}"
        if destino.endswith(".zip"):
            with zipfile.ZipFile(destino) as z:
                z.extractall(tmp)
    return manifesto


def ler(tmp, nome):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")     # 2026 vem como ponto com M; so x e y interessam
        return gpd.read_file(f"{tmp}/{nome}")


def ler_camadas(tmp, manifesto):
    feicoes = {m["camada"]: int(m["feicoes"]) for m in manifesto}
    via = ler(tmp, "SIRGAS_GPKG_classeviariacet.gpkg")[["cvc_classe", "geometry"]]
    faixa = ler(tmp, "faixa_onibus.gpkg")
    corredor = ler(tmp, "corredor_onibus.gpkg")
    ocorr = pd.concat([ler(tmp, os.path.basename(f))[["data", "ocorrencia", "geometry"]]
                       for f in sorted(glob.glob(f"{tmp}/SIRGAS_GPKG_riscoocorrencia_*.gpkg"))], ignore_index=True)
    for nome, gdf in [("Classificacao Viaria CET", via), ("Faixas de onibus", faixa), ("Corredores de onibus", corredor),
                      ("Ocorrencias Defesa Civil 2013-2026", ocorr)]:
        assert len(gdf) == feicoes[nome], f"{nome}: {len(gdf):,} feicoes, manifesto diz {feicoes[nome]:,}"

    via = via[via.cvc_classe != "VIA DE PEDESTRES"].reset_index(drop=True)
    faixa = faixa[faixa.nm_tipo_faixa_corredor == "EXCLUSIVA"].reset_index(drop=True)
    faixa["horas"] = faixa.tx_horario_funcionamento.map(horas_dia)
    faixa["via_dupla"] = faixa.tx_sentido_via_cet.str.upper().str.startswith("DUPLO")
    corredor = corredor[corredor.dc_tipo_status_corredor_onibus.str.startswith("Em Opera")].reset_index(drop=True)
    ocorr["data"] = pd.to_datetime(ocorr.data).dt.strftime("%Y-%m-%d")
    ocorr = ocorr[ocorr.ocorrencia.isin(["ALAGAMENTO", "INUNDACAO"]) & (ocorr.data < INICIO_ANALISE)].reset_index(drop=True)
    return via, faixa, corredor, ocorr


def horas_dia(txt):
    """Horas por dia util da faixa, de textos como '2a a 6a das 06-09h e das 17-20h; Sab. das 06-14h'."""
    if not txt:
        return 0.0
    if "INTEGRAL" in txt.upper():
        return 24.0
    return float(sum((int(b) - int(a)) % 24 or 24 for a, b in re.findall(r"(\d{1,2})-(\d{1,2})h", txt.split(";")[0])))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Tracado de cada trecho
# MAGIC
# MAGIC Um trecho fisico junta varias linhas, entao sua geometria vem do tracado com **mais tempo de onibus** nele. O pedaco entre as
# MAGIC duas paradas sai da mesma regua da `posicao_rota` (`d_ini_m` a `d_fim_m`).

# COMMAND ----------

SQL_REPRESENTANTE = f"""
WITH soma AS (
  SELECT concat(parada_de, '>', parada_ate) AS trecho_id, versao_gtfs, shape_id, trecho_seq, sum(tempo_s) AS tempo_s
  FROM {VEL} GROUP BY 1, 2, 3, 4),
uso AS (SELECT * FROM soma QUALIFY row_number() OVER (PARTITION BY trecho_id ORDER BY tempo_s DESC) = 1)
SELECT u.trecho_id, CAST(u.versao_gtfs AS STRING) AS versao_gtfs, u.shape_id, t.d_ini_m, t.d_fim_m
FROM uso u JOIN {GTFS_TRECHOS} t ON t.versao = u.versao_gtfs AND t.shape_id = u.shape_id AND t.trecho_seq = u.trecho_seq
"""

SQL_SHAPES = f"""
SELECT CAST(s.versao AS STRING) AS versao, s.shape_id, s.shape_pt_sequence, CAST(s.shape_pt_lat AS DOUBLE) AS shape_pt_lat,
       CAST(s.shape_pt_lon AS DOUBLE) AS shape_pt_lon, CAST(s.shape_dist_traveled AS DOUBLE) AS shape_dist_traveled
FROM {GTFS_SHAPES} s JOIN rep_shapes r ON CAST(s.versao AS STRING) = r.versao_gtfs AND s.shape_id = r.shape_id
"""


def pontos_trecho(rep, sh):
    """Pontos a cada ~PASSO_M ao longo do trecho, em metros, com o rumo local (minimo de 3 pontos por trecho)."""
    x, y = Transformer.from_crs(4326, CRS, always_xy=True).transform(sh.shape_pt_lon.values, sh.shape_pt_lat.values)
    sh = sh.assign(x=x, y=y).sort_values(["versao", "shape_id", "shape_pt_sequence"])
    tracados = dict(tuple(sh.groupby(["versao", "shape_id"])))
    partes = []
    for chave, trechos in rep.groupby(["versao_gtfs", "shape_id"]):
        s = tracados[chave]
        regua, sx, sy = s.shape_dist_traveled.values, s.x.values, s.y.values
        for t in trechos.itertuples():
            d = np.linspace(t.d_ini_m, t.d_fim_m, max(3, int(np.ceil((t.d_fim_m - t.d_ini_m) / PASSO_M)) + 1))
            dx = np.interp(d + 5, regua, sx) - np.interp(d - 5, regua, sx)
            dy = np.interp(d + 5, regua, sy) - np.interp(d - 5, regua, sy)
            partes.append(pd.DataFrame({"trecho_id": t.trecho_id, "x": np.interp(d, regua, sx), "y": np.interp(d, regua, sy),
                                        "rumo": np.arctan2(dy, dx)}))
    return pd.concat(partes, ignore_index=True)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Juncao espacial

# COMMAND ----------

def casar(pontos, rumo, linhas, raio):
    """Para cada ponto, a linha mais proxima a ate `raio` com rumo parecido, sem olhar o sentido. Colunas: i (ponto), j (linha)."""
    g = linhas.geometry.values
    i, j = linhas.sindex.query(pontos, predicate="dwithin", distance=raio)
    d = shapely.distance(pontos[i], g[j])
    s = shapely.line_locate_point(g[j], pontos[i])
    a = shapely.line_interpolate_point(g[j], np.maximum(s - 5, 0))
    b = shapely.line_interpolate_point(g[j], s + 5)
    rumo_linha = np.arctan2(shapely.get_y(b) - shapely.get_y(a), shapely.get_x(b) - shapely.get_x(a))
    dif = np.abs((rumo[i] - rumo_linha + np.pi) % (2 * np.pi) - np.pi)
    ok = np.minimum(dif, np.pi - dif) <= np.radians(RUMO_MAX)
    return pd.DataFrame({"i": i[ok], "j": j[ok], "d": d[ok]}).sort_values("d").drop_duplicates("i")


def dias_alagamento(pt, ocorr, raio):
    """Dias distintos com ocorrencia a ate `raio` de algum ponto do trecho."""
    perto = cKDTree(pt[["x", "y"]].values).query_ball_point(np.c_[ocorr.geometry.x, ocorr.geometry.y], r=raio)
    n = [len(v) for v in perto]
    pares = pd.DataFrame({"trecho_id": pt.trecho_id.values[np.concatenate(perto).astype(int)],
                          "data": np.repeat(ocorr.data.values, n)})
    return pares.drop_duplicates().groupby("trecho_id").size()


def atributos(pt, via, faixa, corredor, ocorr, comprimento):
    pt = pt.copy()
    pontos, rumo = shapely.points(pt.x.values, pt.y.values), pt.rumo.values

    c = casar(pontos, rumo, via, RAIO_VIA)
    classe = np.full(len(pt), "SEM_CLASSE", dtype=object)
    classe[c.i.values] = via.cvc_classe.values[c.j.values]
    pt["classe"] = classe
    frac = pt.groupby("trecho_id").classe.value_counts(normalize=True).unstack(fill_value=0.0)
    inf = frac.rename(columns=lambda x: "frac_" + x.lower())
    for coluna in ("frac_vtr", "frac_rodovia", "frac_arterial", "frac_coletora", "frac_local", "frac_sem_classe"):
        assert coluna in inf, coluna
    inf["classe_dominante"] = frac.idxmax(axis=1)

    c = casar(pontos, rumo, faixa, RAIO_FAIXA)
    for coluna, valores in [("faixa", np.ones(len(c), bool)), ("faixa_longa", faixa.horas.values[c.j.values] >= FAIXA_LONGA_H),
                            ("faixa_dupla", faixa.via_dupla.values[c.j.values])]:
        pt[coluna] = False
        pt.iloc[c.i.values, pt.columns.get_loc(coluna)] = valores
    c = casar(pontos, rumo, corredor, RAIO_CORREDOR)
    pt["corredor"] = False
    pt.iloc[c.i.values, pt.columns.get_loc("corredor")] = True

    g = pt.groupby("trecho_id")
    inf["frac_faixa"] = g.faixa.mean()
    inf["frac_faixa_longa"] = g.faixa_longa.mean()
    inf["frac_faixa_via_dupla"] = g.faixa_dupla.mean()
    inf["frac_corredor"] = g.corredor.mean()
    inf["n_pontos"] = g.size()
    for raio in RAIOS_ALAG:
        inf[f"dias_alag_{raio}m"] = dias_alagamento(pt, ocorr, raio).reindex(inf.index).fillna(0).astype(int)

    anos = (pd.Timestamp(INICIO_ANALISE) - pd.Timestamp(INICIO_ALAG)).days / 365.25
    r = max(RAIOS_ALAG)
    area_km2 = (2 * r * comprimento.reindex(inf.index) + np.pi * r ** 2) / 1e6     # faixa em volta do trecho + as duas pontas
    inf["alag_dias_km2_ano"] = inf[f"dias_alag_{r}m"] / area_km2 / anos
    return inf.reset_index()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Calcular e gravar

# COMMAND ----------

manifesto = preparar(ORIGEM, TMP)
via, faixa, corredor, ocorr = ler_camadas(TMP, manifesto)
print(f"{len(via):,} vias; {len(faixa):,} faixas exclusivas; {len(corredor)} corredores em operacao; "
      f"{len(ocorr):,} alagamentos em {ocorr.data.nunique():,} dias, ate {ocorr.data.max()}")

tr = spark.table(TRECHO).select("trecho_id", "lat", "lon", "nome_de", "nome_ate", "comprimento_m", "horas_onibus", "v_kmh_media",
                                "f_atipico").toPandas().set_index("trecho_id")
rep = spark.sql(SQL_REPRESENTANTE).toPandas()
spark.createDataFrame(rep[["versao_gtfs", "shape_id"]].drop_duplicates()).createOrReplaceTempView("rep_shapes")
sh = spark.sql(SQL_SHAPES).toPandas()

pt = pontos_trecho(rep, sh)
inf = atributos(pt, via, faixa, corredor, ocorr, tr.comprimento_m)
inf["versao_infra"] = VERSAO
inf = inf.merge(rep[["trecho_id", "versao_gtfs", "shape_id"]], on="trecho_id")
spark.createDataFrame(inf).write.mode("overwrite").option("overwriteSchema", True).saveAsTable(INFRA)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Checagens (falham o run)
# MAGIC
# MAGIC 1. Um trecho por linha, e quase todos os trechos da gold presentes (≥ 99,9%).
# MAGIC 2. As fracoes de classe somam 1 em cada trecho.
# MAGIC 3. Pelo menos 95% dos pontos caem numa via classificada.
# MAGIC 4. **Comparacao com um dado independente:** as classes vem da CET e a velocidade vem dos onibus. Se a juncao estiver certa,
# MAGIC    a velocidade segue a hierarquia viaria: expressa (VTR + rodovia) > arterial > coletora > local.

# COMMAND ----------

def validar(inf, tr):
    problemas = []
    if inf.trecho_id.duplicated().any():
        problemas.append("trecho repetido")
    if len(inf) / len(tr) < MIN_TRECHOS:
        problemas.append(f"so {len(inf):,} de {len(tr):,} trechos")

    fracoes = ["frac_vtr", "frac_rodovia", "frac_arterial", "frac_coletora", "frac_local", "frac_sem_classe"]
    if (inf[fracoes].sum(axis=1) - 1).abs().max() > 1e-9:
        problemas.append("fracoes de classe nao somam 1")
    com_classe = 1 - np.average(inf.frac_sem_classe, weights=inf.n_pontos)
    if com_classe < MIN_PONTOS_COM_CLASSE:
        problemas.append(f"so {100 * com_classe:.1f}% dos pontos com classe")

    x = inf.merge(tr, left_on="trecho_id", right_index=True)
    x = x[~x.f_atipico]
    grupo = x.classe_dominante.replace({"VTR": "EXPRESSA", "RODOVIA": "EXPRESSA"})
    v = (x.v_kmh_media * x.horas_onibus).groupby(grupo).sum() / x.horas_onibus.groupby(grupo).sum()
    if not v["EXPRESSA"] > v["ARTERIAL"] > v["COLETORA"] > v["LOCAL"]:
        problemas.append(f"velocidade fora da hierarquia viaria: {v.round(1).to_dict()}")
    return problemas, com_classe, x


problemas, com_classe, x = validar(inf, tr)
assert not problemas, "\n".join(problemas)
print(f"ok: {len(inf):,} trechos; {100 * com_classe:.1f}% dos pontos com classe de via")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Resultado
# MAGIC
# MAGIC Sem os trechos atipicos. `horas_mil` = milhares de horas de onibus; velocidade media ponderada por elas.

# COMMAND ----------

def relatorio(x):
    pd.set_option("display.width", 200, "display.max_columns", 30, "display.max_rows", 200, "display.max_colwidth", 44)
    def linha(g):
        return pd.Series({"trechos": len(g), "km": g.comprimento_m.sum() / 1000, "horas_mil": g.horas_onibus.sum() / 1000,
                          "v_kmh": np.average(g.v_kmh_media, weights=g.horas_onibus)})

    print(x.groupby("classe_dominante")[["comprimento_m", "horas_onibus", "v_kmh_media"]].apply(linha).round(1).to_string())
    print("\nfaixa e corredor (trecho com pelo menos metade do comprimento)")
    grupos = {"corredor": x.frac_corredor >= 0.5, "faixa, sem corredor": (x.frac_faixa >= 0.5) & (x.frac_corredor < 0.5),
              "faixa longa, sem corredor": (x.frac_faixa_longa >= 0.5) & (x.frac_corredor < 0.5),
              "faixa em via de mao dupla": x.frac_faixa_via_dupla >= 0.5,
              "sem faixa nem corredor": (x.frac_faixa < 0.1) & (x.frac_corredor < 0.1)}
    print(pd.DataFrame({k: linha(x[m]) for k, m in grupos.items()}).T.round(1).to_string())
    print("\nhistorico de alagamento")
    print(pd.Series({"com alagamento a 100 m": (x.dias_alag_100m > 0).mean(), "com alagamento a 50 m": (x.dias_alag_50m > 0).mean(),
                     "dias a 100 m, p50": x.dias_alag_100m.median(), "p90": x.dias_alag_100m.quantile(0.9),
                     "p99": x.dias_alag_100m.quantile(0.99), "max": x.dias_alag_100m.max()}).round(3).to_string())
    print("\ntrechos com mais dias de alagamento a 100 m")
    print(x.sort_values("dias_alag_100m", ascending=False)[["nome_de", "nome_ate", "dias_alag_100m", "dias_alag_50m",
                                                            "classe_dominante"]].head(15).to_string(index=False))


relatorio(x)

fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 7), sharex=True, sharey=True)
for classe, cor in [("LOCAL", "#c8c8c8"), ("COLETORA", "#7fb3d5"), ("ARTERIAL", "#1b4f72"), ("RODOVIA", "#d35400"), ("VTR", "#d35400")]:
    g = x[x.classe_dominante == classe]
    a1.scatter(g.lon, g.lat, s=0.6, color=cor, label=classe)
a1.set_title("classe de via")
a1.legend(markerscale=8)
a2.scatter(x.lon, x.lat, s=0.3, color="#d8d8d8")
g = x[x.dias_alag_100m > 0].sort_values("dias_alag_100m")
pontos = a2.scatter(g.lon, g.lat, s=1.2, c=np.log10(g.dias_alag_100m), cmap="viridis")
a2.set_title("dias de alagamento a 100 m (2013-2026, log10)")
fig.colorbar(pontos, ax=a2, shrink=0.6)
plt.show()

# COMMAND ----------

# MAGIC %run ./metadados

# COMMAND ----------

aplicar_metadados(INFRA)
aplicar_objetos()
