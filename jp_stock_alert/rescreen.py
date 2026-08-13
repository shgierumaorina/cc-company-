"""優良銘柄マスタの再選定バッチ
デフォルトの候補母集団は既存の nikkei225_screener.py の NIKKEI225_TICKERS（日経225構成銘柄）を再利用する。
使い方:
  python rescreen.py                      # 日経225全銘柄を再スコアリング
  python rescreen.py --codes 7203,6758     # 指定銘柄のみ
"""
import sys
import io
import argparse
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config_loader
import universe_manager as um
import obsidian_writer

try:
    from nikkei225_screener import NIKKEI225_TICKERS
    DEFAULT_CODES = [t.replace(".T", "") for t in NIKKEI225_TICKERS]
except ImportError:
    DEFAULT_CODES = []


def run(codes: list[str]) -> None:
    cfg = config_loader.load_config()
    master = um.load_master()

    newly_passed = []
    for i, code in enumerate(codes, 1):
        print(f"[{i}/{len(codes)}] {code} を評価中...")
        result = um.score_code(code, cfg)
        master = um.upsert_master(master, result)
        um.save_master(master)  # 途中終了しても直前までの結果を失わないよう都度保存する

        flag = "incomplete" if result["data_incomplete"] else "ok"
        print(f"  score={result['score']} passed={result['passed']} ({flag})")
        if result["passed"]:
            newly_passed.append(result)

    print("\n=== 再選定サマリ ===")
    print(f"評価銘柄数: {len(codes)}")
    print(f"優良銘柄マスタ通過: {len(newly_passed)}")
    for r in newly_passed:
        print(f"  {r['code']} {r['name']} score={r['score']}")

    obsidian_writer.record_quality_stocks(cfg, newly_passed)


def main():
    parser = argparse.ArgumentParser(description="優良銘柄マスタ再選定バッチ")
    parser.add_argument("--codes", help="銘柄コードをカンマ区切りで指定（省略時は日経225全銘柄）")
    args = parser.parse_args()

    if args.codes:
        codes = [c.strip() for c in args.codes.split(",") if c.strip()]
    else:
        if not DEFAULT_CODES:
            print("ERROR: --codes未指定かつ nikkei225_screener.py からNIKKEI225_TICKERSを読み込めませんでした")
            sys.exit(1)
        codes = DEFAULT_CODES

    run(codes)


if __name__ == "__main__":
    main()
