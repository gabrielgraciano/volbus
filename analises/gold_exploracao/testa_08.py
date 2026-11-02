import re, numpy as np, pandas as pd
from dbsql import q
src = open(r"C:\Users\gabir\Documents\volbus\files\notebooks\08_gold_base.py", encoding="utf-8").read()
ns = {"np": np, "pd": pd}
# constantes
exec(src[src.index('VEL = "onibus'):src.index("# COMMAND ----------\n\n# MAGIC %md\n# MAGIC ## 1. Trechos")], ns)
# SQL e funcoes do passo 1
exec(src[src.index("SQL_TRECHO_BASE = f"):src.index("tr = preparar_trechos(spark.sql")], ns)
for nome in ["SQL_BASE", "SQL_ROLL", "SQL_CIDADE", "SQL_SLOTS_EVENTO", "SQL_EVENTO", "SQL_FINAL"]:
    m = re.search(rf'^{nome} = (f?""".*?""")', src, re.S | re.M)
    ns[nome] = eval(m.group(1), ns)
# ---- python: trechos e postos
tr = ns["preparar_trechos"](q(ns["SQL_TRECHO_BASE"], timeout_s=900)); po = q(ns["SQL_POSTOS"])
tp = ns["atribuir_postos"](tr, po)
print(len(tr), "trechos |", len(tp), "ligacoes | atipicos", int(tr.f_atipico.sum()), f"({100*tr.f_atipico.mean():.1f}%, {100*tr.loc[tr.f_atipico,'horas_onibus'].sum()/tr.horas_onibus.sum():.1f}% horas)")
g = tp.groupby("trecho_id").agg(s=("peso","sum"), n=("peso","size"), d=("dist_km","max"), f=("fonte_chuva","first"))
print("pesos ok:", bool(np.allclose(g.s,1)), "| n max:", g.n.max(), "| d max:", round(g.d.max(),2))
print(g.groupby(["f","n"]).size().to_string()); print("sem posto:", len(tr)-len(g), "| ids repetidos:", tr.trecho_id.duplicated().sum())
print("peso do 1o posto (mediana):", round(tp[tp.ordem==1].peso.median(),2))
# ---- SQL: tudo composto como CTEs
cte = "WITH " + ",\n".join(f"{n} AS ({ns[s]})" for n, s in [("chuva_base","SQL_BASE"),("chuva_roll","SQL_ROLL"),("cidade","SQL_CIDADE"),("slots_evento","SQL_SLOTS_EVENTO"),("evento_v","SQL_EVENTO"),("final","SQL_FINAL")])
a = q(cte + """
SELECT count(*) linhas, count(DISTINCT prefixo, slot_utc) unicos, round(sum(mm),1) mm_total,
       sum(CAST(chove AND NOT em_evento AS INT)) chove_fora_evento,
       sum(CAST(seco_estrito AND NOT seco_3h AS INT)) inconsistente,
       round(100*avg(CASE WHEN rede='daee' AND dt>='2026-08-25' THEN CAST(chove AS DOUBLE) END),2) pct_chove,
       round(100*avg(CASE WHEN rede='daee' AND dt>='2026-08-25' THEN CAST(em_evento AS DOUBLE) END),2) pct_evento,
       round(100*avg(CASE WHEN rede='daee' AND dt>='2026-08-25' THEN CAST(seco_3h AS DOUBLE) END),2) pct_seco3h,
       round(100*avg(CASE WHEN rede='daee' AND dt>='2026-08-25' THEN CAST(seco_estrito AS DOUBLE) END),2) pct_estrito,
       min(min_desde_fim) min_mdf, max(min_desde_fim) max_mdf, sum(CAST(em_evento AND min_desde_fim IS NOT NULL AS INT)) evento_e_pos
FROM final""", timeout_s=1200)
print(a.T.to_string())
b = q(cte + "SELECT count(*) n, count(DISTINCT evento_id) ids, min(seco_depois_min) min_gap, round(sum(mm_total),0) mm, sum(CAST(mm_total IS NULL AS INT)) mm_null, round(max(pico_mm_h_30),1) pico30, round(max(pico_mm_h_10),1) pico10, round(100*avg(CAST(relevante AS DOUBLE)),1) pct_rel FROM evento_v", timeout_s=1200)
print(b.T.to_string())
s = q("SELECT round(sum(c.mm),1) mm_silver, count(*) n FROM onibus.silver.chuva_10min c JOIN onibus.silver.postos p USING (prefixo) WHERE p.status='ok' AND p.duplicata_de IS NULL")
print(s.to_string(index=False))
c = q(cte + """SELECT slot_sp, mm, mm_h_30, mm_h_60, mm_3h, seco_3h, seco_estrito, round(frac_cidade_chuva,2) frac, evento_id, em_evento, min_desde_fim, min_ate_proximo
FROM final WHERE prefixo='1001635' AND slot_sp BETWEEN '2026-09-12 13:00:00' AND '2026-09-12 18:30:00' ORDER BY slot_sp""", timeout_s=900)
print(c.iloc[::3].to_string(index=False))
