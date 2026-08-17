"""jp_stock_alertで通知した銘柄のフォローアップ（通知後の複数ホライズンのリターン集計・手動実行）
データソース: jp_stock_alert/notified_log.tsv（notifier.pyが通知成功のたびに追記）
通知価格を基準に、翌営業日・2〜5営業日後・10営業日後(≈2週間後)の騰落率を計算し、
コンソール表示 + Discord通知 + ObsidianVault(wiki/japan-stock.md)への記録を行う。
"""
import sys
import io
import argparse
from pathlib import Path
from datetime import datetime, timedelta

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import requests
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from envutil import get_secret

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config_loader
import obsidian_writer

NOTIFIED_LOG_PATH = Path(__file__).resolve().parent / "notified_log.tsv"
HORIZONS = [(1, "翌日"), (2, "2日後"), (3, "3日後"), (4, "4日後"), (5, "5日後"), (10, "2週間後")]


def load_notifications(days: int) -> list[dict]:
    if not NOTIFIED_LOG_PATH.exists():
        return []
    cutoff = datetime.now() - timedelta(days=days)
    entries = []
    with open(NOTIFIED_LOG_PATH, encoding="utf-8") as f:
        next(f, None)
        for line in f:
            p = line.rstrip("\n").split("\t")
            if len(p) != 5:
                continue
            dt = datetime.strptime(p[0], "%Y-%m-%d %H:%M")
            if dt < cutoff:
                continue
            entries.append({"dt": dt, "code": p[1], "name": p[2], "price": float(p[3]), "strength": p[4]})
    entries.sort(key=lambda e: e["dt"], reverse=True)
    return entries


def find_anchor_pos(dates: list, notif_date) -> int | None:
    """通知日時点(またはそれ以前で最も近い営業日)のインデックスを返す"""
    pos = None
    for i, d in enumerate(dates):
        if d <= notif_date:
            pos = i
        else:
            break
    return pos


def compute_returns(entries: list[dict]) -> list[dict]:
    hist_cache = {}
    results = []
    for e in entries:
        code = e["code"]
        if code not in hist_cache:
            try:
                hist_cache[code] = yf.Ticker(f"{code}.T").history(period="6mo")
            except Exception:
                hist_cache[code] = None
        hist = hist_cache[code]
        row = dict(e)
        if hist is None or hist.empty:
            row["error"] = "株価データ取得失敗"
            results.append(row)
            continue
        dates = [d.date() for d in hist.index]
        pos0 = find_anchor_pos(dates, e["dt"].date())
        if pos0 is None:
            row["error"] = "通知日時点の株価データなし"
            results.append(row)
            continue
        closes = hist["Close"].tolist()
        for h, _ in HORIZONS:
            pos = pos0 + h
            row[f"ret_{h}"] = (closes[pos] / e["price"] - 1) * 100 if pos < len(closes) else None
        results.append(row)
    return results


def print_table(results: list[dict]) -> None:
    header = "通知日時       コード 銘柄            強弱 通知価格 " + " ".join(f"{l:>8}" for _, l in HORIZONS)
    print(header)
    print("-" * len(header))
    for r in results:
        if r.get("error"):
            print(f"{r['dt']:%Y-%m-%d %H:%M} {r['code']:<6} {r['name']:<10} {r['strength']:<4} "
                  f"{r['price']:>8,.0f} {r['error']}")
            continue
        cells = " ".join(f"{r[f'ret_{h}']:+7.1f}%" if r[f"ret_{h}"] is not None else f"{'未到達':>8}"
                          for h, _ in HORIZONS)
        print(f"{r['dt']:%Y-%m-%d %H:%M} {r['code']:<6} {r['name']:<10} {r['strength']:<4} "
              f"{r['price']:>8,.0f} {cells}")


def build_discord_content(results: list[dict], days: int) -> str:
    lines = [f"📈 **jp_stock_alert フォローアップレポート** {datetime.now().strftime('%m/%d %H:%M')}",
             f"対象: 過去{days}日 {len(results)}件", ""]
    for r in results:
        head = f"**{r['code']} {r['name']}** [{r['strength']}] 通知{r['price']:,.0f}円 ({r['dt']:%m/%d %H:%M})"
        if r.get("error"):
            lines.append(f"- {head} → {r['error']}")
            continue
        detail = " ".join(
            f"{l}{r[f'ret_{h}']:+.1f}%" if r[f"ret_{h}"] is not None else f"{l}未到達"
            for h, l in HORIZONS
        )
        lines.append(f"- {head}\n  {detail}")
    lines.append("\n※通知価格（発生時点の現在値）基準・営業日ベース")
    content = "\n".join(lines)
    if len(content) > 1990:
        content = content[:1980] + "\n(以下略)"
    return content


def send_discord_report(results: list[dict], days: int) -> None:
    webhook_url = get_secret("DISCORD_WEBHOOK_URL_KABU")
    if not webhook_url:
        print("[ERROR] DISCORD_WEBHOOK_URL_KABU が設定されていません（リポジトリ直下の.envを確認）")
        return
    content = build_discord_content(results, days)
    resp = requests.post(webhook_url, json={"content": content}, timeout=30)
    resp.raise_for_status()
    print("[OK] Discord通知送信")


def main() -> int:
    parser = argparse.ArgumentParser(description="jp_stock_alert 通知済み銘柄のフォローアップ集計")
    parser.add_argument("--days", type=int, default=60, help="notified_log.tsvを遡る日数(デフォルト60)")
    parser.add_argument("--no-notify", action="store_true", help="Discord通知を送らない")
    args = parser.parse_args()

    entries = load_notifications(args.days)
    if not entries:
        print(f"対象期間(過去{args.days}日)に通知履歴がありません（{NOTIFIED_LOG_PATH}）")
        return 0

    print(f"対象: 過去{args.days}日 {len(entries)}件\n")
    results = compute_returns(entries)
    print_table(results)

    cfg = config_loader.load_config()
    obsidian_writer.record_followup_report(cfg, results, args.days)

    if args.no_notify:
        print("(Discord通知スキップ: --no-notify)")
    else:
        try:
            send_discord_report(results, args.days)
        except requests.RequestException as e:
            print(f"[ERROR] Discord送信失敗: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
