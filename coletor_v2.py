#!/usr/bin/env python3
"""
Coletor da API Olho Vivo (SPTrans) -> bronze CRU (payload original, gzip).

v2 (21/09/2026): o bronze passa a guardar a resposta da API exatamente como
chegou, byte a byte, sem achatar nem deduplicar. Achatamento e dedupe sao
feitos na silver. Motivo: nao criar dependencia fragil do formato do payload
no bronze — se a SPTrans adicionar ou mudar campos, nada se perde.

Ate 21/09/2026 o bronze era achatado (bronze_posicao/, NDJSON). A partir
daqui, bronze_raw/ (JSON original). A silver le os dois formatos.

Uso (uma execucao, chamada pelo systemd):
    export SPTRANS_TOKEN="seu_token"
    python coletor.py --out ./data
"""

import argparse
import csv
import gzip
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

BASE = "https://api.olhovivo.sptrans.com.br/v2.1"
TZ_SP = ZoneInfo("America/Sao_Paulo")
TIMEOUT = 30
TENTATIVAS = 4


class PayloadVazio(Exception):
    """HTTP 200, mas o corpo nao e o JSON esperado (ex.: literalmente null)."""


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------

def autenticar(sess: requests.Session, token: str) -> None:
    # A API exige Content-Length explicito no POST; sem ele devolve HTTP 411.
    r = sess.post(f"{BASE}/Login/Autenticar", params={"token": token},
                  data=b"", headers={"Content-Length": "0"}, timeout=TIMEOUT)
    r.raise_for_status()
    if r.text.strip().lower() != "true":
        raise RuntimeError(f"Autenticacao falhou: HTTP {r.status_code}, corpo={r.text[:200]!r}")


def buscar_posicao(sess: requests.Session, token: str) -> tuple[bytes, dict]:
    """GET /Posicao com backoff e reautenticacao. Devolve (bytes crus, json)."""
    ultimo_erro = None
    for tentativa in range(1, TENTATIVAS + 1):
        try:
            r = sess.get(f"{BASE}/Posicao", timeout=TIMEOUT)
            if r.status_code in (401, 403):
                autenticar(sess, token)
                r = sess.get(f"{BASE}/Posicao", timeout=TIMEOUT)
            r.raise_for_status()
            payload = r.json()
            # A API as vezes responde HTTP 200 com corpo null. Tratamos como
            # falha para cair no mesmo backoff; o corpo invalido nao e gravado.
            if not isinstance(payload, dict) or "l" not in payload:
                raise PayloadVazio(f"corpo={r.text[:100]}")
            return r.content, payload
        except Exception as e:  # noqa: BLE001
            ultimo_erro = e
            if tentativa < TENTATIVAS:
                time.sleep(2 ** tentativa)
    raise ultimo_erro


# --------------------------------------------------------------------------
# Escrita
# --------------------------------------------------------------------------

def gravar_cru(conteudo: bytes, out: Path, agora: datetime) -> Path:
    """Grava a resposta da API sem nenhuma transformacao, so comprimida."""
    dt_local = agora.astimezone(TZ_SP).strftime("%Y-%m-%d")
    pasta = out / "bronze_raw" / f"dt={dt_local}"
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / f"posicao_{agora.strftime('%Y%m%dT%H%M%SZ')}.json.gz"
    tmp = destino.with_suffix(".tmp")
    with gzip.open(tmp, "wb") as f:
        f.write(conteudo)
    tmp.replace(destino)  # escrita atomica: nunca deixa arquivo pela metade
    return destino


def contar_veiculos(payload: dict) -> int:
    """So para a auditoria — nao transforma nada."""
    return sum(len(l.get("vs") or []) for l in payload.get("l") or [])


def auditar(out: Path, **campos) -> None:
    """Heartbeat: uma linha por execucao. Mesmas colunas da v1, para o
    auditoria.csv continuar um arquivo so. Na v2, veiculos_gravados ==
    veiculos_brutos, porque o dedupe saiu da ingestao."""
    caminho = out / "auditoria.csv"
    novo = not caminho.exists()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(campos))
        if novo:
            w.writeheader()
        w.writerow(campos)


# --------------------------------------------------------------------------
# Ciclo
# --------------------------------------------------------------------------

def coletar_uma_vez(sess, token, out: Path) -> int:
    agora = datetime.now(timezone.utc).replace(microsecond=0)
    iso = agora.isoformat()
    t0 = time.monotonic()
    try:
        # Login dentro do try: se falhar, o ciclo ainda deixa linha na auditoria.
        autenticar(sess, token)
        conteudo, payload = buscar_posicao(sess, token)
        destino = gravar_cru(conteudo, out, agora)
        n = contar_veiculos(payload)
        auditar(out, coletado_em=iso, status="ok",
                veiculos_brutos=n, veiculos_gravados=n,
                hr_api=payload.get("hr"), arquivo=destino.name,
                bytes=destino.stat().st_size,
                duracao_s=round(time.monotonic() - t0, 2), erro="")
        print(f"[{iso}] ok — {n} veiculos")
        return n
    except Exception as e:  # noqa: BLE001
        # O HTTPError do login traz a URL com ?token=...; nao vazar para a
        # auditoria nem para o journal do systemd.
        msg = f"{type(e).__name__}: {e}".replace(token, "***")
        auditar(out, coletado_em=iso, status="erro",
                veiculos_brutos=0, veiculos_gravados=0, hr_api="",
                arquivo="", bytes=0,
                duracao_s=round(time.monotonic() - t0, 2),
                erro=msg[:300])
        print(f"[{iso}] ERRO — {msg}", file=sys.stderr)
        return -1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="./data")
    args = ap.parse_args()

    token = os.environ.get("SPTRANS_TOKEN")
    if not token:
        print("Defina SPTRANS_TOKEN no ambiente.", file=sys.stderr)
        return 2

    out = Path(args.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    sess = requests.Session()
    return 0 if coletar_uma_vez(sess, token, out) >= 0 else 1


if __name__ == "__main__":
    sys.exit(main())
