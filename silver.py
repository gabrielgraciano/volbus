"""
Camada silver: projeta posicoes do Olho Vivo nos shapes do GTFS
e deriva headway observado em pontos virtuais de medicao.

Ideia central
-------------
O shapes.txt da SPTrans ja traz `shape_dist_traveled`: a distancia acumulada,
em metros, de cada vertice desde o inicio da rota. Entao projetar um ponto GPS
no shape devolve direto "este onibus esta no metro X da linha" — que e a
coordenada unidimensional em que headway faz sentido.

Com isso, headway num ponto vira: quais veiculos cruzaram a marca X, e quando.
"""

from __future__ import annotations

import gzip
import json
import math
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

# Centro aproximado de Sao Paulo, usado como origem da projecao planar local.
LAT0 = -23.55
LON0 = -46.63
R_TERRA = 6_371_000.0

# Confirmado empiricamente em 2026-08-26 sobre 9.839 veiculos:
# entre os 647 grupos (c, sl) em que um sentido teve erro lateral 3x menor que
# o outro, a separacao foi de 294/294 e 353/353, sem um unico contraexemplo.
MAPA_SENTIDO = {1: "0", 2: "1"}

# As posicoes publicadas pela SPTrans ja vem projetadas sobre a polilinha da
# rota (99,8% com erro lateral exatamente 0,00 m; maximo observado 1,54 m).
# Consequencia: filtro por erro lateral nao serve como controle de qualidade —
# use saltos de distancia e movimento para tras.
ERRO_LATERAL_ESPERADO_M = 2.0


# --------------------------------------------------------------------------
# Geometria
# --------------------------------------------------------------------------

def para_xy(lat, lon):
    """
    Equirretangular local: converte lat/lon em metros num plano tangente a SP.

    Em escala urbana (~50 km) o erro fica abaixo de 0,1%, o que e irrelevante
    perto da propria incerteza do GPS. Muito mais barato que reprojetar.
    """
    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)
    x = np.radians(lon - LON0) * R_TERRA * math.cos(math.radians(LAT0))
    y = np.radians(lat - LAT0) * R_TERRA
    return x, y


class Shape:
    """Um shape do GTFS, preparado para projecao vetorizada."""

    def __init__(self, shape_id: str, lat, lon, dist):
        ordem = np.argsort(dist)
        self.shape_id = shape_id
        self.dist = np.asarray(dist, dtype=float)[ordem]
        x, y = para_xy(np.asarray(lat)[ordem], np.asarray(lon)[ordem])
        self.xy = np.column_stack([x, y])

        # Segmentos: origem, vetor e comprimento ao quadrado.
        self.a = self.xy[:-1]
        self.v = self.xy[1:] - self.xy[:-1]
        self.v2 = np.einsum("ij,ij->i", self.v, self.v)
        self.v2[self.v2 == 0] = 1e-12  # vertices duplicados nao quebram a conta
        self.comprimento = float(self.dist[-1])

    def projetar(self, lat, lon):
        """
        Projeta pontos no shape.

        Retorna (dist_ao_longo_m, erro_lateral_m). O erro lateral e o quanto o
        ponto esta fora da rota. Como a SPTrans ja publica as posicoes sobre a
        rota, no shape certo ele fica ~0 e NAO serve como filtro de qualidade
        (ver ERRO_LATERAL_ESPERADO_M). Serve para comparar shapes: valor alto
        indica shape errado (ex.: sentido trocado).
        """
        px, py = para_xy(lat, lon)
        p = np.column_stack([px, py])

        # Para cada ponto, projeta em TODOS os segmentos de uma vez.
        # d[i, j] = posicao do ponto i no segmento j, limitada a [0, 1].
        dx = p[:, None, 0] - self.a[None, :, 0]
        dy = p[:, None, 1] - self.a[None, :, 1]
        t = (dx * self.v[None, :, 0] + dy * self.v[None, :, 1]) / self.v2[None, :]
        t = np.clip(t, 0.0, 1.0)

        proj_x = self.a[None, :, 0] + t * self.v[None, :, 0]
        proj_y = self.a[None, :, 1] + t * self.v[None, :, 1]
        d2 = (p[:, None, 0] - proj_x) ** 2 + (p[:, None, 1] - proj_y) ** 2

        melhor = np.argmin(d2, axis=1)
        idx = np.arange(len(p))
        t_melhor = t[idx, melhor]

        dist_ao_longo = (self.dist[melhor]
                         + t_melhor * (self.dist[melhor + 1] - self.dist[melhor]))
        erro_lateral = np.sqrt(d2[idx, melhor])
        return dist_ao_longo, erro_lateral


# --------------------------------------------------------------------------
# Carga do GTFS
# --------------------------------------------------------------------------

def carregar_gtfs(pasta: str | Path) -> dict[str, pd.DataFrame]:
    pasta = Path(pasta)
    ler = lambda n: pd.read_csv(pasta / n, dtype=str)

    gtfs = {
        "routes": ler("routes.txt"),
        "trips": ler("trips.txt"),
        "frequencies": ler("frequencies.txt"),
        "stops": ler("stops.txt"),
    }
    gtfs["shapes"] = pd.read_csv(
        pasta / "shapes.txt",
        dtype={"shape_id": str, "shape_pt_sequence": int},
    )
    for c in ("shape_pt_lat", "shape_pt_lon", "shape_dist_traveled"):
        gtfs["shapes"][c] = pd.to_numeric(gtfs["shapes"][c])

    gtfs["frequencies"]["headway_secs"] = pd.to_numeric(
        gtfs["frequencies"]["headway_secs"]
    )
    return gtfs


def construir_shapes(gtfs: dict[str, pd.DataFrame]) -> dict[str, Shape]:
    """Um objeto Shape por shape_id, pronto para projetar."""
    saida = {}
    for sid, g in gtfs["shapes"].groupby("shape_id", sort=False):
        saida[sid] = Shape(
            sid, g["shape_pt_lat"].to_numpy(),
            g["shape_pt_lon"].to_numpy(),
            g["shape_dist_traveled"].to_numpy(),
        )
    return saida


def mapa_trip(gtfs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """route_id + direction_id -> trip_id e shape_id."""
    t = gtfs["trips"][["route_id", "direction_id", "trip_id", "shape_id"]].copy()
    # Uma rota+sentido pode ter mais de um shape (variantes). Fica o primeiro
    # por trip_id, de forma deterministica, mas avisamos quantos casos ha.
    n_shapes = t.groupby(["route_id", "direction_id"])["shape_id"].nunique()
    n_ambiguos = int((n_shapes > 1).sum())
    if n_ambiguos:
        warnings.warn(f"{n_ambiguos} pares rota+sentido com mais de um shape_id; "
                      "usando o do menor trip_id")
    t = t.sort_values("trip_id")
    return t.drop_duplicates(["route_id", "direction_id"])


# --------------------------------------------------------------------------
# Leitura do bronze
# --------------------------------------------------------------------------

def _achatar_payload(payload: dict, coletado_em: str) -> list[dict]:
    """Payload cru da API (bronze v2) -> uma linha por veiculo."""
    hr = payload.get("hr")
    linhas = []
    for linha in payload.get("l") or []:
        for v in linha.get("vs") or []:
            linhas.append({
                "ta": v.get("ta"), "p": None if v.get("p") is None else str(v.get("p")),
                "cl": linha.get("cl"), "sl": linha.get("sl"), "c": linha.get("c"),
                "lt0": linha.get("lt0"), "lt1": linha.get("lt1"),
                "py": v.get("py"), "px": v.get("px"), "a": v.get("a"),
                "hr": hr, "coletado_em": coletado_em,
            })
    return linhas


def carregar_bronze(padrao: str, limite_arquivos: int | None = None) -> pd.DataFrame:
    """
    Le bronze nos dois formatos e deduplica por (p, ta).

      v1 (ate 21/09/2026)  bronze_posicao/**/*.ndjson.gz  ja achatado
      v2 (depois)          bronze_raw/**/*.json.gz        payload cru da API

    No v2 o instante da coleta vem do nome do arquivo (posicao_YYYYMMDDTHHMMSSZ).
    """
    import glob
    import re

    arquivos = sorted(glob.glob(padrao, recursive=True))
    if limite_arquivos:
        arquivos = arquivos[:limite_arquivos]

    registros = []
    for f in arquivos:
        if f.endswith(".ndjson.gz"):
            with gzip.open(f, "rt", encoding="utf-8") as fh:
                registros.extend(json.loads(l) for l in fh)
        elif f.endswith(".json.gz"):
            m = re.search(r"(\d{8}T\d{6}Z)", f)
            col = (pd.to_datetime(m.group(1), format="%Y%m%dT%H%M%SZ", utc=True).isoformat()
                   if m else None)
            with gzip.open(f, "rt", encoding="utf-8") as fh:
                registros.extend(_achatar_payload(json.load(fh), col))

    df = pd.DataFrame(registros)
    df["ta"] = pd.to_datetime(df["ta"], format="ISO8601", utc=True)
    return df.drop_duplicates(["p", "ta"])


# --------------------------------------------------------------------------
# Validacao do sentido: sl (Olho Vivo) x direction_id (GTFS)
# --------------------------------------------------------------------------

def descobrir_mapa_sentido(bronze, shapes, trips, min_veiculos=5):
    """
    Descobre empiricamente se sl=1 corresponde a direction_id 0 ou 1.

    Nao chuta: testa as duas hipoteses e escolhe pela evidencia. Um veiculo
    andando no sentido certo tem `dist_ao_longo` CRESCENDO com o tempo; no
    sentido errado, decrescendo. Mede-se a fracao de deltas positivos em cada
    hipotese e vence a que produzir movimento para a frente.
    """
    idx = trips.set_index(["route_id", "direction_id"])["shape_id"]
    resultados = []

    for (c, sl), g in bronze.groupby(["c", "sl"], sort=False):
        if g["p"].nunique() < min_veiculos:
            continue
        for dir_id in ("0", "1"):
            sid = idx.get((c, dir_id))
            if sid is None or sid not in shapes:
                continue
            sh = shapes[sid]
            d, err = sh.projetar(g["py"].to_numpy(), g["px"].to_numpy())
            sub = g.assign(d=d, err=err)
            sub = sub[sub["err"] < 100].sort_values(["p", "ta"])
            if len(sub) < 10:
                continue
            delta = sub.groupby("p")["d"].diff().dropna()
            if len(delta) < 10:
                continue
            resultados.append({
                "c": c, "sl": sl, "direction_id": dir_id,
                "frac_avanco": float((delta > 0).mean()),
                "erro_mediano": float(sub["err"].median()),
                "n": len(delta),
            })

    if not resultados:
        return pd.DataFrame(), {}

    r = pd.DataFrame(resultados)
    vencedor = r.loc[r.groupby(["c", "sl"])["frac_avanco"].idxmax()]
    mapa = (vencedor.groupby(["sl", "direction_id"]).size()
            .unstack(fill_value=0))
    return r, mapa


# --------------------------------------------------------------------------
# Headway observado
# --------------------------------------------------------------------------

def detectar_cruzamentos(sub: pd.DataFrame, marca_m: float) -> list[dict]:
    """
    Detecta quando cada veiculo cruzou a marca (metro X da rota).

    Entre dois pings consecutivos do mesmo veiculo, se um esta antes da marca e
    o outro depois, houve cruzamento. O instante e interpolado linearmente — e
    e por isso que a incerteza fica na ordem de dezenas de segundos, nao zero.
    """
    cruz = []
    for p, g in sub.groupby("p", sort=False):
        g = g.sort_values("ta")
        d = g["d"].to_numpy()
        t = g["ta"].to_numpy()
        antes = d[:-1]
        depois = d[1:]
        hits = np.where((antes < marca_m) & (depois >= marca_m))[0]
        for i in hits:
            faixa = depois[i] - antes[i]
            if faixa <= 0:
                continue
            frac = (marca_m - antes[i]) / faixa
            dt = (t[i + 1] - t[i]) / np.timedelta64(1, "s")
            if dt > 600:  # buraco grande demais para interpolar com honestidade
                continue
            cruz.append({
                "p": p,
                "instante": t[i] + np.timedelta64(int(frac * dt * 1000), "ms"),
                "incerteza_s": float(dt),
            })
    return cruz


def headway_observado(bronze, shapes, trips, c, sl, direction_id,
                      fracoes=(0.25, 0.5, 0.75), err_max=100.0):
    """Headway observado em pontos virtuais ao longo da rota."""
    sid = trips.set_index(["route_id", "direction_id"])["shape_id"].get((c, direction_id))
    if sid is None or sid not in shapes:
        return pd.DataFrame()

    sh = shapes[sid]
    g = bronze[(bronze["c"] == c) & (bronze["sl"] == sl)]
    if g.empty:
        return pd.DataFrame()

    d, err = sh.projetar(g["py"].to_numpy(), g["px"].to_numpy())
    sub = g.assign(d=d, err=err)
    sub = sub[sub["err"] < err_max]

    linhas = []
    for frac in fracoes:
        marca = sh.comprimento * frac
        cruz = pd.DataFrame(detectar_cruzamentos(sub, marca))
        if len(cruz) < 2:
            continue
        cruz = cruz.sort_values("instante")
        hw = cruz["instante"].diff().dt.total_seconds().dropna()
        for inst, h, inc in zip(cruz["instante"].iloc[1:], hw, cruz["incerteza_s"].iloc[1:]):
            linhas.append({
                "c": c, "sl": sl, "marca_frac": frac, "marca_m": marca,
                "instante": inst, "headway_s": h, "incerteza_s": inc,
            })
    return pd.DataFrame(linhas)


def headway_programado(gtfs, trip_id: str) -> pd.DataFrame:
    """Headway que a SPTrans planeja, por faixa horaria — a linha de base."""
    f = gtfs["frequencies"]
    return f[f["trip_id"] == trip_id][["start_time", "end_time", "headway_secs"]]
