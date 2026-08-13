"""1回分のシグナルチェック実行（タスクスケジューラ・watch.pyから呼ばれる）
条件: 監視リスト(watchlist.json) ∩ 優良銘柄マスタ(passed=true) の銘柄について
      安値圏×出来高急増の両方が成立したものだけをDiscord通知する。
"""
import sys
import io
from pathlib import Path
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config_loader
import universe_manager as um
import signal_detector
import notifier

LOG_PATH = Path(__file__).resolve().parent / "logs" / "check_signals.log"


def log(msg: str) -> None:
    LOG_PATH.parent.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def is_market_hours(now: datetime, sessions: list) -> bool:
    if now.weekday() >= 5:
        return False
    now_min = now.hour * 60 + now.minute
    for start_s, end_s in sessions:
        sh, sm = map(int, start_s.split(":"))
        eh, em = map(int, end_s.split(":"))
        if sh * 60 + sm <= now_min <= eh * 60 + em:
            return True
    return False


def main() -> int:
    cfg = config_loader.load_config()

    if not is_market_hours(datetime.now(), cfg["market_hours"]["sessions"]):
        log("市場時間外 - スキップ")
        return 0

    watchlist = um.load_watchlist()
    master = {m["code"]: m for m in um.load_master()}

    if not watchlist:
        log("監視リストが空です。manage_universe.py add で銘柄を追加してください")
        return 0

    hits = []
    for w in watchlist:
        code = w["code"]
        master_entry = master.get(code)
        if master_entry is None or not master_entry.get("passed"):
            log(f"  {code}: 優良銘柄マスタ未通過のためスキップ")
            continue

        try:
            result = signal_detector.evaluate(code, cfg)
        except Exception as e:
            log(f"  {code}: エラー {e}")
            continue

        if result is None:
            log(f"  {code}: 株価データ不足")
            continue

        log(f"  {code} {master_entry.get('name','')}: "
            f"価格={result['price']} 安値圏={result['low_price']['passed']} "
            f"出来高急増={result['volume_surge']['passed']} ratio={result['volume_surge']['ratio']}")

        if result["signal"]:
            hits.append((result, master_entry.get("name", "")))

    if not hits:
        log("シグナルなし")
        return 0

    log(f"シグナル検出: {[r['code'] for r, _ in hits]}")
    notifier.send_signals(hits, cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
