"""
Consolida os CSVs exportados do SIBH (telemetria de chuva) numa base unica,
aplica controle de qualidade por posto e gera:

  chuva_10min.parquet    serie consolidada (so postos aprovados)
  qc_postos.csv          relatorio de qualidade de todos os postos
  postos_sem_dado.txt    IDs pedidos que nao voltaram (para repescagem)

Uso:
    python consolida_chuva.py --entrada ./csvs_sibh --ids sp_ids.txt

Criterios de aprovacao (ajustaveis nas constantes abaixo):
  - total no periodo dentro de [MM_MIN, MM_MAX]
  - dado em pelo menos DIAS_MIN dias
  - nenhuma lacuna maior que GAP_MAX_H horas
  - dentro do municipio de Sao Paulo
"""

import argparse
import glob
from pathlib import Path

import pandas as pd

# Setembro de 2026 foi recorde (~250 mm so na primeira quinzena, estacao
# Mirante de Santana). Um posto integro no periodo 15/08-21/09 fica bem acima
# de 100 mm. Abaixo disso e sensor quebrado; acima de 600 mm e suspeito.
MM_MIN = 100.0
MM_MAX = 600.0
DIAS_MIN = 34
GAP_MAX_H = 24.0

MUNICIPIO_OK = "são paulo"


def carregar(pasta: str) -> pd.DataFrame:
    arquivos = sorted(glob.glob(str(Path(pasta) / "*.csv")))
    if not arquivos:
        raise SystemExit(f"nenhum CSV em {pasta}")
    partes = []
    for a in arquivos:
        d = pd.read_csv(a, dtype={"Prefixo": str})
        d["arquivo_origem"] = Path(a).name
        partes.append(d)
        print(f"  {Path(a).name:32} {len(d):7,} linhas  {d.Prefixo.nunique():3} postos")
    d = pd.concat(partes, ignore_index=True)
    d["Data"] = pd.to_datetime(d["Data"], format="%Y/%m/%d %H:%M")
    d["Valor"] = pd.to_numeric(d["Valor"], errors="coerce")
    d["municipio"] = d["Nome"].str.extract(r"^([^(]+)\(")[0].str.strip().str.lower()

    antes = len(d)
    d = d.drop_duplicates(["Prefixo", "Data"])
    print(f"\n  duplicatas removidas: {antes - len(d):,}")
    return d.sort_values(["Prefixo", "Data"]).reset_index(drop=True)


def avaliar(d: pd.DataFrame) -> pd.DataFrame:
    inicio, fim = d.Data.min(), d.Data.max()
    total_dias = (fim - inicio).total_seconds() / 86400

    linhas = []
    for (pref, nome), g in d.groupby(["Prefixo", "Nome"], sort=False):
        dt_min = g.Data.diff().dt.total_seconds().dropna() / 60
        cad = float(dt_min.median()) if len(dt_min) else float("nan")
        gap_h = float(dt_min.max() / 60) if len(dt_min) else float("nan")
        mm = float(g.Valor.sum())
        dias = int(g.Data.dt.date.nunique())
        mun = g.municipio.iloc[0]

        if mun != MUNICIPIO_OK:
            status = "fora_municipio"
        elif mm < MM_MIN:
            status = "quebrado_mm_baixo"
        elif mm > MM_MAX:
            status = "suspeito_mm_alto"
        elif dias < DIAS_MIN:
            status = "lacuna_dias"
        elif gap_h > GAP_MAX_H:
            status = "lacuna_longa"
        else:
            status = "ok"

        linhas.append({
            "prefixo": pref, "nome": nome, "municipio": mun,
            "cadencia_min": cad, "leituras": len(g), "dias_com_dado": dias,
            "maior_lacuna_h": round(gap_h, 1), "mm_total": round(mm, 1),
            "max_intervalo_mm": float(g.Valor.max()),
            "status": status,
        })

    qc = pd.DataFrame(linhas).sort_values(["status", "mm_total"], ascending=[True, False])
    print(f"\n  periodo: {inicio} -> {fim} ({total_dias:.1f} dias)")
    print(f"\n{qc.status.value_counts().to_string()}")
    return qc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--entrada", default="./csvs_sibh")
    ap.add_argument("--ids", default=None, help="lista de IDs pedidos, separados por ;")
    ap.add_argument("--saida", default=".")
    args = ap.parse_args()
    out = Path(args.saida)
    out.mkdir(parents=True, exist_ok=True)

    print("Carregando:")
    d = carregar(args.entrada)
    qc = avaliar(d)
    qc.to_csv(out / "qc_postos.csv", index=False)

    aprovados = set(qc.loc[qc.status == "ok", "prefixo"])
    serie = d[d.Prefixo.isin(aprovados)][["Prefixo", "Nome", "Data", "Valor"]].rename(
        columns={"Prefixo": "prefixo", "Nome": "nome", "Data": "instante_local", "Valor": "mm"}
    )
    try:
        serie.to_parquet(out / "chuva_10min.parquet", index=False)
        nome_saida = "chuva_10min.parquet"
    except ImportError:
        # sem pyarrow instalado: cai para CSV (pip install pyarrow para parquet)
        serie.to_csv(out / "chuva_10min.csv", index=False)
        nome_saida = "chuva_10min.csv"
    print(f"\n  gravado: {nome_saida} — {len(serie):,} linhas, {len(aprovados)} postos aprovados")

    if args.ids:
        pedidos = [x.strip() for x in Path(args.ids).read_text(encoding="utf-8").split(";") if x.strip()]
        vieram = set(d.Prefixo)
        faltam = [x for x in pedidos if x not in vieram]
        (out / "postos_sem_dado.txt").write_text(";".join(faltam), encoding="utf-8")
        print(f"  pedidos: {len(pedidos)} | vieram: {len(vieram & set(pedidos))} | faltam: {len(faltam)}")


if __name__ == "__main__":
    main()
