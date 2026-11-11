"""POST API の処理。"""
import os
import re
import threading
import traceback
import uuid
from datetime import datetime, timedelta

from . import audiostore, dispatch, feeds, gemini, prepare, questions, store, talk

INTERVALS = [1, 3, 7, 14, 30]  # 復習の間隔（日）


def _day(offset=0):
    return (datetime.now(store.JST) + timedelta(days=offset)).strftime("%Y-%m-%d")


def public_state():
    cfg = store.config()
    key = gemini.api_key()
    safe = {k: v for k, v in cfg.items() if k != "gemini_api_key"}
    safe.update(has_key=bool(key), key_hint=("…" + key[-4:]) if key else "", cloud=store.CLOUD)
    return {"config": safe, "episodes": store.list_episodes(), "progress": store.progress(),
            "today": store.today()}


def _set_status(ep_id, status, message, cancelled=False):
    meta = store.episode_meta(ep_id)
    if meta:
        meta.update(status=status, message=message, progress=0, updated=store.now_iso(), cancelled=cancelled)
        store.save_episode_meta(ep_id, meta)


def _background(fn, *args):
    def run():
        try:
            fn(*args)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
    threading.Thread(target=run, daemon=True).start()


def _dispatch():
    ok, why = dispatch.trigger("queue")
    if not ok:
        print("dispatch failed:", why, flush=True)


def _erase_episode(ep_id, keep_marker):
    """回のデータ（音声・文字起こし・区間・復習の文）を消す。
    keep_marker=True なら「削除済み」の印だけ残し、新着確認で同じ回がまた登録されないようにする。"""
    meta = store.episode_meta(ep_id)
    if not meta:
        return
    audiostore.delete(ep_id)
    for part in ("transcript", "sections"):
        store.delete(f"ep:{ep_id}:{part}")
    if keep_marker:  # 処理中のActionsも、この印を見て止まる
        store.save_episode_meta(ep_id, {k: meta.get(k) for k in ("id", "feed_id", "title", "published_ts")}
                                | {"status": "deleted", "cancelled": True, "updated": store.now_iso()})
    else:
        store.delete(f"ep:{ep_id}:meta")
    pr = store.progress()
    pr["review"] = [r for r in pr["review"] if r.get("ep") != ep_id]
    store.save_progress(pr)


def _delete_feed(fid):
    for m in store.list_episodes():
        if m.get("feed_id") == fid:
            _erase_episode(m["id"], keep_marker=False)
    return _edit_config(lambda cfg: cfg.update(feeds=[f for f in cfg["feeds"] if f["id"] != fid]))


def _yt_id(url):
    m = re.search(r"(?:v=|youtu\.be/|shorts/|embed/)([A-Za-z0-9_-]{11})", url)
    if not m:
        raise ValueError("YouTubeのURLから動画IDが見つかりません")
    return m.group(1)


def save_session(b):
    pr = store.progress()
    missed = b.get("missed") or []
    sess = {"date": store.today(), "at": store.now_iso(), "ep": b["ep"], "idx": int(b["idx"]),
            "choice": b.get("choice"), "correct": b.get("correct"), "feel": b.get("feel"),
            "lines": b.get("lines", 0), "missed": [{"line": m["line"], "cause": m.get("cause")} for m in missed]}
    pr["sessions"] = [s for s in pr["sessions"]
                      if not (s["ep"] == sess["ep"] and s["idx"] == sess["idx"] and s["date"] == sess["date"])]
    pr["sessions"].append(sess)
    existing = {(r["ep"], r["idx"], r["line"]) for r in pr["review"]}
    for m in missed:
        if (b["ep"], int(b["idx"]), m["line"]) in existing:
            continue
        pr["review"].append({"id": uuid.uuid4().hex[:10], "ep": b["ep"], "idx": int(b["idx"]),
                             "line": m["line"], "text": m.get("text", ""), "ja": m.get("ja", ""),
                             "start": m.get("start"), "end": m.get("end"), "cause": m.get("cause"),
                             "added": store.today(), "due": _day(1), "stage": 0})
    store.save_progress(pr)
    return public_state()


def review_answer(b):
    pr = store.progress()
    for it in pr["review"]:
        if it["id"] == b.get("id"):
            if b.get("ok"):
                it["stage"] = it.get("stage", 0) + 1
                if it["stage"] >= len(INTERVALS):
                    it["done"] = True
                else:
                    it["due"] = _day(INTERVALS[it["stage"]])
            else:
                it["stage"], it["due"] = 0, _day(1)
            it["reviews"] = it.get("reviews", 0) + 1
    store.save_progress(pr)
    return public_state()


def _edit_progress(fn):
    pr = store.progress()
    fn(pr)
    store.save_progress(pr)
    return public_state()


def _edit_config(fn):
    cfg = store.config()
    fn(cfg)
    store.save_config(cfg)
    return public_state()


def route(p, b):
    if p == "/api/settings":
        def edit(cfg):
            for k in ("whisper_model", "segment_minutes", "auto_prepare"):
                if k in b:
                    cfg[k] = b[k]
            if b.get("gemini_api_key") and not store.CLOUD:
                cfg["gemini_api_key"], cfg["gemini_model"] = b["gemini_api_key"].strip(), ""
        return _edit_config(edit)
    if p == "/api/test-key":
        if not gemini.api_key():
            raise ValueError("GeminiのAPIキーが未設定です")
        return {"ok": True, "model": gemini.pick_model(gemini.api_key(), force=True)}
    if p == "/api/feeds":
        feeds.add_feed(b.get("url", ""))
        return public_state()
    if p == "/api/feeds/check":
        feeds.check_feeds()
        return public_state()
    if p == "/api/feeds/toggle":
        return _edit_config(lambda cfg: [f.update(auto=not f.get("auto", True))
                                         for f in cfg["feeds"] if f["id"] == b.get("id")])
    if p == "/api/episodes/prepare":
        # 文字起こしはGitHub Actionsが行う。トークンがあればすぐ起動、なければ30分ごとの定期実行で拾う
        has_token = bool(os.environ.get("GITHUB_DISPATCH_TOKEN"))
        _set_status(b["id"], "queued", "順番待ち（まもなく文字起こしが始まります）" if has_token
                    else "順番待ち（30分以内に自動で文字起こしが始まります）")
        if has_token:
            _background(_dispatch)
        return public_state()
    if p == "/api/episodes/cancel":
        # 処理中のActionsは、次の進み具合の更新時（20秒以内）に気づいて止まる
        if store.episode_meta(b["id"]).get("status") in ("queued",) + prepare.ACTIVE:
            _set_status(b["id"], "new", "中断しました", cancelled=True)
        return public_state()
    if p == "/api/episodes/delete":
        _erase_episode(b["id"], keep_marker=True)
        return public_state()
    if p == "/api/feeds/delete":
        return _delete_feed(b.get("id"))
    if p == "/api/review/delete":
        return _edit_progress(lambda pr: pr.update(review=[r for r in pr["review"] if r["id"] != b.get("id")]))
    if p == "/api/talk/delete":
        store.delete(f"talk:{b.get('id', '')}")
        return {"talks": talk.summaries()}
    if p == "/api/episodes/regenerate":
        _set_status(b["id"], "generating", "要旨問題と表現を作成中")
        _background(prepare.regenerate_questions, b["id"])
        return public_state()
    if p == "/api/translate":
        return questions.translate_section(b["ep"], int(b["idx"]))
    if p == "/api/session":
        return save_session(b)
    if p == "/api/review/answer":
        return review_answer(b)
    if p == "/api/themes":
        name = (b.get("name") or "").strip()
        if not name:
            raise ValueError("テーマ名を入力してください")
        tid = "u" + uuid.uuid4().hex[:6]
        st = _edit_progress(lambda pr: pr["themes"].insert(
            0, {"id": tid, "name": name, "fav": False, "count": 0, "last": None}))
        st["new_theme"] = tid
        return st
    if p == "/api/themes/fav":
        return _edit_progress(lambda pr: [t.update(fav=not t.get("fav"))
                                          for t in pr["themes"] if t["id"] == b.get("id")])
    if p == "/api/themes/delete":
        return _edit_progress(lambda pr: pr.update(themes=[t for t in pr["themes"] if t["id"] != b.get("id")]))
    if p == "/api/talk/start":
        return talk.start(b)
    if p == "/api/talk/reply":
        return talk.reply(b)
    if p == "/api/youtube":
        vid = _yt_id(b.get("url", ""))
        return _edit_config(lambda cfg: None if any(y["video_id"] == vid for y in cfg["youtube"]) else
                            cfg["youtube"].insert(0, {"id": vid, "video_id": vid, "url": b["url"],
                                                      "title": (b.get("title") or "").strip() or vid,
                                                      "added": store.today()}))
    if p == "/api/youtube/remove":
        return _edit_config(lambda cfg: cfg.update(youtube=[y for y in cfg["youtube"] if y["id"] != b.get("id")]))
    return None
