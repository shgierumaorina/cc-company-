"""
米国株（S&P500）の「優良×安値圏×出来高急増」自動判定（手動実行）
国内版 notified-stock-score.py の移植。国内は daily-picks.py の通知ログ(picks-log.tsv)から
候補を拾うが、米国株にはその土台がないため、S&P500全銘柄を毎回スクリーニングして候補を作る。

  1) .company/us-stock/sp500.tsv のユニバースを読む（無ければWikipediaから取得しキャッシュ）
  2) yfinanceで全銘柄の6ヶ月足を一括取得し、共通テクニカル（RSI/BB/25日線乖離/出来高倍率）を計算
  3) 底値圏(bottom)・急騰(surge)の候補を機械的に抽出
  4) 各グループ上位のみファンダ(PER/PBR/ROE/利益率)を取得し、最終スコアを確定
"""
import sys, io, os, json, argparse
from datetime import datetime, timezone, time as dtime
from zoneinfo import ZoneInfo
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import numpy as np
import pandas as pd
import yfinance as yf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UNIVERSE_PATH = os.path.join(ROOT, ".company", "us-stock", "sp500.tsv")
PICKS_LOG_PATH = os.path.join(ROOT, ".company", "us-stock", "picks-log.tsv")
ET = ZoneInfo("America/New_York")
BAR_SETTLED = dtime(16, 15)   # 米東部の大引け16:00 + 日足が固まるまでの余裕
WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


def refresh_universe():
    """WikipediaのS&P500構成銘柄表を取得して ticker<TAB>name でキャッシュする"""
    tables = pd.read_html(WIKI_URL, storage_options={"User-Agent": "Mozilla/5.0"})
    df = next((t for t in tables if "Symbol" in t.columns and "Security" in t.columns), None)
    if df is None or df.empty:
        raise RuntimeError(f"S&P500構成銘柄の表を {WIKI_URL} から読めませんでした（表構造の変更かアクセス拒否）")
    os.makedirs(os.path.dirname(UNIVERSE_PATH), exist_ok=True)
    tmp = UNIVERSE_PATH + ".tmp"  # 書き切ってから差し替える（壊れたtsvを残さない）
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("ticker\tname\n")
        for sym, name in zip(df["Symbol"], df["Security"]):
            f.write(f"{str(sym).strip().replace('.', '-')}\t{str(name).strip()}\n")
    os.replace(tmp, UNIVERSE_PATH)
    return len(df)


def load_universe():
    if not os.path.exists(UNIVERSE_PATH):
        n = refresh_universe()
        print(f"ユニバース未取得のためWikipediaから取得しました: {n}銘柄 -> {UNIVERSE_PATH}")
    with open(UNIVERSE_PATH, encoding="utf-8") as f:
        next(f)
        rows = [l.rstrip("\n").split("\t") for l in f if l.strip()]
    return [r[0] for r in rows], {r[0]: r[1] for r in rows}


def rsi_last(close, period=14):
    d = close.diff()
    gain = d.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-d.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    g, l = float(gain.iloc[-1]), float(loss.iloc[-1])
    if pd.isna(g) or pd.isna(l):
        return None
    if l == 0:  # 全戻しなしの上昇。移植元と同じく100を返す(過熱減点を効かせるため)
        return 100.0
    return round(100 - 100 / (1 + g / l), 1)


def screen(tickers, closed_only=False):
    """全銘柄の共通テクニカル指標を1パスで計算する。

    米国市場の取引時間中に実行すると最終足が未確定で出来高が過少になり、
    出来高急増の判定が壊れる。最終足が当日ぶんで、かつ大引けから十分たっていない
    場合は自動で捨てる（自動実行でいつ走っても記録が汚れないようにするため）。
    closed_only=True なら日付に関係なく常に最終足を捨てる。"""
    data = yf.download(tickers, period="6mo", progress=False, group_by="ticker", threads=True)
    now_et = datetime.now(ET)
    out, skipped, dropped = [], [], 0
    for t in tickers:
        try:
            df = data[t].dropna()
            if len(df) and (closed_only or (df.index[-1].date() == now_et.date()
                                            and now_et.time() < BAR_SETTLED)):
                df = df.iloc[:-1]
                dropped += 1
            if len(df) < 60:
                skipped.append(f"{t}:データ不足({len(df)}本)")
                continue
            c, v = df["Close"], df["Volume"]
            price = float(c.iloc[-1])
            ma25 = float(c.iloc[-25:].mean())
            w = c.iloc[-20:]
            bb_lo = float(w.mean() - 2 * w.std(ddof=0))
            bb_hi = float(w.mean() + 2 * w.std(ddof=0))
            avg_vol20 = float(v.iloc[-21:-1].mean())
            out.append({
                "ticker": t, "price": round(price, 2),
                "day_chg": round(float((c.iloc[-1] - c.iloc[-2]) / c.iloc[-2] * 100), 2),
                "trend5": round(float((c.iloc[-1] - c.iloc[-6]) / c.iloc[-6] * 100), 2),
                "dev25": round((price - ma25) / ma25 * 100, 2),
                "rsi": rsi_last(c), "bb_lo": round(bb_lo, 2), "bb_hi": round(bb_hi, 2),
                "vol_ratio": round(float(v.iloc[-1]) / avg_vol20, 2) if avg_vol20 else None,
                "date": str(df.index[-1].date()),
            })
        except Exception as e:
            skipped.append(f"{t}:{type(e).__name__} {e}")
    return out, skipped, dropped


def pick_candidates(rows):
    """国内版の bottom / surge に相当する候補を機械的に抽出する"""
    bottom = [dict(x) for x in rows if x["rsi"] is not None and x["rsi"] < 45
              and x["dev25"] < 0 and x["price"] <= x["bb_lo"] * 1.05]
    surge = [dict(x) for x in rows if x["vol_ratio"] is not None and x["vol_ratio"] > 1.5
             and x["day_chg"] > 0 and x["trend5"] > 0]
    return bottom, surge


def score_technical(x, group):
    """国内版 notified-stock-score.py と同じ配点（ファンダ以外）"""
    s, reasons = 0, []
    rsi, dev25, trend5, day_chg, vr = x["rsi"], x["dev25"], x["trend5"], x["day_chg"], x["vol_ratio"]
    if group == "bottom":
        if rsi is not None and rsi < 35:
            s += 25; reasons.append(f"RSI{rsi}(売られすぎ)")
        elif rsi is not None and rsi < 45:
            s += 10
        if x["price"] <= x["bb_lo"] * 1.02:
            s += 20; reasons.append("BB下限近辺")
        if dev25 < -3:
            s += 15; reasons.append(f"25日線乖離{dev25:+.1f}%")
        if trend5 > 0:
            s += 20; reasons.append(f"直近5日{trend5:+.1f}%(反発)")
        elif trend5 < -5:
            s -= 15; reasons.append(f"直近5日{trend5:+.1f}%(下落継続=下げ止まり未確認)")
        if day_chg > 0:
            s += 10
    else:
        if trend5 > 3:
            s += 25; reasons.append(f"直近5日{trend5:+.1f}%(上昇継続)")
        elif trend5 > 0:
            s += 10
        if vr is not None and vr > 1.5:
            s += 20; reasons.append(f"出来高{vr:.1f}倍")
        if day_chg > 1:
            s += 15; reasons.append(f"当日{day_chg:+.1f}%")
        if rsi is not None and rsi > 70:
            s -= 20; reasons.append(f"RSI{rsi}(過熱警戒)")
        elif rsi is not None and 50 <= rsi <= 68:
            s += 15
        if dev25 > 12:
            s -= 15; reasons.append(f"25日線乖離{dev25:+.1f}%(過熱)")
        elif dev25 > 0:
            s += 10
    return s, reasons


def add_fundamentals(x):
    """米国株は国内のPBR<1.2がほぼ成立しないため、収益性(ROE/利益率)を優良判定に加える"""
    try:
        info = yf.Ticker(x["ticker"]).info
    except Exception:
        info = {}
    x["per"] = info.get("trailingPE")
    x["pbr"] = info.get("priceToBook")
    x["roe"] = info.get("returnOnEquity")
    x["margin"] = info.get("profitMargins")
    if x["roe"] is not None and x["roe"] > 0.15:
        x["score"] += 10; x["reasons"].append(f"ROE{x['roe'] * 100:.0f}%")
    if x["margin"] is not None and x["margin"] > 0.10:
        x["score"] += 5; x["reasons"].append(f"利益率{x['margin'] * 100:.0f}%")
    if x["pbr"] is not None and 0 < x["pbr"] < 3.0:  # 負のPBR(債務超過)は割安ではないので除外
        x["score"] += 5; x["reasons"].append(f"PBR{x['pbr']:.2f}")
    if x["per"] is not None and 0 < x["per"] < 20:
        x["score"] += 5; x["reasons"].append(f"PER{x['per']:.1f}")
    return x


def log_picks(results, base_date):
    """判定結果を picks-log.tsv に追記する（後から us-rescore-picks.py で答え合わせするため）。

    run_utc は「いつ判定したか」。米国市場の寄りを何回またいだかで実際に買える日が決まるため、
    基準日(base_date)だけでは足りず、実行時刻をUTCで残す。
    同じ (base_date, group, ticker) は再実行しても二重に書かない。
    """
    run_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    seen, is_new = set(), not os.path.exists(PICKS_LOG_PATH)
    if not is_new:
        with open(PICKS_LOG_PATH, encoding="utf-8") as f:
            next(f, None)
            for line in f:
                p = line.rstrip("\n").split("\t")
                if len(p) >= 5:
                    seen.add((p[1], p[2], p[4]))
    os.makedirs(os.path.dirname(PICKS_LOG_PATH), exist_ok=True)
    added = 0
    with open(PICKS_LOG_PATH, "a", encoding="utf-8") as f:
        if is_new:
            f.write("run_utc\tbase_date\tgroup\trank\tticker\tname\tscore\tprice\n")
        for group in ("bottom", "surge"):
            ranked = sorted([r for r in results if r["group"] == group], key=lambda r: -r["score"])
            for rank, r in enumerate(ranked, 1):
                if (base_date, group, r["ticker"]) in seen:
                    continue
                seen.add((base_date, group, r["ticker"]))
                added += 1
                f.write(f"{run_utc}\t{base_date}\t{group}\t{rank}\t{r['ticker']}\t"
                        f"{r['name']}\t{r['score']}\t{r['price']}\n")
    return added


def fmt(v, digits=1, suffix=""):
    return "-" if v is None else f"{v:.{digits}f}{suffix}"


def main():
    p = argparse.ArgumentParser(description="S&P500の底値圏/急騰銘柄を機械スコア評価する(手動実行)")
    p.add_argument("--top-n", type=int, default=15, help="各グループでファンダ取得する上位件数(デフォルト15)")
    p.add_argument("--limit", type=int, help="ユニバースの先頭N銘柄だけ対象にする(動作確認用)")
    p.add_argument("--closed-only", action="store_true",
                   help="常に最終足を捨てる(取引中の自動除外は既定で働くため、通常は不要)")
    p.add_argument("--refresh-universe", action="store_true", help="S&P500構成銘柄をWikipediaから取り直す")
    p.add_argument("--json", help="結果をJSONファイルにも出力する場合のパス")
    p.add_argument("--no-log", action="store_true",
                   help="picks-log.tsv に記録しない(動作確認用。答え合わせの母数を汚さないため)")
    args = p.parse_args()

    if args.refresh_universe:
        print(f"ユニバース更新: {refresh_universe()}銘柄 -> {UNIVERSE_PATH}")
    tickers, names = load_universe()
    if args.limit:
        tickers = tickers[:args.limit]
    print(f"対象: {len(tickers)}銘柄を取得中...")

    rows, skipped, dropped = screen(tickers, closed_only=args.closed_only)
    if dropped and not args.closed_only:
        print(f"未確定の最終足を自動で除外しました（{dropped}銘柄／米国市場が取引中または大引け直後）")
    if skipped:
        print(f"スキップ {len(skipped)}銘柄: " + ", ".join(skipped[:5])
              + (f" ...他{len(skipped) - 5}件" if len(skipped) > 5 else ""))
    if not rows:
        print("ERROR: 株価データを取得できませんでした")
        sys.exit(1)
    bottom, surge = pick_candidates(rows)
    print(f"基準日: {rows[0]['date']} / 指標算出: {len(rows)}銘柄")
    print(f"底値圏候補: {len(bottom)}銘柄 / 急騰候補: {len(surge)}銘柄\n")

    # テクニカル上位を広めに取ってからファンダを評価し、「優良」を最終順位に反映させる
    results = []
    for group, cands in (("bottom", bottom), ("surge", surge)):
        for x in cands:
            x["group"], x["name"] = group, names.get(x["ticker"], x["ticker"])
            x["score"], x["reasons"] = score_technical(x, group)
        pool = sorted(cands, key=lambda r: -r["score"])[:args.top_n * 3]
        results += sorted([add_fundamentals(x) for x in pool],
                          key=lambda r: -r["score"])[:args.top_n]

    for group, label in (("bottom", "=== 底値圏候補 ==="), ("surge", "=== 急騰候補 ===")):
        print(label)
        for r in sorted([x for x in results if x["group"] == group], key=lambda r: -r["score"]):
            reasons = " / ".join(r["reasons"]) if r["reasons"] else "シグナル弱い"
            print(f"[{r['ticker']}] {r['name']} score={r['score']} ${r['price']} "
                  f"{r['day_chg']:+.1f}% RSI{fmt(r['rsi'])} 25日線乖離{r['dev25']:+.1f}% "
                  f"5日{r['trend5']:+.1f}% 出来高{fmt(r['vol_ratio'], 2, '倍')} | {reasons}")
        print()

    if args.no_log or args.limit:
        print("※ picks-log には記録していません（--no-log / --limit 指定時）")
    else:
        n = log_picks(results, rows[0]["date"])
        print(f"picks-log 追記: {n}件 -> {os.path.relpath(PICKS_LOG_PATH, ROOT)}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"JSON出力: {args.json}")


if __name__ == "__main__":
    main()
