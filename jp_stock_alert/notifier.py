"""Discord Webhook通知 + 当日重複防止(クールダウン)
既存の discord_notifier.py（リポジトリ直下）のembed構造・requestsパターンを踏襲する。
"""
import sys
import json
from pathlib import Path
from datetime import datetime, date

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from envutil import get_secret

sys.path.insert(0, str(Path(__file__).resolve().parent))
import obsidian_writer

STATE_PATH = Path(__file__).resolve().parent / "notified_state.json"


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {}


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def in_cooldown(state: dict, code: str, cooldown_hours: float) -> bool:
    last = state.get(code)
    if not last:
        return False
    if cooldown_hours >= 24:
        # 24時間以上のクールダウンは「当日一度きり」として日付一致で判定する
        return datetime.fromisoformat(last).date() == date.today()
    elapsed_hours = (datetime.now() - datetime.fromisoformat(last)).total_seconds() / 3600
    return elapsed_hours < cooldown_hours


def mark_notified(state: dict, code: str) -> dict:
    state[code] = datetime.now().isoformat()
    return state


def build_embed(result: dict, name: str) -> dict:
    code = result["code"]
    lp = result["low_price"]
    vs = result["volume_surge"]
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = []
    ma_dev = lp["checks"].get("ma_deviation", {}).get("value")
    if ma_dev is not None:
        lines.append(f"25/75日線乖離率: {ma_dev:+.2f}%")
    w52 = lp["checks"].get("week52_low", {}).get("value")
    if w52 is not None:
        lines.append(f"52週安値からの上昇率: {w52:+.2f}%")
    dd = lp["checks"].get("drawdown", {}).get("value")
    if dd is not None:
        lines.append(f"直近高値からの下落率: {dd:+.2f}%")

    return {
        "title": f"優良銘柄 安値圏×出来高急増: {name} ({code})",
        "color": 0x00C851,
        "fields": [
            {"name": "現在値", "value": f"¥{result['price']:,.0f}", "inline": True},
            {"name": "当日出来高", "value": f"{vs['today_volume']:,}", "inline": True},
            {"name": "平均出来高比", "value": f"{vs['ratio']}倍", "inline": True},
            {"name": "安値圏シグナル", "value": "\n".join(lines) or "-", "inline": False},
        ],
        "footer": {"text": f"jp_stock_alert | 判定時刻 {now_str}"},
    }


def send_signals(results_with_names: list[tuple], cfg: dict) -> None:
    """results_with_names: [(signal_detector.evaluate結果, 銘柄名), ...]
    クールダウン判定・送信・state更新を行う。DISCORD_WEBHOOK_URL未設定時は送信せずログのみ出す。
    """
    webhook_url = get_secret("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("[ERROR] DISCORD_WEBHOOK_URL が設定されていません（リポジトリ直下の.envを確認）")
        return

    cooldown_hours = cfg["notify"]["cooldown_hours"]
    state = load_state()

    embeds = []
    to_notify = []  # [(code, result, name), ...] 送信対象(クールダウン外)のみ
    for result, name in results_with_names:
        code = result["code"]
        if in_cooldown(state, code, cooldown_hours):
            print(f"[SKIP] {code} はクールダウン中のため通知しません")
            continue
        embeds.append(build_embed(result, name))
        to_notify.append((code, result, name))

    if not embeds:
        print("[INFO] 通知対象なし")
        return

    # バッチ(最大10件)ごとに送信成功したものだけをその場でクールダウン登録・vault記録する。
    # 途中のバッチが失敗しても、既に成功したバッチ分を未送信扱いのまま残さない。
    for i in range(0, len(embeds), 10):
        batch = to_notify[i:i + 10]
        payload = {"embeds": embeds[i:i + 10]}
        try:
            resp = requests.post(webhook_url, json=payload, timeout=10)
            resp.raise_for_status()
            print(f"[OK] Discord通知送信 ({len(embeds[i:i+10])}件)")
        except requests.RequestException as e:
            print(f"[ERROR] Discord送信失敗: {e}")
            save_state(state)
            return

        for code, result, name in batch:
            state = mark_notified(state, code)
            obsidian_writer.record_notification(cfg, code, name, result)
        save_state(state)
