"""Gemini API（無料枠）呼び出し。追加ライブラリ不要（urllibのみ）。"""
import json
import os
import time
import urllib.error
import urllib.request

from . import store

API = "https://generativelanguage.googleapis.com/v1beta"


class GeminiError(Exception):
    pass


def _http(method, url, key, body=None, timeout=90):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("x-goog-api-key", key)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        raise GeminiError(f"HTTP {e.code}: {detail}") from None
    except urllib.error.URLError as e:
        raise GeminiError(f"接続できません: {e.reason}") from None


def _candidates(key):
    """使えるモデルを一覧から選ぶ。Flash-Lite（無料枠の回数が多い）を優先。"""
    res = _http("GET", f"{API}/models?pageSize=200", key)
    names = []
    for m in res.get("models", []):
        if "generateContent" not in m.get("supportedGenerationMethods", []):
            continue
        n = m["name"].split("/", 1)[-1]
        low = n.lower()
        if "flash" not in low:
            continue
        if any(x in low for x in ("tts", "image", "live", "audio", "embedding", "thinking", "exp")):
            continue
        names.append(n)

    def rank(n):
        low = n.lower()
        lite = 0 if "lite" in low else 1
        preview = 1 if "preview" in low else 0
        # 数字の大きい（新しい）ものを先に
        nums = [int(x) for x in "".join(c if c.isdigit() else " " for c in low).split()[:2]]
        ver = tuple(-x for x in nums)
        return (lite, preview, ver)

    names.sort(key=rank)
    return names


def pick_model(key, force=False):
    cfg = store.config()
    if cfg.get("gemini_model") and not force:
        return cfg["gemini_model"]
    names = _candidates(key)
    if not names:
        raise GeminiError("使えるGeminiモデルが見つかりません")
    for n in names[:6]:
        try:
            # 応答が返ればOK（中身は問わない）
            _http("POST", f"{API}/models/{n}:generateContent", key, {
                "contents": [{"role": "user", "parts": [{"text": "Say OK."}]}],
                "generationConfig": {"maxOutputTokens": 200},
            })
            cfg = store.config()
            cfg["gemini_model"] = n
            store.save_config(cfg)
            return n
        except GeminiError:
            continue
    raise GeminiError("無料枠で使えるモデルが見つかりません（キーの設定を確認してください）")


def _generate(key, model, prompt, system, max_tokens=4096, json_mode=False, history=None):
    contents = list(history or [])
    contents.append({"role": "user", "parts": [{"text": prompt}]})
    body = {
        "contents": contents,
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.7},
    }
    if json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    res = _http("POST", f"{API}/models/{model}:generateContent", key, body)
    try:
        parts = res["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts)
    except (KeyError, IndexError):
        raise GeminiError(f"応答が空でした: {json.dumps(res)[:300]}") from None


def api_key():
    """クラウドでは環境変数 GEMINI_API_KEY、PCでは設定画面で保存したキー。"""
    return os.environ.get("GEMINI_API_KEY", "").strip() or store.config().get("gemini_api_key", "").strip()


BUSY = ("HTTP 500", "HTTP 502", "HTTP 503", "HTTP 504")
WAITS = (2, 5, 10)  # 混雑時の待ち時間（秒）。2回目からは別のモデルに切り替える


def _friendly(e):
    msg = str(e)
    if msg.startswith(BUSY):
        return GeminiError("Geminiが混み合っています。少し時間をおいてからもう一度試してください")
    if msg.startswith("HTTP 429"):
        return GeminiError("Geminiの無料枠の上限に達しました。上限は毎日（日本時間の夕方ごろ）リセットされます")
    return e


def generate(prompt, system=None, max_tokens=4096, json_mode=False, history=None):
    key = api_key()
    if not key:
        raise GeminiError("GeminiのAPIキーが未設定です（設定画面から入力）")
    model, tried, reselected = pick_model(key), [], False
    for attempt in range(len(WAITS) + 1):
        tried.append(model)
        try:
            text = _generate(key, model, prompt, system, max_tokens, json_mode, history)
            break
        except GeminiError as e:
            msg = str(e)
            if ("HTTP 404" in msg or "HTTP 403" in msg) and not reselected:
                model, reselected = pick_model(key, force=True), True  # モデルが使えなくなったら選び直す
                continue
            if not msg.startswith(BUSY) or attempt == len(WAITS):
                raise _friendly(e) from None
            time.sleep(WAITS[attempt])
            if attempt >= 1:  # 同じモデルが混んでいたら、別のモデルを試す
                model = next((n for n in _candidates(key) if n not in tried), model)
    if json_mode:
        return parse_json(text)
    return text


def parse_json(text):
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        t = t.rsplit("```", 1)[0]
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        s, e = t.find("{"), t.rfind("}")
        if s >= 0 and e > s:
            return json.loads(t[s:e + 1])
        raise GeminiError("AIの応答をJSONとして読めませんでした")


def test_key(key):
    names = _candidates(key)
    return names
