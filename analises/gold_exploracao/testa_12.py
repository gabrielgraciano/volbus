"""Roda a logica do notebook 12 no PC, sem gravar nada, com as funcoes exatamente como estao no notebook.

Uso: python testa_12.py PASTA REPS
PASTA tem p12_chuva.parquet, p12_seco.parquet e p12_trecho.parquet, com o resultado das consultas do notebook.
"""
import sys
import time

import numpy as np
import pandas as pd

pasta, reps = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 100
src = open(r"C:\Users\gabir\Documents\volbus\files\notebooks\12_gold_efeito_trecho.py", encoding="utf-8").read()
ns = {}
imports = src[src.index("import numpy as np"):src.index('spark.conf.set')]
exec(chr(10).join(x for x in imports.splitlines() if "pyspark" not in x), ns)
exec(src[src.index('RAZAO = "onibus'):src.index("# COMMAND ----------\n\n# MAGIC %md\n# MAGIC ## 1. Agregar")], ns)
exec(src[src.index('PERIODO = """'):src.index("# COMMAND ----------\n\n# MAGIC %md\n# MAGIC ## 2. Estagio 1")], ns)
exec(src[src.index("def estagio1(ch, se, tr):"):src.index("ch = spark.sql(SQL_CHUVA)")], ns)
exec(src[src.index("def validar(res, ch, se, tr):"):src.index("problemas, rho_placebo = validar")], ns)
exec(src[src.index("def relatorio(res):"):src.index('relatorio(res)\n\ns = res["trecho"]')], ns)
ns["REPS"] = reps
if len(sys.argv) > 3:
    ns["METADES"] = int(sys.argv[3])

ch = pd.read_parquet(f"{pasta}/p12_chuva.parquet")
se = pd.read_parquet(f"{pasta}/p12_seco.parquet")
tr = pd.read_parquet(f"{pasta}/p12_trecho.parquet")
t0 = time.time()
res = ns["calcular"](ch, se, tr)
print(f"{time.time() - t0:.0f} s")
print("info:", {k: (round(v, 4) if isinstance(v, float) else v) for k, v in res["info"].items() if k != "pi"})
print("mistura:", {float(k): round(float(v), 3) for k, v in res["info"]["pi"].items()})
problemas, rho = ns["validar"](res, ch, se, tr)
print("problemas:", problemas, "| rho placebo:", round(rho, 3))

tr_ok = tr.set_index("trecho_id")
c_ = ch[ch.classe_chuva.isin(ns["CLASSES"]) & ch.trecho_id.isin(tr_ok.index)].assign(celula=lambda z: z.periodo + "/" + z.classe_chuva)
dias_ = sorted(set(c_.dt) | set(se.dt))
idx, th = ns["theta_em"](ns["matrizes"](res["t"], c_, se[se.trecho_id.isin(tr_ok.index)], dias_), np.ones(len(dias_)))
print("theta_em x estagio 1, dif max:", float(np.abs(th - res["t"].theta.values[idx]).max()), "| trechos", len(idx))
ns["relatorio"](res)
print(res["trecho"].dtypes.astype(str).to_dict())
res["trecho"].to_parquet(f"{pasta}/t12_trecho.parquet")
res["coefs"].to_parquet(f"{pasta}/t12_coefs.parquet")
res["grupos"].to_parquet(f"{pasta}/t12_grupos.parquet")
res["estabilidade"].to_parquet(f"{pasta}/t12_estab.parquet")
