"""Roda a logica do notebook 13 sem gravar nada, com as consultas e funcoes exatamente como estao no notebook.

Uso: python testa_13.py PASTA [REPS] [METADES]
PASTA tem p13_pos.parquet, p12_chuva.parquet, p12_trecho.parquet e t12_trecho.parquet, com o resultado das consultas por trecho.
As consultas de grupo rodam no warehouse.
"""
import sys
import time

import pandas as pd

from dbsql import q

pasta = sys.argv[1]
src = open(r"C:\Users\gabir\Documents\volbus\files\notebooks\13_gold_recuperacao_trecho.py", encoding="utf-8").read()
ns = {}
imports = src[src.index("import matplotlib.pyplot as plt"):src.index("spark.conf.set")]
exec(chr(10).join(x for x in imports.splitlines() if "pyspark" not in x), ns)
exec(src[src.index('RAZAO = "onibus'):src.index("# COMMAND ----------\n\n# MAGIC %md\n# MAGIC ## 1. Agregar")], ns)
exec(src[src.index('HORA_FIM = "hour'):src.index("# COMMAND ----------\n\n# MAGIC %md\n# MAGIC ## 2. Por trecho")], ns)
exec(src[src.index("def moderar(s2, gl, x):"):src.index("# COMMAND ----------\n\n# MAGIC %md\n# MAGIC ## 5. Calcular")], ns)
exec(src[src.index("def validar(res, g, janelas_cidade):"):src.index("problemas = validar(res")], ns)
exec(src[src.index("def relatorio(res):"):src.index('relatorio(res)\n\nfig, eixos')], ns)
if len(sys.argv) > 2:
    ns["REPS"] = int(sys.argv[2])
if len(sys.argv) > 3:
    ns["METADES"] = int(sys.argv[3])

pos = pd.read_parquet(f"{pasta}/p13_pos.parquet")
pos = pos[pos.classe_evento.isin(["moderada", "forte"])]
ch = pd.read_parquet(f"{pasta}/p12_chuva.parquet")
ch = ch[ch.classe_chuva.isin(["moderada", "forte", "muito_forte"])]
tr = pd.read_parquet(f"{pasta}/p12_trecho.parquet")
tr = tr.merge(pd.read_parquet(f"{pasta}/t12_trecho.parquet")[["trecho_id", "grupo_critico"]], on="trecho_id", how="left")

g = q(ns["SQL_GRUPOS"], timeout_s=1500)
for c in ("tau_min", "d", "e", "janelas"):
    g[c] = pd.to_numeric(g[c])
n_trechos = q(ns["SQL_N_TRECHOS"], timeout_s=600)
n_trechos["n_trechos"] = pd.to_numeric(n_trechos.n_trechos)
janelas_cidade = float(q(ns["SQL_CIDADE"], timeout_s=300).iloc[0, 0])
print(len(g), "linhas nos grupos;", int(g.janelas.sum()), "janelas; cidade:", int(janelas_cidade))

t0 = time.time()
res = ns["calcular"](pos, ch, tr, g, n_trechos)
print(f"{time.time() - t0:.0f} s")
print("problemas:", ns["validar"](res, g, janelas_cidade))
ns["relatorio"](res)
print(res["trecho"].dtypes.astype(str).to_dict())
for k in ("trecho", "tempos", "curvas", "validacao"):
    res[k].to_parquet(f"{pasta}/t13_{k}.parquet")
