"""ポッドキャスト（RSS）の登録と新着確認。"""
import hashlib
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from . import store

UA = "Mozilla/5.0 (compatible; ListeningLab/1.0)"
ITUNES = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"
MEDIA = "{http://search.yahoo.com/mrss/}"
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp")
MEDIA_EXT = (".mp3", ".m4a", ".mp4", ".aac", ".ogg", ".oga", ".opus", ".wav", ".webm", ".mov", ".m4v")
KEEP = 15  # 1番組あたり一覧に載せる最新回の数
NOT_RSS = ("このURLは番組のRSSではありませんでした。Apple Podcastsで番組を開き、"
           "そのページのURL（podcasts.apple.com/…）を貼ってください")


def http_get(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=timeout)


def resolve_feed_url(url):
    """Apple PodcastsのURLやRSSのURLから、RSSのURLを得る。"""
    url = url.strip()
    if "open.spotify.com" in url:
        raise ValueError("Spotifyのリンクからは音声を取得できません。Apple PodcastsのURLかRSSのURLを貼ってください")
    if "podcasts.apple.com" in url or "itunes.apple.com" in url:
        m = re.search(r"id(\d+)", url)
        if not m:
            raise ValueError("Apple PodcastsのURLから番組IDが見つかりません")
        with http_get(f"https://itunes.apple.com/lookup?id={m.group(1)}&entity=podcast") as r:
            data = json.loads(r.read().decode("utf-8"))
        for res in data.get("results", []):
            if res.get("feedUrl"):
                return res["feedUrl"]
        raise ValueError("この番組のRSSが見つかりませんでした")
    if not url.startswith("http"):
        raise ValueError("URLを確認してください")
    return url


def _discover_rss(html, base_url):
    """番組のWebページ（HTML）から、RSSへのリンクを探す。"""
    for tag in re.findall(r"<link\b[^>]*>", html, flags=re.I):
        if re.search(r"application/(rss|atom)\+xml", tag, flags=re.I):
            m = re.search(r"href=[\"']([^\"']+)", tag, flags=re.I)
            if m:
                return urllib.parse.urljoin(base_url, m.group(1).replace("&amp;", "&"))
    return None


def find_feed(url):
    """URLがRSSならそのまま、番組のWebページならページ内のRSSリンクを返す。"""
    with http_get(url) as r:
        body = r.read()
    try:
        if ET.fromstring(body).find("channel") is not None:
            return url
    except ET.ParseError:
        pass
    rss = _discover_rss(body.decode("utf-8", "replace"), url)
    if not rss:
        raise ValueError(NOT_RSS)
    return rss


def fetch_feed(feed_url):
    with http_get(feed_url) as r:
        body = r.read()
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        raise ValueError(NOT_RSS) from None
    ch = root.find("channel")
    if ch is None:
        raise ValueError(NOT_RSS)
    title = (ch.findtext("title") or "").strip()
    items = []
    for it in ch.findall("item"):
        audio = _media_url(it)
        if not audio:  # 画像だけの回など、音声・動画のない回は除く
            continue
        try:
            ts = parsedate_to_datetime(it.findtext("pubDate") or "").timestamp()
        except (TypeError, ValueError):
            ts = 0
        items.append({
            "id": hashlib.sha1(audio.encode("utf-8")).hexdigest()[:12],
            "title": (it.findtext("title") or "").strip(),
            "audio_url": audio,
            "published_ts": ts,
            "duration_text": (it.findtext(f"{ITUNES}duration") or "").strip(),
        })
    items.sort(key=lambda x: x["published_ts"], reverse=True)
    return title, items


def _media_url(item):
    """回の中から音声（なければ動画）のURLを選ぶ。画像などは選ばない。"""
    cands = item.findall("enclosure") + item.findall(f"{MEDIA}content") + item.findall(f"{MEDIA}group/{MEDIA}content")
    for prefix in ("audio/", "video/"):
        for c in cands:
            if c.get("url") and (c.get("type") or "").lower().startswith(prefix):
                return c.get("url")
    # 種類の書き方が曖昧な配信（application/octet-stream など）は、画像・文章でなければ拡張子で判断
    usable = [c for c in cands if c.get("url") and not (c.get("type") or "").lower().startswith(("image/", "text/"))]
    for c in usable:
        if urllib.parse.urlparse(c.get("url")).path.lower().endswith(MEDIA_EXT):
            return c.get("url")
    for c in usable:
        if not urllib.parse.urlparse(c.get("url")).path.lower().endswith(IMAGE_EXT):
            return c.get("url")
    return None


def register_items(fid, show_title, items):
    """フィードのエピソードを一覧に登録（まだ処理はしない）。新しく増えた回のIDを返す。"""
    eps = store.list_episodes()
    for m in eps:  # 以前の版で登録された、画像だけの回を片付ける
        path = urllib.parse.urlparse(m.get("audio_url", "")).path.lower()
        if m.get("feed_id") == fid and m.get("status") in ("new", "error") and path.endswith(IMAGE_EXT):
            store.delete(f"ep:{m['id']}:meta")
    known = {m["id"] for m in eps}
    new = []
    for it in items[:KEEP]:
        if it["id"] in known:
            continue
        store.save_episode_meta(it["id"], {**it, "feed_id": fid, "show": show_title,
                                           "status": "new", "progress": 0, "message": ""})
        new.append(it["id"])
    return new


def add_feed(url):
    feed_url = find_feed(resolve_feed_url(url))
    title, items = fetch_feed(feed_url)
    if not items:
        raise ValueError("この番組には音声・動画ファイルのある回が見つかりませんでした（画像や記事だけの配信は使えません）")
    cfg = store.config()
    fid = hashlib.sha1(feed_url.encode("utf-8")).hexdigest()[:10]
    if not any(f["id"] == fid for f in cfg["feeds"]):
        cfg["feeds"].append({"id": fid, "title": title, "feed_url": feed_url,
                             "auto": True, "last_check": store.now_iso()})
        store.save_config(cfg)
    register_items(fid, title, items)
    return fid


def check_feeds():
    cfg = store.config()
    found = []
    for f in cfg["feeds"]:
        try:
            title, items = fetch_feed(f["feed_url"])
            found += register_items(f["id"], title or f["title"], items)
            f["last_check"] = store.now_iso()
            f.pop("last_error", None)
        except Exception as e:  # noqa: BLE001
            f["last_error"] = str(e)[:200]
    # 設定画面での変更と競合しないよう、番組の確認結果だけを書き戻す
    latest = store.config()
    by_id = {f["id"]: f for f in cfg["feeds"]}
    for f in latest["feeds"]:
        if f["id"] in by_id:
            f["last_check"] = by_id[f["id"]].get("last_check")
            if "last_error" in by_id[f["id"]]:
                f["last_error"] = by_id[f["id"]]["last_error"]
            else:
                f.pop("last_error", None)
    store.save_config(latest)
    return found
