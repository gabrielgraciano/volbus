"""Roda SQL no SQL Warehouse via CLI do Databricks e devolve pandas.DataFrame (com paginacao de chunks)."""
import json
import os
import subprocess
import tempfile
import time

import pandas as pd

CLI = r"C:\Users\gabir\AppData\Local\Microsoft\WinGet\Links\databricks.exe"
WH = "117d33ac28f3ff05"


def _api(metodo, caminho, corpo=None):
    args = [CLI, "api", metodo, caminho]
    tmp = None
    if corpo is not None:
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(corpo, tmp)
        tmp.close()
        args += ["--json", "@" + tmp.name]
    r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8")
    if tmp:
        os.unlink(tmp.name)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-2000:])
    return json.loads(r.stdout)


def q(sql, timeout_s=900):
    r = _api("post", "/api/2.0/sql/statements", {
        "warehouse_id": WH, "statement": sql, "wait_timeout": "50s",
        "format": "JSON_ARRAY", "disposition": "INLINE", "on_wait_timeout": "CONTINUE"})
    sid = r["statement_id"]
    t0 = time.time()
    while r["status"]["state"] in ("PENDING", "RUNNING"):
        if time.time() - t0 > timeout_s:
            _api("post", f"/api/2.0/sql/statements/{sid}/cancel")
            raise TimeoutError(sid)
        time.sleep(5)
        r = _api("get", f"/api/2.0/sql/statements/{sid}")
    if r["status"]["state"] != "SUCCEEDED":
        raise RuntimeError(json.dumps(r["status"])[:2000])
    cols = [c["name"] for c in r["manifest"]["schema"]["columns"]]
    tipos = [c["type_name"] for c in r["manifest"]["schema"]["columns"]]
    rows = list(r.get("result", {}).get("data_array", []) or [])
    nxt = r.get("result", {}).get("next_chunk_index")
    while nxt is not None:
        c = _api("get", f"/api/2.0/sql/statements/{sid}/result/chunks/{nxt}")
        rows += c.get("data_array", []) or []
        nxt = c.get("next_chunk_index")
    df = pd.DataFrame(rows, columns=cols)
    for c, t in zip(cols, tipos):
        if t in ("INT", "LONG", "BIGINT", "SHORT", "DOUBLE", "FLOAT", "DECIMAL"):
            df[c] = pd.to_numeric(df[c])
        elif t in ("TIMESTAMP", "TIMESTAMP_NTZ"):
            df[c] = pd.to_datetime(df[c])
        elif t == "DATE":
            df[c] = pd.to_datetime(df[c]).dt.date
    return df
