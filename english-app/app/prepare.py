"""音源の取得 → 文字起こし（Whisper）→ 区間分割 → 出題の準備。

GitHub Actions から実行する:
    python -m app.prepare --queue   # 画面で「準備する」を押した回を処理
    python -m app.prepare --auto    # 夜間：新着確認＋各番組の未準備の最新回を1本
"""
import os
import random
import sys
import time
import traceback
import urllib.parse
from datetime import datetime

from . import feeds, gemini, store
from .questions import build_questions, split_sections

ACTIVE = ("downloading", "transcribing", "generating")
MAX_PER_RUN = 3


def _set(ep_id, **kw):
    meta = store.episode_meta(ep_id)
    meta.update(kw, updated=store.now_iso())
    store.save_episode_meta(ep_id, meta)
    return meta


def download(ep_id):
    meta = _set(ep_id, status="downloading", progress=0, message="音声を取得中")
    ext = os.path.splitext(urllib.parse.urlparse(meta["audio_url"]).path)[1]
    ext = ext if 1 < len(ext) <= 5 else ".mp3"
    path = os.path.join(store.work_dir(ep_id), "audio" + ext)
    if os.path.exists(path) and os.path.getsize(path) > 10000:
        return path
    with feeds.http_get(meta["audio_url"], timeout=120) as r, open(path + ".part", "wb") as f:
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)
    os.replace(path + ".part", path)
    return path


def _patch_av():
    """PyAV 15以降で消えた引数（metadata_errors）をfaster-whisperが渡すため、互換用に取り除く。"""
    import av
    if getattr(av.open, "_ll_compat", False):
        return
    original = av.open

    def compat_open(*a, **k):
        k.pop("metadata_errors", None)
        return original(*a, **k)
    compat_open._ll_compat = True
    av.open = compat_open


def transcribe(ep_id, path):
    _patch_av()
    from faster_whisper import WhisperModel  # 重いので必要な時だけ読み込む
    name = store.config().get("whisper_model") or "small.en"
    _set(ep_id, status="transcribing", progress=0, message="文字起こし中")
    print("loading model", name, flush=True)
    model = WhisperModel(name, device="cpu", compute_type="int8")
    segments, info = model.transcribe(path, language="en", vad_filter=True, beam_size=1)
    lines, last = [], time.time()
    for s in segments:
        text = s.text.strip()
        if not text:
            continue
        lines.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": text})
        if time.time() - last > 20 and info.duration:
            _set(ep_id, progress=min(99, int(s.end * 100 / info.duration)))
            last = time.time()
    store.put(f"ep:{ep_id}:transcript", lines)
    _set(ep_id, duration=round(info.duration or 0, 1))
    print("transcribed", len(lines), "lines", flush=True)
    return lines


def make_sections(ep_id, lines):
    """文字起こしから区間と問題を作って保存する（Geminiのみ使用・数十秒）。"""
    sections = split_sections(lines, store.config().get("segment_minutes") or 4)
    _set(ep_id, status="generating", progress=0, message="要旨問題と表現を作成中")
    message = ""
    try:
        qs = build_questions(sections)
    except gemini.GeminiError as e:
        qs, message = {}, f"問題作成に失敗（「問題を作り直す」で再作成できます）: {e}"[:200]
    for s in sections:
        q = qs.get(s["index"], {})
        choices = [c for c in [q.get("correct_ja")] + list(q.get("wrong_ja") or []) if c]
        random.shuffle(choices)
        s.update(topic_ja=q.get("topic_ja", ""), summary_ja=q.get("summary_ja", ""), choices=choices,
                 answer=choices.index(q["correct_ja"]) if q.get("correct_ja") in choices else -1,
                 chunks=q.get("chunks", []))
    store.put(f"ep:{ep_id}:sections", sections)
    _set(ep_id, status="ready", progress=100, sections=len(sections), message=message,
         prepared_at=store.now_iso())


def prepare(ep_id):
    """1エピソードを学習できる状態にする。"""
    try:
        lines = store.get(f"ep:{ep_id}:transcript")
        if not lines:
            lines = transcribe(ep_id, download(ep_id))
        if not lines:
            raise RuntimeError("文字起こし結果が空でした")
        make_sections(ep_id, lines)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        _set(ep_id, status="error", message=str(e)[:300])
    return store.episode_meta(ep_id)


def regenerate_questions(ep_id):
    try:
        lines = store.get(f"ep:{ep_id}:transcript")
        if not lines:
            raise RuntimeError("文字起こしがまだありません。「準備する」を押してください")
        make_sections(ep_id, lines)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        _set(ep_id, status="error", message=str(e)[:300])


def _stale(meta, hours=3):
    try:
        return (datetime.fromisoformat(store.now_iso()) - datetime.fromisoformat(meta.get("updated", ""))
                ).total_seconds() > hours * 3600
    except ValueError:
        return True


def todo(auto):
    eps = store.list_episodes()
    picks = [e for e in eps if e.get("status") == "queued"
             or (e.get("status") in ACTIVE and _stale(e))]  # 途中で止まったものもやり直す
    if auto:
        feeds.check_feeds()
        cfg = store.config()
        eps = store.list_episodes()
        if cfg.get("auto_prepare", True):
            for f in cfg["feeds"]:
                if f.get("auto", True):
                    new = [e for e in eps if e.get("feed_id") == f["id"] and e.get("status") in ("new", "error")]
                    picks += new[:1]
    seen, out = set(), []
    for e in picks:
        if e["id"] not in seen:
            seen.add(e["id"])
            out.append(e)
    return out[:MAX_PER_RUN]


def main():
    auto = "--auto" in sys.argv
    eps = todo(auto)
    if "--check" in sys.argv:  # Actions用：処理対象があるかだけ返す
        print("has_work=" + ("true" if eps else "false"))
        return
    for e in eps:
        print("prepare:", e["id"], flush=True)
        prepare(e["id"])


if __name__ == "__main__":
    main()
