"""Roda a logica do notebook 10 no warehouse, sem gravar nada, com as consultas e funcoes exatamente como estao no notebook.

Enquanto o 09 corrigido nao rodou, `obs_razao` nao tem `pico_evento_mm_h`: o teste calcula essa coluna na hora.
"""
import sys

import numpy as np
import pandas as pd

from dbsql import q

src = open(r"C:\Users\gabir\Documents\volbus\files\notebooks\10_gold_efeito_cidade.py", encoding="utf-8").read()
ns = {"np": np, "pd": pd}
exec(src[src.index('RAZAO = "onibus'):src.index("# COMMAND ----------\n\n# MAGIC %md\n# MAGIC ## 1. Agregar")], ns)
exec(src[src.index("def periodo_sql(hora):"):src.index("# COMMAND ----------\n\n# MAGIC %md\n# MAGIC ## 2. Funcoes")], ns)
exec(src[src.index("def pesos(dias):"):src.index("# COMMAND ----------\n\n# MAGIC %md\n# MAGIC ## 3. Calcular")], ns)
efeito, contrastes, recuperacao, quadro = ns["efeito"], ns["contrastes"], ns["recuperacao"], ns["quadro"]

sql_rec = ns["SQL_RECUPERACAO"]
if "--com-pico" not in sys.argv:
    p = """(SELECT r.*, p.pico AS pico_evento_mm_h FROM onibus.gold.obs_razao r JOIN (
      SELECT tp.trecho_id, ch.slot_sp,
             max(CASE WHEN ch.em_evento OR ch.min_desde_fim <= 180 THEN e.pico_mm_h_30 END) pico
      FROM onibus.gold.trecho_posto tp JOIN onibus.gold.chuva_posto_10min ch USING (prefixo)
      LEFT JOIN onibus.gold.evento_chuva e ON e.evento_id = ch.evento_id
      WHERE ch.dt >= '2026-08-25' AND ch.min_desde_fim <= 180 GROUP BY 1, 2) p
      ON p.trecho_id = r.trecho_id AND p.slot_sp = r.janela_sp)"""
    sql_rec = sql_rec.replace("FROM onibus.gold.obs_razao o", f"FROM {p} o")

a = q(ns["SQL_EFEITO"], timeout_s=2400)
b = q(sql_rec, timeout_s=2400)
leads = q(ns["SQL_LEADS"], timeout_s=2400)
for df in (a, b, leads):
    for c in ("d", "e", "janelas", "tau_min"):
        if c in df:
            df[c] = pd.to_numeric(df[c])
# o tipo_dia ainda errado no obs atual: tira domingo e sabado que entraram em 'util'
if "--com-pico" not in sys.argv:
    fds = pd.to_datetime(a.dt).dt.dayofweek > 4
    a = a[~fds]
    b = b[pd.to_datetime(b.dt).dt.dayofweek <= 4]
    leads = leads[pd.to_datetime(leads.dt).dt.dayofweek <= 4]

pd.set_option("display.width", 220, "display.max_columns", 30, "display.max_rows", 300)
t_efeito, relativas, ponto = efeito(a, "tudo")
t_ate, _, _ = efeito(a[a.dt < ns["CORTE_1MIN"]], "ate_20_09")
t_desde, _, _ = efeito(a[a.dt >= ns["CORTE_1MIN"]], "desde_21_09")
print(a.dt.nunique(), "dias uteis;", a.janelas.sum(), "janelas KR1;", b.janelas.sum(), "janelas KR2")
print(quadro(t_efeito).to_string())
print(quadro(t_ate).to_string())
print(quadro(t_desde).to_string())
print(contrastes(relativas, ponto).round(3).to_string(index=False))
t_curvas, t_tempos = recuperacao(a, b, leads)
print(t_tempos.drop(columns="janelas").round(3).to_string(index=False))
print(t_curvas[t_curvas.classe_evento == "antecipacao"][["tau_min", "razao", "ic_inf", "ic_sup", "janelas"]].round(4).to_string(index=False))
print(t_curvas[t_curvas.periodo_fim == "tarde"].pivot(index="tau_min", columns="classe_evento", values="razao").round(3).to_string())

seco = ponto.xs("seco", level="classe_chuva")
print("seco:", seco.round(4).to_dict())
