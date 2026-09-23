"""
us-stock-score.py の判定を「実際に約定できる価格」で採点する検証スクリプト（手動実行・読み取り専用）。
国内版 rescore-picks.py の米国株版。

採点ルール:
  - エントリー: 判定を実行した時刻(run_utc)より後に最初に来る米国市場の「寄り」
    判定に使うのは確定足なので、判定時点ではもうその日の寄りは買えない。
    米東部時間9:30より前に実行していればその日の寄り、後なら翌営業日の寄りで買う。
  - イグジット: --hold-days 営業日ぶん保有したあとの終値（既定1日＝当日引け）
  - 往復コスト（手数料+為替スプレッド+スリッページ）を差し引く。--cost で指定する。
  - 保有中に株式分割が入ると未調整価格が見かけ上下がるため、売値を分割倍率で戻す。
    配当落ちは調整していない（その分リターンは控えめに出る）
  - score別・グループ別に、日次クラスタの t値 で優位性を判定する
    （同じ日に出た銘柄は相関するため、1銘柄1標本として扱うとt値が過大になる）

出力: .company/us-stock/outcomes.tsv
"""
import sys, io, os, argparse, warnings
from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
warnings.filterwarnings("ignore")

import numpy as np
import yfinance as yf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PICKS_LOG_PATH = os.path.join(ROOT, ".company", "us-stock", "picks-log.tsv")
OUT_PATH = os.path.join(ROOT, ".company", "us-stock", "outcomes.tsv")
ET = ZoneInfo("America/New_York")
MARKET_OPEN = dtime(9, 30)          # 米東部時間の寄り
DEFAULT_COST_PCT = 0.5              # 往復コストの既定値（%ポイント）。実コストは証券会社による
SCORE_BUCKETS = [(80, 10 ** 9, "score>=80"), (60, 80, "score60-79"), (-10 ** 9, 60, "score<60")]


def load_picks():
    """picks-log を読む。同じ (base_date, group, ticker) は1件に畳む。"""
    if not os.path.exists(PICKS_LOG_PATH):
        print(f"ERROR: {PICKS_LOG_PATH} がありません。先に us-stock-score.py を実行してください")
        sys.exit(1)
    picks, seen = [], set()
    with open(PICKS_LOG_PATH, encoding="utf-8") as f:
        next(f, None)
        for line in f:
            p = line.rstrip("\n").split("\t")
            if len(p) != 8:
                continue
            key = (p[1], p[2], p[4])
            if key in seen:
                continue
            seen.add(key)
            picks.append(dict(
                run_utc=datetime.strptime(p[0], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=ZoneInfo("UTC")),
                base_date=p[1], group=p[2], rank=int(p[3]), ticker=p[4],
                name=p[5], score=int(p[6]), price=float(p[7])))
    return picks


def entry_session(run_utc, sessions):
    """run_utc より後に最初に買える取引日を返す（買えるのは寄りだけと仮定する）。"""
    run_et = run_utc.astimezone(ET)
    d = run_et.date()
    for s in sessions:                      # sessions は昇順の取引日
        if s > d or (s == d and run_et.time() < MARKET_OPEN):
            return s
    return None                             # まだ寄りが来ていない = 未確定


def split_ratio(df, entry_day, exit_day):
    """entry翌日〜exit当日に実施された株式分割の累積倍率。

    未調整(auto_adjust=False)の終値を使うため、保有中に分割が入ると価格が見かけ上
    下がる。株数は増えているので、売値にこの倍率を掛けて元のスケールへ戻す。
    """
    factor = 1.0
    try:
        splits = df["Stock Splits"].dropna()
    except Exception:
        return factor
    for i, ratio in splits.items():
        if ratio and ratio > 0 and entry_day < i.date() <= exit_day:
            factor *= float(ratio)
    return factor


def evaluate(picks, data, cost_pct, hold_days=1):
    """戻り値: 採点行, 未確定件数, 株価取得不可件数, 窓外件数"""
    rows, pending, missing, out_of_window = [], 0, 0, 0
    for x in picks:
        try:
            df = data[x["ticker"]]
            opens, closes = df["Open"].dropna(), df["Close"].dropna()
        except Exception:
            missing += 1
            continue
        if len(opens) == 0 or len(closes) == 0:
            missing += 1
            continue
        sessions = sorted({i.date() for i in opens.index})
        day = entry_session(x["run_utc"], sessions)
        if day is None:
            pending += 1
            continue
        # 取得窓より古い判定は、窓の先頭を「翌寄り」と誤認して架空の利益を作る。
        # 判定から10日以上あとの寄りしか無いものは採点せず、窓外として明示する。
        if (day - x["run_utc"].astimezone(ET).date()).days > 10:
            out_of_window += 1
            continue
        i_entry = sessions.index(day)
        i_exit = i_entry + hold_days - 1
        if i_exit >= len(sessions):
            pending += 1
            continue
        exit_day = sessions[i_exit]
        idx_e = next((i for i in opens.index if i.date() == day), None)
        idx_x = next((i for i in closes.index if i.date() == exit_day), None)
        if idx_e is None or idx_x is None:
            pending += 1
            continue
        entry, exit_px = float(opens[idx_e]), float(closes[idx_x])
        if entry <= 0:
            pending += 1
            continue
        gross = (exit_px * split_ratio(df, day, exit_day) / entry - 1) * 100
        rows.append((x, day, exit_day, entry, exit_px, gross, gross - cost_pct))
    return rows, pending, missing, out_of_window


def save(rows):
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write("base_date\tentry_date\texit_date\tgroup\trank\tticker\tname\tscore"
                "\tentry\texit\tret_gross\tret_net\n")
        for x, day, exit_day, entry, exit_px, gross, net in rows:
            f.write(f"{x['base_date']}\t{day}\t{exit_day}\t{x['group']}\t{x['rank']}\t{x['ticker']}\t"
                    f"{x['name']}\t{x['score']}\t{entry:.2f}\t{exit_px:.2f}\t{gross:+.2f}\t{net:+.2f}\n")


# 自由度 n-1 に対する t分布の両側95%点（標本が小さいと正規近似では区間が狭すぎる）
T95 = {2: 12.71, 3: 4.30, 4: 3.18, 5: 2.78, 6: 2.57, 7: 2.45, 8: 2.36, 9: 2.31, 10: 2.26,
       12: 2.20, 15: 2.14, 20: 2.09, 25: 2.06, 30: 2.05, 35: 2.03, 40: 2.02}


def t95(n):
    """自由度 n-1 の両側95%点。表に無い n は表にある直近の小さい n に丸める（区間を狭めない）。"""
    if n > 40:
        return 1.96
    return T95[max(k for k in T95 if k <= n)]


def daily_stats(by_day):
    """日ごとの平均を1標本として 平均・t値・95%CI を返す（同じ日の銘柄は相関するため）。"""
    means = [np.mean(v) for v in by_day.values()]
    n = len(means)
    if n < 2:
        return float("nan"), float("nan"), float("nan"), float("nan"), n
    m = float(np.mean(means))
    se = float(np.std(means, ddof=1) / np.sqrt(n))
    if se == 0:
        return m, float("nan"), float("nan"), float("nan"), n
    q = t95(n)
    return m, m / se, m - q * se, m + q * se, n


def report(rows, min_days):
    """score帯 × グループで集計する。判定はどちらも「買い」前提。"""
    agg = {}
    for x, day, _xd, _e, _x2, _g, net in rows:
        label = next(lbl for lo, hi, lbl in SCORE_BUCKETS if lo <= x["score"] < hi)
        for key in (f"{x['group']}/{label}", f"{x['group']}/ALL"):
            s = agg.setdefault(key, dict(n=0, win=0, nets=[], days={}))
            s["n"] += 1
            s["nets"].append(net)
            s["win"] += 1 if net > 0 else 0
            s["days"].setdefault(str(day), []).append(net)
    lines = [f"{'区分':<22}{'件数':>7}{'日数':>6}{'勝率':>8}{'取引平均':>10}"
             f"{'日次平均':>10}{'95%CI':>21}{'t値':>8}  判定"]
    for key in sorted(agg):
        s = agg[key]
        dm, t, lo, hi = daily_stats(s["days"])[:4]
        if s["n"] == 0 or np.isnan(t):
            verdict, ci, tt = "データ不足", "-", "-"
        else:
            ci = f"[{lo:+.3f}, {hi:+.3f}]"
            tt = f"{t:.2f}"
            if len(s["days"]) < min_days:
                verdict = f"判定保留(日数{len(s['days'])}<{min_days})"
            else:
                # 区分を同時に何本も検定しているため、t>2 は「候補」止まりで断定しない
                verdict = "残る(要多重検定の割引)" if t > 2 else "優位性を検出できず"
        dm_s = "-" if np.isnan(dm) else f"{dm:+.3f}%"
        lines.append(f"{key:<22}{s['n']:>7}{len(s['days']):>6}{s['win'] / s['n'] * 100:>7.1f}%"
                     f"{np.mean(s['nets']):>+9.3f}%{dm_s:>10}{ci:>21}{tt:>8}  {verdict}")
    return lines


def main():
    p = argparse.ArgumentParser(description="us-stock-score.py の判定を約定可能価格で採点する")
    p.add_argument("--cost", type=float, default=DEFAULT_COST_PCT,
                   help=f"往復コスト%%（手数料+為替スプレッド+スリッページ、既定{DEFAULT_COST_PCT}）")
    p.add_argument("--min-days", type=int, default=20,
                   help="優位性の判定を始める最低営業日数(デフォルト20)")
    p.add_argument("--hold-days", type=int, default=1,
                   help="保有営業日数(デフォルト1=翌寄り買い当日引け売り)。底値圏は1日で決着しないので複数日も試す")
    args = p.parse_args()

    picks = load_picks()
    if not picks:
        print("picks-log.tsv に判定履歴がありません")
        return 1
    tickers = sorted({x["ticker"] for x in picks})
    d0 = min(x["base_date"] for x in picks)
    d1 = max(x["base_date"] for x in picks)
    print(f"判定 {len(picks)}件 / 銘柄 {len(tickers)} / 基準日 {d0} 〜 {d1}")

    # 取得期間は必ずログ最古の判定日をカバーさせる。足りないと古い判定が
    # 「取得窓の先頭 = 数ヶ月後の寄り」で約定したことにされ、架空の利益が混ざる。
    start = (datetime.strptime(d0, "%Y-%m-%d").date() - timedelta(days=10)).isoformat()
    data = yf.download(tickers, start=start, progress=False, group_by="ticker",
                       auto_adjust=False, actions=True, threads=True)
    rows, pending, missing, oow = evaluate(picks, data, args.cost, args.hold_days)
    save(rows)
    print(f"採点 {len(rows)}件 / 未確定(寄り待ち) {pending}件 / 株価取得不可 {missing}件"
          + (f" / 窓外(株価取得期間より古く採点不可) {oow}件" if oow else ""))
    print(f"翌寄り買い→{args.hold_days}営業日保有で引け売り、往復コスト {args.cost}%控除後 "
          f"→ {os.path.relpath(OUT_PATH, ROOT)}")
    if not rows:
        print("\nまだ採点できる判定がありません。エントリーの寄りが来てから再実行してください。")
        return 0

    print()
    print("\n".join(report(rows, args.min_days)))
    gross_by_day = {}
    for x, day, _xd, _e, _x2, g, _n in rows:
        gross_by_day.setdefault(str(day), []).append(g)
    gm, gt = daily_stats(gross_by_day)[:2]
    print()
    print(f"コスト控除前の全体日次平均: {'-' if np.isnan(gm) else f'{gm:+.3f}%'} "
          f"(t={'-' if np.isnan(gt) else f'{gt:.2f}'})")
    days = len({str(d) for _x, d, _xd, _e, _x2, _g, _n in rows})
    if days < args.min_days:
        print(f"※ 営業日数 {days} は判定に足りない（最低{args.min_days}日）。"
              f"この時点の数字で売買判断をしない。")
    print(f"※ 往復コスト {args.cost}% は仮定値。証券会社の実際の手数料と為替スプレッドに置き換えること。")
    print("※ 区分を同時に複数検定しているため、どれか1本が t>2 になるのは偶然でも起こる。")
    print("  「残る」は候補であって確定ではない。保有日数を変えて結果が消えないかも確認すること。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
