"""データ保存。TURSO_DATABASE_URL があればTurso（クラウド）、なければ data/ フォルダのJSON。

キー一覧: config / progress / ep:<id>:meta / ep:<id>:transcript / ep:<id>:sections / talk:<id>
"""
import json
import os
import threading
from datetime import datetime, timedelta, timezone

from . import turso

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
CLOUD = bool(os.environ.get("TURSO_DATABASE_URL"))
JST = timezone(timedelta(hours=9))

_lock = threading.RLock()
_ready = False

DEFAULT_CONFIG = {
    "gemini_api_key": "",
    "gemini_model": "",
    "whisper_model": "small.en",
    "segment_minutes": 4,
    "auto_prepare": True,
    "feeds": [],
    "youtube": [],
}

DEFAULT_PROGRESS = {
    "sessions": [],
    "review": [],
    "themes": [
        {"id": "t1", "name": "週末の過ごし方", "fav": True, "count": 0, "last": None},
        {"id": "t2", "name": "仕事で最近あったこと", "fav": True, "count": 0, "last": None},
        {"id": "t3", "name": "今日のトレードの振り返り", "fav": False, "count": 0, "last": None},
        {"id": "t4", "name": "好きな食べ物", "fav": False, "count": 0, "last": None},
        {"id": "t5", "name": "旅行で行きたい場所", "fav": False, "count": 0, "last": None},
    ],
}


def _copy(obj):
    return json.loads(json.dumps(obj))


def _path(key):
    parts = key.split(":")
    if parts[0] == "ep":
        return os.path.join(DATA, "episodes", parts[1], parts[2] + ".json")
    if parts[0] == "talk":
        return os.path.join(DATA, "talks", parts[1] + ".json")
    return os.path.join(DATA, key + ".json")


def ensure_ready():
    global _ready
    if _ready:
        return
    if CLOUD:
        turso.execute("CREATE TABLE IF NOT EXISTS en_kv (key TEXT PRIMARY KEY, value TEXT NOT NULL, "
                      "updated_at TEXT NOT NULL)")
    else:
        for d in (DATA, os.path.join(DATA, "episodes"), os.path.join(DATA, "talks")):
            os.makedirs(d, exist_ok=True)
    _ready = True


def get(key, default=None):
    ensure_ready()
    if CLOUD:
        rows = turso.execute("SELECT value FROM en_kv WHERE key = ?", [key])
        return json.loads(rows[0][0]) if rows else _copy(default)
    p = _path(key)
    with _lock:
        if not os.path.exists(p):
            return _copy(default)
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return _copy(default)


def put(key, obj):
    ensure_ready()
    text = json.dumps(obj, ensure_ascii=False)
    if CLOUD:
        turso.execute("INSERT INTO en_kv (key, value, updated_at) VALUES (?, ?, ?) "
                      "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                      [key, text, now_iso()])
        return
    p = _path(key)
    with _lock:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p + ".tmp", "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(p + ".tmp", p)


def delete(key):
    ensure_ready()
    if CLOUD:
        turso.execute("DELETE FROM en_kv WHERE key = ?", [key])
    elif os.path.exists(_path(key)):
        os.remove(_path(key))


def exists(key):
    if CLOUD:
        ensure_ready()
        return bool(turso.execute("SELECT 1 FROM en_kv WHERE key = ?", [key]))
    return os.path.exists(_path(key))


def config():
    c = get("config", DEFAULT_CONFIG)
    for k, v in DEFAULT_CONFIG.items():
        c.setdefault(k, _copy(v))
    return c


def save_config(c):
    put("config", c)


def progress():
    p = get("progress", DEFAULT_PROGRESS)
    for k, v in DEFAULT_PROGRESS.items():
        p.setdefault(k, _copy(v))
    return p


def save_progress(p):
    put("progress", p)


def episode_meta(ep_id):
    return get(f"ep:{ep_id}:meta", {})


def save_episode_meta(ep_id, meta):
    put(f"ep:{ep_id}:meta", meta)


def list_episodes():
    ensure_ready()
    if CLOUD:
        rows = turso.execute("SELECT value FROM en_kv WHERE key LIKE 'ep:%:meta'")
        out = [json.loads(r[0]) for r in rows]
    else:
        root = os.path.join(DATA, "episodes")
        out = [m for m in (episode_meta(n) for n in os.listdir(root)) if m]
    out.sort(key=lambda m: m.get("published_ts", 0), reverse=True)
    return out


def list_talks(limit=50):
    ensure_ready()
    if CLOUD:
        rows = turso.execute("SELECT value FROM en_kv WHERE key LIKE 'talk:%' ORDER BY key DESC LIMIT ?", [limit])
        return [json.loads(r[0]) for r in rows]
    root = os.path.join(DATA, "talks")
    names = sorted((n for n in os.listdir(root) if n.endswith(".json")), reverse=True)[:limit]
    return [t for t in (get("talk:" + n[:-5]) for n in names) if t]


def work_dir(ep_id):
    """音声ファイルなど一時ファイルの置き場所。"""
    base = os.environ.get("ENGLISH_APP_WORK") or os.path.join(DATA, "episodes")
    d = os.path.join(base, ep_id)
    os.makedirs(d, exist_ok=True)
    return d


def now_iso():
    return datetime.now(JST).replace(tzinfo=None).isoformat(timespec="seconds")


def today():
    return datetime.now(JST).strftime("%Y-%m-%d")
