"""過去データで「安値圏×出来高急増」シグナルを再現し、その後の値動きを検証するバックテスト
実行例:
  python backtest.py                          # 優良銘柄マスタ(passed=true)・過去2年
  python backtest.py --universe watchlist      # 監視リストのみ
  python backtest.py --years 3 --codes 7203,6758
"""
import sys
import io
import argparse
from pathlib import Path
from datetime import datetime, time as dtime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import numpy as np
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config_loader
import universe_manager as um
import signal_detector

RESULTS_DIR = Path(__file__).resolve().parent / "backtest_results"
FORWARD_DAYS = (5, 10)
WARMUP_DAYS = 100          # MA75・出来高平均が安定するまでの最低営業日数
VOL_RATIO_GRID = [2.0, 2.5, 3.0, 3.5]
STOP_LOSS_GRID = [7.0, 8.0, 9.0, 10.0]


def load_universe(source: str, codes_arg: str | None) -> list[dict]:
    if codes_arg:
        codes = [c.strip() for c in codes_arg.split(",") if c.strip()]
        return [{"code": c, "name": c} for c in codes]
    if source == "watchlist":
        return [{"code": w["code"], "name": w.get("name", w["code"])} for w in um.load_watchlist()]
    return [{"code": m["code"], "name": m.get("name", m["code"])}
            for m in um.load_master() if m.get("passed")]


def fetch_batch(tickers: list[str], years: int) -> dict:
    data = yf.download(tickers, period=f"{years}y", progress=False, group_by="ticker", threads=True)
    out = {}
    for t in tickers:
        try:
            df = data[t].dropna(subset=["Open", "High", "Low", "Close", "Volume"])
            if len(df) >= WARMUP_DAYS + max(FORWARD_DAYS) + 1:
                out[t] = df
        except Exception:
            continue
    return out


def replay_signals(code: str, df, cfg: dict) -> list[dict]:
    """1銘柄分、ルックアヘッドなしで各日のシグナルを再現し、その後の値動きを記録する。"""
    records = []
    forward_max = max(FORWARD_DAYS)
    for i in range(WARMUP_DAYS, len(df) - forward_max):
        hist_slice = df.iloc[:i + 1]
        eval_date = df.index[i]
        now = datetime.combine(eval_date.date(), dtime(15, 1))  # 場後扱い=按分なしで判定させる

        low_price = signal_detector.check_low_price(hist_slice, cfg)
        volume_surge = signal_detector.check_volume_surge(hist_slice, cfg, now)
        liquidity = signal_detector.check_liquidity(hist_slice, cfg)
        confirmation = signal_detector.check_confirmation(hist_slice, cfg)
        strength = signal_detector.classify_strength(low_price, volume_surge, liquidity, confirmation)
        if strength is None:
            continue

        entry = df["Close"].iloc[i]
        rec = {
            "code": code, "date": eval_date.strftime("%Y-%m-%d"),
            "strength": strength, "entry": float(entry),
            "vol_ratio": volume_surge["ratio"],
        }
        window_low = df["Low"].iloc[i + 1:i + forward_max + 1]
        rec["max_drawdown_pct"] = float((window_low.min() / entry - 1) * 100) if not window_low.empty else None
        for d in FORWARD_DAYS:
            fwd_close = df["Close"].iloc[i + d]
            rec[f"ret_{d}d_pct"] = float((fwd_close / entry - 1) * 100)
        records.append(rec)
    return records


def summarize(records: list[dict], key_filter=None) -> dict:
    rows = [r for r in records if key_filter is None or key_filter(r)]
    out = {"n": len(rows)}
    for d in FORWARD_DAYS:
        rets = [r[f"ret_{d}d_pct"] for r in rows]
        if rets:
            out[f"win_rate_{d}d"] = sum(1 for x in rets if x > 0) / len(rets) * 100
            out[f"avg_ret_{d}d"] = float(np.mean(rets))
        else:
            out[f"win_rate_{d}d"] = None
            out[f"avg_ret_{d}d"] = None
    dds = [r["max_drawdown_pct"] for r in rows if r["max_drawdown_pct"] is not None]
    out["avg_max_drawdown"] = float(np.mean(dds)) if dds else None
    return out


def simulate_stop_loss(records: list[dict], stop_loss_pct: float) -> dict:
    """各シグナルについて、10営業日の窓内でstop_loss_pctを下回ったら-stop_loss_pct%で損切りしたとみなして
    シミュレーション後リターンを計算する。損切りに触れなければ実際の10営業日後リターンを使う。
    """
    sim_rets = []
    for r in records:
        if r["max_drawdown_pct"] is not None and r["max_drawdown_pct"] <= -stop_loss_pct:
            sim_rets.append(-stop_loss_pct)
        else:
            sim_rets.append(r["ret_10d_pct"])
    if not sim_rets:
        return {"n": 0, "avg_ret": None, "win_rate": None}
    return {
        "n": len(sim_rets),
        "avg_ret": float(np.mean(sim_rets)),
        "win_rate": sum(1 for x in sim_rets if x > 0) / len(sim_rets) * 100,
    }


def build_report(records: list[dict], universe_n: int, years: int) -> str:
    lines = [f"# jp_stock_alert バックテスト結果 ({datetime.now().strftime('%Y-%m-%d %H:%M')})", ""]
    lines.append(f"対象: {universe_n}銘柄 / 過去{years}年 / データソース: yfinance")
    lines.append(f"検出シグナル総数: {len(records)}件")
    lines.append("")

    lines.append("## 強度別サマリ")
    lines.append("| 区分 | 件数 | 5日勝率 | 5日平均リターン | 10日勝率 | 10日平均リターン | 平均最大DD(10日) |")
    lines.append("|---|---|---|---|---|---|---|")
    for label, flt in [("強", lambda r: r["strength"] == "strong"),
                        ("弱", lambda r: r["strength"] == "weak"),
                        ("全体", None)]:
        s = summarize(records, flt)
        if s["n"] == 0:
            lines.append(f"| {label} | 0 | - | - | - | - | - |")
            continue
        lines.append(f"| {label} | {s['n']} | {s['win_rate_5d']:.0f}% | {s['avg_ret_5d']:+.2f}% | "
                      f"{s['win_rate_10d']:.0f}% | {s['avg_ret_10d']:+.2f}% | {s['avg_max_drawdown']:+.2f}% |")
    lines.append("")

    lines.append("## 出来高倍率しきい値別（10営業日後リターン、そのしきい値以上の全シグナル）")
    lines.append("| 倍率しきい値 | 件数 | 勝率 | 平均リターン |")
    lines.append("|---|---|---|---|")
    vol_grid_results = []
    for th in VOL_RATIO_GRID:
        s = summarize(records, lambda r, th=th: r["vol_ratio"] is not None and r["vol_ratio"] >= th)
        vol_grid_results.append((th, s))
        if s["n"] == 0:
            lines.append(f"| {th}x以上 | 0 | - | - |")
        else:
            lines.append(f"| {th}x以上 | {s['n']} | {s['win_rate_10d']:.0f}% | {s['avg_ret_10d']:+.2f}% |")
    lines.append("")

    lines.append("## 損切り幅しきい値別シミュレーション（10営業日の窓内で損切りした場合）")
    lines.append("| 損切り幅 | 件数 | 勝率 | シミュレーション後平均リターン |")
    lines.append("|---|---|---|---|")
    stop_grid_results = []
    for sl in STOP_LOSS_GRID:
        s = simulate_stop_loss(records, sl)
        stop_grid_results.append((sl, s))
        if s["n"] == 0:
            lines.append(f"| -{sl}% | 0 | - | - |")
        else:
            lines.append(f"| -{sl}% | {s['n']} | {s['win_rate']:.0f}% | {s['avg_ret']:+.2f}% |")
    lines.append("")

    lines.append("## 閾値チューニング案")
    best_vol = max((v for v in vol_grid_results if v[1]["n"] >= 10), key=lambda v: v[1]["avg_ret_10d"] or -999,
                   default=None)
    best_stop = max((v for v in stop_grid_results if v[1]["n"] >= 10), key=lambda v: v[1]["avg_ret"] or -999,
                     default=None)
    if best_vol:
        lines.append(f"- 出来高倍率: {best_vol[0]}x以上が過去データ上もっとも平均リターンが高い"
                      f"（{best_vol[1]['n']}件、勝率{best_vol[1]['win_rate_10d']:.0f}%、"
                      f"平均{best_vol[1]['avg_ret_10d']:+.2f}%）")
    else:
        lines.append("- 出来高倍率: サンプル不足（各しきい値10件未満）のため提案なし")
    if best_stop:
        lines.append(f"- 損切り幅: -{best_stop[0]}%が過去データ上もっとも平均リターンが高い"
                      f"（{best_stop[1]['n']}件、勝率{best_stop[1]['win_rate']:.0f}%、"
                      f"平均{best_stop[1]['avg_ret']:+.2f}%）")
    else:
        lines.append("- 損切り幅: サンプル不足（各しきい値10件未満）のため提案なし")
    lines.append("")
    lines.append("※ 過去データに基づく参考値。実際の閾値変更は`config.yaml`をユーザーが確認の上で編集すること。")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--universe", choices=["master", "watchlist"], default="master")
    parser.add_argument("--years", type=int, default=2)
    parser.add_argument("--codes", type=str, default=None)
    args = parser.parse_args()

    cfg = config_loader.load_config()
    universe = load_universe(args.universe, args.codes)
    if not universe:
        print("ERROR: 対象銘柄が0件です（優良銘柄マスタ/監視リストを確認してください）")
        sys.exit(1)

    tickers = [f"{u['code']}.T" for u in universe]
    names = {f"{u['code']}.T": u["name"] for u in universe}
    print(f"対象 {len(tickers)}銘柄 / 過去{args.years}年 のデータを取得中...")
    batch = fetch_batch(tickers, args.years)
    print(f"取得成功 {len(batch)}銘柄")

    all_records = []
    for i, (ticker, df) in enumerate(batch.items(), 1):
        code = ticker.replace(".T", "")
        try:
            recs = replay_signals(code, df, cfg)
            all_records.extend(recs)
            if i % 10 == 0:
                print(f"  {i}/{len(batch)}銘柄処理済み...")
        except Exception as e:
            print(f"  {code}: エラー {e}")

    print(f"検出シグナル総数: {len(all_records)}件")
    report = build_report(all_records, len(batch), args.years)
    print("\n" + report)

    RESULTS_DIR.mkdir(exist_ok=True)
    out_path = RESULTS_DIR / f"{datetime.now().strftime('%Y-%m-%d')}-backtest.md"
    out_path.write_text(report, encoding="utf-8")
    print(f"\nレポートを保存しました: {out_path}")


if __name__ == "__main__":
    main()
