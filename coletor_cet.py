#!/usr/bin/env python3
"""
Coletor da lentidao por regiao da CET-SP.

A cada execucao:
  1. baixa a pagina "Transito Agora"
  2. guarda o HTML CRU comprimido (bronze — permite reprocessar se o layout mudar)
  3. extrai km, % e tendencia das 5 regioes e acrescenta ao lentidao.csv
  4. registra uma linha de auditoria

Uso:
    python coletor_cet.py --out ./data_cet

Sobre os campos:
  km        extensao de lentidao na regiao — ESTE e o regressor
  pct       participacao da regiao no congestionamento total da cidade
            (os 5 somam ~100%). Nao e intensidade: se a cidade toda travar
            por igual, o pct nao muda. Guardado so por completude.
  tendencia nome do icone exibido (ex.: ESTAVEL)
"""

import argparse
import csv
import gzip
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

URL = "https://www.cetsp.com.br/transito-agora/transito-nas-principais-vias.aspx"
TZ_SP = ZoneInfo("America/Sao_Paulo")
TIMEOUT = 30
TENTATIVAS = 3
REGIOES = ("Norte", "Oeste", "Centro", "Leste", "Sul")

# User-Agent honesto: identifica o coletor e o proposito, sem se passar por navegador.
HEADERS = {"User-Agent": "coletor-lentidao-pesquisa-ime-usp/1.0"}

PADRAO = re.compile(
    r'<li class="txt(?P<regiao>Norte|Oeste|Centro|Leste|Sul)">'
    r'.*?<strong>\s*(?P<km>\d+)\s*km\s*\(\s*(?P<pct>\d+)\s*%\s*\)\s*</strong>'
    r'.*?src="[^"]*/ico/(?P<tend>[A-Za-z_]+)\.gif"',
    re.S | re.I,
)


def baixar() -> str:
    ultimo = None
    for t in range(1, TENTATIVAS + 1):
        try:
            r = requests.get(URL, headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            r.encoding = "utf-8"
            return r.text
        except Exception as e:  # noqa: BLE001
            ultimo = e
            if t < TENTATIVAS:
                time.sleep(2 ** t)
    raise ultimo


def extrair(html: str) -> list[dict]:
    achados = {}
    for m in PADRAO.finditer(html):
        achados[m.group("regiao").capitalize()] = {
            "km": int(m.group("km")),
            "pct": int(m.group("pct")),
            "tendencia": m.group("tend").upper(),
        }
    return [{"regiao": r, **achados[r]} for r in REGIOES if r in achados]


def gravar_html(html: str, out: Path, agora: datetime) -> Path:
    dt_local = agora.astimezone(TZ_SP).strftime("%Y-%m-%d")
    pasta = out / "bronze_html" / f"dt={dt_local}"
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / f"cet_{agora.strftime('%Y%m%dT%H%M%SZ')}.html.gz"
    with gzip.open(destino, "wt", encoding="utf-8") as f:
        f.write(html)
    return destino


def anexar_csv(caminho: Path, campos: list[str], linhas: list[dict]) -> None:
    novo = not caminho.exists()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos)
        if novo:
            w.writeheader()
        w.writerows(linhas)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="./data_cet")
    args = ap.parse_args()
    out = Path(args.out).expanduser().resolve()

    agora = datetime.now(timezone.utc).replace(microsecond=0)
    iso = agora.isoformat()
    t0 = time.monotonic()
    status, erro, n, tamanho = "ok", "", 0, 0

    try:
        html = baixar()
        destino = gravar_html(html, out, agora)
        tamanho = destino.stat().st_size

        regioes = extrair(html)
        n = len(regioes)
        if n != len(REGIOES):
            # HTML salvo mesmo assim: layout mudou, reprocessar depois
            status, erro = "erro_parse", f"{n} de {len(REGIOES)} regioes encontradas"
        else:
            anexar_csv(
                out / "lentidao.csv",
                ["coletado_em", "regiao", "km", "pct", "tendencia"],
                [{"coletado_em": iso, **r} for r in regioes],
            )
    except Exception as e:  # noqa: BLE001
        status, erro = "erro", f"{type(e).__name__}: {e}"[:300]

    anexar_csv(
        out / "auditoria.csv",
        ["coletado_em", "status", "regioes", "bytes_html_gz", "duracao_s", "erro"],
        [{"coletado_em": iso, "status": status, "regioes": n,
          "bytes_html_gz": tamanho, "duracao_s": round(time.monotonic() - t0, 2),
          "erro": erro}],
    )
    print(f"[{iso}] {status} — {n} regioes {erro}".rstrip())
    return 0 if status == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
