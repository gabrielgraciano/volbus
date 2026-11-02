"""Roda a logica do notebook 11 no PC, sem gravar nada, com as funcoes exatamente como estao no notebook.

Uso, com um python que tenha geopandas (com -I, para nao carregar modulos da pasta dos dados):
    python -I testa_11.py PASTA_DOS_ARQUIVOS PASTA_DOS_PARQUETS
PASTA_DOS_ARQUIVOS tem os arquivos do volume infra/versao=... e manifesto.csv. PASTA_DOS_PARQUETS tem
p11_rep.parquet, p11_shapes.parquet e p11_trecho.parquet, com o resultado das consultas do notebook.
"""
import sys

import pandas as pd

origem, dados = sys.argv[1], sys.argv[2]
src = open(sys.argv[3] if len(sys.argv) > 3 else r"C:\Users\gabir\Documents\volbus\files\notebooks\11_gold_trecho_infra.py",
           encoding="utf-8").read()
ns = {}
exec(src[src.index("import csv"):src.index("# COMMAND ----------\n\n# MAGIC %md\n# MAGIC ## 1. Arquivos")], ns)
exec(src[src.index("def preparar(origem, tmp):"):src.index("# COMMAND ----------\n\n# MAGIC %md\n# MAGIC ## 2. Tracado")], ns)
exec(src[src.index("def pontos_trecho(rep, sh):"):src.index("# COMMAND ----------\n\n# MAGIC %md\n# MAGIC ## 3. Juncao")], ns)
exec(src[src.index("def casar(pontos, rumo, linhas, raio):"):src.index("# COMMAND ----------\n\n# MAGIC %md\n# MAGIC ## 4. Calcular")], ns)
exec(src[src.index("def validar(inf, tr):"):src.index("problemas, com_classe, x = validar")], ns)
exec(src[src.index("def relatorio(x):"):src.index("relatorio(x)\n\nfig")], ns)

tmp = dados + "/tmp_infra"
manifesto = ns["preparar"](origem, tmp)
via, faixa, corredor, ocorr = ns["ler_camadas"](tmp, manifesto)
print(f"{len(via):,} vias; {len(faixa):,} faixas; {len(corredor)} corredores; {len(ocorr):,} alagamentos em "
      f"{ocorr.data.nunique():,} dias, ate {ocorr.data.max()}")
print("horas de faixa:", faixa.horas.describe().round(1).to_dict())

tr = pd.read_parquet(f"{dados}/p11_trecho.parquet").set_index("trecho_id")
rep = pd.read_parquet(f"{dados}/p11_rep.parquet")
sh = pd.read_parquet(f"{dados}/p11_shapes.parquet")
for c in ("d_ini_m", "d_fim_m"):
    rep[c] = pd.to_numeric(rep[c])
rep["versao_gtfs"] = rep.versao_gtfs.astype(str).str[:10]
sh["versao"] = sh.versao.astype(str).str[:10]

pt = ns["pontos_trecho"](rep, sh)
inf = ns["atributos"](pt, via, faixa, corredor, ocorr, tr.comprimento_m)
print(inf.dtypes.astype(str).to_dict())
problemas, com_classe, x = ns["validar"](inf, tr)
print("problemas:", problemas)
print(f"{len(inf):,} de {len(tr):,} trechos; {100 * com_classe:.1f}% dos pontos com classe")
ns["relatorio"](x)
print(inf[["frac_faixa", "frac_faixa_longa", "frac_faixa_via_dupla", "frac_corredor", "alag_dias_km2_ano"]].describe().round(3).to_string())
inf.to_parquet(f"{dados}/p11_infra.parquet")
