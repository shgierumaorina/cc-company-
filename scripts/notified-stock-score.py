"""
Discord通知済み銘柄（底値圏/急騰）の再スコア評価（手動実行）
データソース: .company/japan-stock/picks-log.tsv（daily-picks.pyの通知ログ）
- 底値圏 = bottom（底値反転確認、digest経由で通知）+ higherlow（底値切り上げ、直接通知）
- 急騰   = gap（寄りギャップ、直接通知）+ closestrong（引け強銘柄、直接通知）
直近N営業日ぶんのtsvから各モード上位N位以内に一定回数以上出現した銘柄を抽出し、
yfinanceの最新データ（RSI・BB・25日線乖離・出来高倍率・PER/PBR）で機械的にスコア評価する。
"""
import sys, io, os, json, argparse
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import yfinance as yf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PICKS_LOG_PATH = os.path.join(ROOT, ".company", "japan-stock", "picks-log.tsv")

BOTTOM_MODES = {"bottom", "higherlow"}
SURGE_MODES = {"gap", "closestrong"}


def load_candidates(days, top_n, min_occur):
    if not os.path.exists(PICKS_LOG_PATH):
        print(f"ERROR: {PICKS_LOG_PATH} が見つかりません")
        sys.exit(1)

    with open(PICKS_LOG_PATH, encoding="utf-8") as f:
        next(f)
        rows = [line.rstrip("\n").split("\t") for line in f if line.strip()]

    dates = sorted({r[0][:10] for r in rows if len(r) == 6}, reverse=True)[:days]
    date_set = set(dates)

    def collect(modes):
        seen = {}
        for r in rows:
            if len(r) != 6:
                continue
            dt, mode, rank, code, name, price = r
            if dt[:10] not in date_set or mode not in modes or int(rank) > top_n:
                continue
            entry = seen.setdefault(code, {"code": code, "name": name, "count": 0})
            entry["count"] += 1
        return [v for v in seen.values() if v["count"] >= min_occur]

    return collect(BOTTOM_MODES), collect(SURGE_MODES), dates


def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    diffs = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(d, 0) for d in diffs]
    losses = [max(-d, 0) for d in diffs]
    ag = sum(gains[:period]) / period
    al = sum(losses[:period]) / period
    for i in range(period, len(diffs)):
        ag = (ag * (period - 1) + gains[i]) / period
        al = (al * (period - 1) + losses[i]) / period
    if al == 0:
        return 100.0
    return round(100 - 100 / (1 + ag / al), 1)


def calc_bb(closes, period=20):
    if len(closes) < period:
        return None, None
    w = closes[-period:]
    mean = sum(w) / period
    std = (sum((x - mean) ** 2 for x in w) / period) ** 0.5
    return round(mean - 2 * std, 2), round(mean + 2 * std, 2)


def analyze(code, name, group):
    t = yf.Ticker(f"{code}.T")
    hist = t.history(period="90d")
    if hist.empty or len(hist) < 30:
        return {"code": code, "name": name, "group": group, "error": "データ不足"}
    closes = hist["Close"].tolist()
    vols = hist["Volume"].tolist()
    price = closes[-1]
    day_chg = (closes[-1] - closes[-2]) / closes[-2] * 100
    ma25 = sum(closes[-25:]) / 25
    dev25 = (price - ma25) / ma25 * 100
    trend5 = (closes[-1] - closes[-6]) / closes[-6] * 100 if len(closes) >= 6 else None
    rsi = calc_rsi(closes)
    bb_lo, bb_hi = calc_bb(closes)
    avg_vol20 = sum(vols[-21:-1]) / 20 if len(vols) >= 21 else None
    vol_ratio = vols[-1] / avg_vol20 if avg_vol20 else None

    try:
        info = t.info
        per = info.get("trailingPE")
        pbr = info.get("priceToBook")
    except Exception:
        per = pbr = None

    score = 0
    reasons = []
    if group == "bottom":
        if rsi is not None and rsi < 35:
            score += 25; reasons.append(f"RSI{rsi}(売られすぎ)")
        elif rsi is not None and rsi < 45:
            score += 10
        if bb_lo is not None and price <= bb_lo * 1.02:
            score += 20; reasons.append("BB下限近辺")
        if dev25 < -3:
            score += 15; reasons.append(f"25日線乖離{dev25:+.1f}%")
        if trend5 is not None and trend5 > 0:
            score += 20; reasons.append(f"直近5日{trend5:+.1f}%(反発)")
        elif trend5 is not None and trend5 < -5:
            score -= 15; reasons.append(f"直近5日{trend5:+.1f}%(下落継続=下げ止まり未確認)")
        if day_chg > 0:
            score += 10
        if pbr is not None and pbr < 1.2:
            score += 10; reasons.append(f"PBR{pbr:.2f}")
    else:  # surge
        if trend5 is not None and trend5 > 3:
            score += 25; reasons.append(f"直近5日{trend5:+.1f}%(上昇継続)")
        elif trend5 is not None and trend5 > 0:
            score += 10
        if vol_ratio is not None and vol_ratio > 1.5:
            score += 20; reasons.append(f"出来高{vol_ratio:.1f}倍")
        if day_chg > 1:
            score += 15; reasons.append(f"当日{day_chg:+.1f}%")
        if rsi is not None and rsi > 70:
            score -= 20; reasons.append(f"RSI{rsi}(過熱警戒)")
        elif rsi is not None and 50 <= rsi <= 68:
            score += 15
        if dev25 is not None and dev25 > 12:
            score -= 15; reasons.append(f"25日線乖離{dev25:+.1f}%(過熱)")
        elif dev25 is not None and dev25 > 0:
            score += 10

    return {
        "code": code, "name": name, "group": group, "price": round(price, 1),
        "day_chg": round(day_chg, 2), "rsi": rsi, "bb_lo": bb_lo, "bb_hi": bb_hi,
        "dev25": round(dev25, 2) if dev25 is not None else None,
        "trend5": round(trend5, 2) if trend5 is not None else None,
        "vol_ratio": round(vol_ratio, 2) if vol_ratio is not None else None,
        "per": per, "pbr": pbr, "score": score, "reasons": reasons,
    }


def main():
    parser = argparse.ArgumentParser(description="Discord通知済み底値圏/急騰銘柄の再スコア評価(手動実行)")
    parser.add_argument("--days", type=int, default=5, help="picks-log.tsvを遡る営業日数(デフォルト5)")
    parser.add_argument("--top-n", type=int, default=5, help="各モードの上位何位までを対象にするか(デフォルト5)")
    parser.add_argument("--min-occur", type=int, default=2, help="対象期間中の最低出現回数(デフォルト2)")
    parser.add_argument("--json", help="結果をJSONファイルにも出力する場合のパス")
    args = parser.parse_args()

    bottom_c, surge_c, dates = load_candidates(args.days, args.top_n, args.min_occur)
    print(f"対象期間: {dates[-1]}〜{dates[0]}（{len(dates)}営業日、上位{args.top_n}位以内・{args.min_occur}回以上出現）")
    print(f"底値圏候補: {len(bottom_c)}銘柄 / 急騰候補: {len(surge_c)}銘柄\n")

    results = []
    for c in bottom_c:
        try:
            results.append(analyze(c["code"], c["name"], "bottom"))
        except Exception as e:
            results.append({"code": c["code"], "name": c["name"], "group": "bottom", "error": str(e)})
    for c in surge_c:
        try:
            results.append(analyze(c["code"], c["name"], "surge"))
        except Exception as e:
            results.append({"code": c["code"], "name": c["name"], "group": "surge", "error": str(e)})

    for group, label in (("bottom", "=== 底値圏候補 ==="), ("surge", "=== 急騰候補 ===")):
        print(label)
        rows = sorted([r for r in results if r["group"] == group and "error" not in r],
                      key=lambda r: -r["score"])
        for r in rows:
            reasons = " / ".join(r["reasons"]) if r["reasons"] else "シグナル弱い"
            print(f"[{r['code']}] {r['name']} score={r['score']} {r['price']}円 "
                  f"{r['day_chg']:+.1f}% RSI{r['rsi']} 25日線乖離{r['dev25']:+.1f}% "
                  f"5日{r['trend5']:+.1f}% PER{r['per']} PBR{r['pbr']} | {reasons}")
        for r in [x for x in results if x["group"] == group and "error" in x]:
            print(f"[{r['code']}] {r['name']}: {r['error']}")
        print()

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"JSON出力: {args.json}")


if __name__ == "__main__":
    main()
