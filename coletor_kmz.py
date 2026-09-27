#!/usr/bin/env python3
"""
Coletor do mapa de fluidez da SPTrans (API Olho Vivo, /KMZ).

O KMZ traz, por trecho de corredor e de via importante, a velocidade media e o
tempo medio de percurso dos onibus, separados por sentido (bairro-centro e
centro-bairro). E so o estado atual: sem historico, entao precisa ser coletado.
/KMZ sem sufixo ja traz os dois sentidos (27/09: 633 trechos, 244 vias).

A cada execucao:
  1. faz login na API
  2. baixa /KMZ
  3. guarda o KMZ CRU (bronze — o parse fica para a silver)
  4. registra uma linha de auditoria com o sha256 do conteudo:
     hashes repetidos em ciclos seguidos = a SPTrans ainda nao atualizou.
     E assim que se mede a frequencia real de atualizacao da fonte.

Uso:
    export SPTRANS_TOKEN="seu_token"
    python coletor_kmz.py --out ./data/kmz
"""

import argparse
import csv
import hashlib
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

BASE = "https://api.olhovivo.sptrans.com.br/v2.1"
TZ_SP = ZoneInfo("America/Sao_Paulo")
TIMEOUT = 60
TENTATIVAS = 3


def autenticar(sess: requests.Session, token: str) -> None:
    # A API exige Content-Length explicito no POST; sem ele devolve HTTP 411.
    r = sess.post(f"{BASE}/Login/Autenticar", params={"token": token},
                  data=b"", headers={"Content-Length": "0"}, timeout=TIMEOUT)
    r.raise_for_status()
    if r.text.strip().lower() != "true":
        raise RuntimeError(f"Autenticacao falhou: HTTP {r.status_code}, corpo={r.text[:200]!r}")


def baixar(sess: requests.Session, token: str) -> bytes:
    ultimo = None
    for t in range(1, TENTATIVAS + 1):
        try:
            r = sess.get(f"{BASE}/KMZ", timeout=TIMEOUT)
            if r.status_code in (401, 403):
                autenticar(sess, token)
                r = sess.get(f"{BASE}/KMZ", timeout=TIMEOUT)
            r.raise_for_status()
            # KMZ e um zip: comeca com "PK". Qualquer outra coisa (null, HTML
            # de erro) e falha e entra no retry.
            if not r.content.startswith(b"PK"):
                raise ValueError(f"resposta nao e KMZ: {r.content[:60]!r}")
            return r.content
        except Exception as e:  # noqa: BLE001
            ultimo = e
            if t < TENTATIVAS:
                time.sleep(2 ** t)
    raise ultimo


def gravar(conteudo: bytes, out: Path, agora: datetime) -> Path:
    dt_local = agora.astimezone(TZ_SP).strftime("%Y-%m-%d")
    pasta = out / "bronze_kmz" / f"dt={dt_local}"
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / f"kmz_{agora.strftime('%Y%m%dT%H%M%SZ')}.kmz"
    tmp = destino.with_suffix(".tmp")
    tmp.write_bytes(conteudo)  # KMZ ja e comprimido; gzip nao ganha nada
    tmp.replace(destino)  # escrita atomica
    return destino


def auditar(out: Path, linha: dict) -> None:
    caminho = out / "auditoria.csv"
    novo = not caminho.exists()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(linha))
        if novo:
            w.writeheader()
        w.writerow(linha)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="./data/kmz")
    args = ap.parse_args()

    token = os.environ.get("SPTRANS_TOKEN")
    if not token:
        print("Defina SPTRANS_TOKEN no ambiente.", file=sys.stderr)
        return 2

    out = Path(args.out).expanduser().resolve()
    agora = datetime.now(timezone.utc).replace(microsecond=0)
    iso = agora.isoformat()
    t0 = time.monotonic()
    linha = {"coletado_em": iso, "status": "ok", "arquivo": "", "bytes": 0,
             "sha256": "", "duracao_s": 0, "erro": ""}
    try:
        sess = requests.Session()
        autenticar(sess, token)
        conteudo = baixar(sess, token)
        destino = gravar(conteudo, out, agora)
        linha.update(arquivo=destino.name, bytes=len(conteudo),
                     sha256=hashlib.sha256(conteudo).hexdigest()[:16])
    except Exception as e:  # noqa: BLE001
        # O HTTPError do login traz a URL com ?token=...; nao vazar.
        linha.update(status="erro",
                     erro=f"{type(e).__name__}: {e}".replace(token, "***")[:300])
    linha["duracao_s"] = round(time.monotonic() - t0, 2)
    auditar(out, linha)
    print(f"[{iso}] {linha['status']} {linha['bytes']}B {linha['erro']}".rstrip())
    return 0 if linha["status"] == "ok" else 1

if __name__ == "__main__":
    sys.exit(main())
