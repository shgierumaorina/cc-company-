"""Turso（libSQL）をHTTP APIで使う最小クライアント。追加ライブラリ不要。"""
import json
import os
import urllib.error
import urllib.request


class TursoError(Exception):
    pass


def _endpoint():
    url = os.environ.get("TURSO_DATABASE_URL", "").strip()
    if not url:
        raise TursoError("TURSO_DATABASE_URL が未設定です")
    if url.startswith("libsql://"):
        url = "https://" + url[len("libsql://"):]
    return url.rstrip("/") + "/v2/pipeline"


def _arg(v):
    if v is None:
        return {"type": "null"}
    if isinstance(v, bool):
        return {"type": "integer", "value": str(int(v))}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    return {"type": "text", "value": str(v)}


def _val(cell):
    t = cell.get("type")
    if t == "null":
        return None
    if t == "integer":
        return int(cell["value"])
    return cell.get("value")


def execute_many(statements):
    """[(sql, [args...]), ...] を1回の通信で実行し、各結果の行リストを返す。"""
    reqs = [{"type": "execute", "stmt": {"sql": sql, "args": [_arg(a) for a in args]}}
            for sql, args in statements]
    reqs.append({"type": "close"})
    body = json.dumps({"requests": reqs}).encode("utf-8")
    req = urllib.request.Request(_endpoint(), data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    token = os.environ.get("TURSO_AUTH_TOKEN", "").strip()
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise TursoError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}") from None
    except urllib.error.URLError as e:
        raise TursoError(f"Tursoに接続できません: {e.reason}") from None
    out = []
    for res in data.get("results", [])[:len(statements)]:
        if res.get("type") == "error":
            raise TursoError(str(res.get("error"))[:300])
        result = res["response"].get("result", {})
        out.append([[_val(c) for c in row] for row in result.get("rows", [])])
    return out


def execute(sql, args=()):
    return execute_many([(sql, list(args))])[0]
