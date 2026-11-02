"""Roda a logica do notebook 09 no warehouse, sem gravar nada, com as consultas exatamente como estao no notebook."""
import re
import sys

from dbsql import q

src = open(r"C:\Users\gabir\Documents\volbus\files\notebooks\09_gold_obs_base.py", encoding="utf-8").read()
ns = {}
exec(src[src.index('VEL = "onibus'):src.index("# COMMAND ----------\n\n# MAGIC %md\n# MAGIC ## 1. Observacoes")], ns)
exec(src[src.index("def media(col):"):src.index('SQL_OBS = f"""')], ns)
for nome in ["SQL_OBS", "SQL_LINHA_BASE", "SQL_AJUSTE_DIA_HORA", "SQL_AJUSTE_SEMANA"]:
    m = re.search(rf'^{nome} = (f?""".*?""")', src, re.S | re.M)
    ns[nome] = eval(m.group(1), ns)

de, ate = (sys.argv[1], sys.argv[2]) if len(sys.argv) > 2 else ("2026-09-07", "2026-09-27")
obs = ns["SQL_OBS"].replace(f"dt >= '{ns['INICIO']}'", f"dt BETWEEN '{de}' AND '{ate}'")
obs = obs.replace(f"ch.dt BETWEEN '{de}' AND '{ate}'", f"ch.dt BETWEEN '{de}' AND '{ate}'")
# recorte curto: reduz o minimo de janelas para a linha de base existir
base = ns["SQL_LINHA_BASE"].replace(str(ns["MIN_JANELAS_UTIL"]), "10").replace(str(ns["MIN_JANELAS_FDS"]), "6")
cte = f"WITH obs AS ({obs}), base AS ({base}), fator_dh AS ({ns['SQL_AJUSTE_DIA_HORA']}), fator_sem AS ({ns['SQL_AJUSTE_SEMANA']}),"
cte += """
r AS (SELECT o.*, b.v_base_ms, f.fator_dia_hora, s.fator_semana,
             o.tempo_s * b.v_base_ms * f.fator_dia_hora * s.fator_semana AS dist_esperada_m
      FROM obs o JOIN base b USING (trecho_id, grupo_dia, hora)
      JOIN fator_dh f USING (grupo_dia, dia_semana, hora) JOIN fator_sem s USING (semana))
"""
a = q(cte + """
SELECT classe_chuva, CASE WHEN hora BETWEEN 6 AND 9 THEN '1 manha' WHEN hora BETWEEN 16 AND 19 THEN '3 tarde'
                          WHEN hora BETWEEN 10 AND 15 THEN '2 meio' ELSE '4 noite' END periodo,
       round(sum(dist_m) / sum(dist_esperada_m), 3) razao, count(*) janelas, count(DISTINCT dt) dias
FROM r WHERE grupo_dia = 'util' GROUP BY 1, 2""", timeout_s=2400)
ordem = ["sem_dado", "seco", "transbordamento", "pos_chuva", "traco", "fraca", "moderada", "forte", "muito_forte"]
a["o"] = a.classe_chuva.map({c: i for i, c in enumerate(ordem)})
print(a.pivot(index=["o", "classe_chuva"], columns="periodo", values="razao").to_string())
print(a.groupby("classe_chuva").janelas.sum().to_string())
b = q(cte + """
SELECT 'total' k, '' v, round(sum(dist_m) / sum(dist_esperada_m), 4) r FROM r WHERE classe_chuva = 'seco'
UNION ALL SELECT 'dia_semana', CAST(dia_semana AS STRING), round(sum(dist_m) / sum(dist_esperada_m), 4) FROM r WHERE classe_chuva = 'seco' GROUP BY dia_semana
UNION ALL SELECT 'semana', CAST(semana AS STRING), round(sum(dist_m) / sum(dist_esperada_m), 4) FROM r WHERE classe_chuva = 'seco' GROUP BY semana
ORDER BY 1, 2""", timeout_s=2400)
print(b.to_string(index=False))
c = q(cte + """SELECT (SELECT count(*) FROM obs) n_obs, (SELECT count(*) FROM (SELECT DISTINCT trecho_id, janela_sp FROM obs)) unicos,
  (SELECT round(sum(tempo_s)) FROM obs) t_obs, (SELECT round(sum(tempo_s)) FROM r) t_r""", timeout_s=2400)
print(c.to_string(index=False), "| % tempo com base:", round(100 * c.t_r[0] / c.t_obs[0], 1))
