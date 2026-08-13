"""常駐ループ版 - 取引時間中(config.yamlのmarket_hours.sessions)のみcheck_signals.mainを定期実行する
使い方: python watch.py
タスクスケジューラで定期実行する場合は check_signals.py を直接呼ぶ方式(check_signals.pyのdocstring参照)でもよい。
"""
import sys
import io
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config_loader
import check_signals


def main():
    cfg = config_loader.load_config()
    interval_sec = cfg["watch"]["poll_interval_minutes"] * 60

    check_signals.log("watch.py 起動（Ctrl+Cで停止）")
    try:
        while True:
            check_signals.main()  # 市場時間外の判定はcheck_signals.main内部で行う
            time.sleep(interval_sec)
    except KeyboardInterrupt:
        check_signals.log("watch.py 停止")


if __name__ == "__main__":
    main()
