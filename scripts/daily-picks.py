"""
日次銘柄分析バッチ（AI不使用・テクニカル+バリュエーション）
モード（★=Discord通知あり、それ以外は記録のみで digest に集約）:
  --mode surge     (default) 急騰候補 上位20 … 毎日16:00 (cc-daily-picks) ※成績不振で通知停止中
  --mode value     割安高配当 厳選10         … 毎日17:00 (cc-value-picks)
  --mode bottom    底値反転確認 厳選10       … 毎日18:00 (cc-bottom-picks)
  --mode volsurge  出来高急増 上位40(場中)   … 平日 9:30 (cc-volsurge-picks) ※成績不振で通知停止中
  --mode higherlow 底値切り上げ 上位20(場中) … 平日9:00-15:30 30分おき (cc-higherlow-picks) ★
  --mode macro     朝の地合い予報            … 平日 7:30 (cc-macro-report) ★
  --mode gap       寄りギャップ 上位20       … 平日 9:20 (cc-gap-picks) ★
  --mode closestrong 引け強銘柄 上位20       … 平日15:50 (cc-closestrong-picks) ★
  --mode crash     急落スパイク 厳選10       … 毎日16:30 (cc-crash-picks)
  --mode pullback  押し目反発 厳選10         … 毎日16:40 (cc-pullback-picks)
  --mode sector    セクター資金ローテーション … 毎日18:30 (cc-sector-rotation)
  --mode squeeze   ボラ収縮 厳選10           … 毎日19:00 (cc-squeeze-picks)
  --mode overheat  過熱警告 厳選10           … 毎日19:10 (cc-overheat-picks)
  --mode digest    夕方ダイジェスト(上記まとめ) … 毎日19:30 (cc-evening-digest) ★
  --mode report    週次 的中率レポート(7日+4週) … 土曜10:00 (cc-weekly-report) ★
出力: .company/japan-stock/daily/YYYY-MM-DD-picks.md へ追記 + Discord通知
--no-notify で通知抑止 / --force で場中モードの当日データチェックを無視（テスト用）
"""
import sys, io, os, re, warnings
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
warnings.filterwarnings("ignore")

import requests
import yfinance as yf
import pandas as pd
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PICKS_DIR = os.path.join(ROOT, ".company", "japan-stock", "daily")
PICKS_LOG_PATH = os.path.join(ROOT, ".company", "japan-stock", "picks-log.tsv")
OUTCOMES_PATH = os.path.join(ROOT, ".company", "japan-stock", "outcomes.tsv")
sys.path.insert(0, ROOT)
from envutil import get_secret

# stock-screener.py と同じ株アラート用チャンネル
DISCORD_WEBHOOK_URL = get_secret("DISCORD_WEBHOOK_URL_KABU")

MODES = {
    "surge":     {"top": 20, "emoji": "📊", "title": "急騰候補 上位20"},
    "value":     {"top": 10, "emoji": "💰", "title": "割安高配当 厳選10"},
    "bottom":    {"top": 10, "emoji": "🔄", "title": "底値反転 厳選10"},
    "volsurge":  {"top": 40, "emoji": "⚡", "title": "出来高急増 上位40（9:30時点）"},
    "higherlow": {"top": 20, "emoji": "📈", "title": "底値切り上げ 上位20"},
    "macro":     {"top": 0,  "emoji": "🌅", "title": "朝の地合い予報"},
    "gap":       {"top": 20, "emoji": "🌄", "title": "寄りギャップ 上位20"},
    "closestrong": {"top": 20, "emoji": "🔒", "title": "引け強銘柄 上位20"},
    "crash":    {"top": 10, "emoji": "💥", "title": "急落スパイク（翌日リバ候補）厳選10"},
    "pullback": {"top": 10, "emoji": "🎯", "title": "押し目反発（MA25）厳選10"},
    "sector":   {"top": 0,  "emoji": "🔀", "title": "セクター資金ローテーション"},
    "squeeze":  {"top": 10, "emoji": "🧨", "title": "ボラ収縮（ブレイク前夜）厳選10"},
    "overheat": {"top": 10, "emoji": "🌡️", "title": "過熱警告（利確検討）厳選10"},
    "report":   {"top": 0,  "emoji": "🏁", "title": "週次 的中率レポート"},
    "digest":   {"top": 0,  "emoji": "🌇", "title": "本日の夕方ダイジェスト"},
}
INTRADAY_MODES = {"volsurge", "higherlow", "gap", "closestrong"}  # 当日データがない日（休場）は通知しない
# 通知せず picks-log への記録のみ行うモード:
# - surge/volsurge: 2026-07-12 週次振り返りで成績不振（勝率25%/30%・平均マイナス）のため通知停止。記録は継続し4週データで再判断
# - 夕方モード（crash〜sector）: 個別通知をやめ --mode digest（19:30 の1通）に統合
LOG_ONLY_MODES = {"surge", "volsurge", "crash", "pullback", "value", "bottom", "squeeze", "overheat", "sector"}
DIGEST_MODES = ["crash", "pullback", "value", "bottom", "squeeze", "overheat"]  # digest掲載順
DIGEST_TOP_N = 3


def nikkei225_universe():
    """nikkei225_screener.py からティッカー一覧と日本語銘柄名辞書を読む"""
    src = open(os.path.join(ROOT, "nikkei225_screener.py"), encoding="utf-8").read()
    body = re.search(r"NIKKEI225_TICKERS\s*=\s*\[(.*?)\]", src, re.S).group(1)
    tickers = re.findall(r'"([0-9A-Z]+\.T)"', body)
    names = dict(re.findall(r'"([0-9A-Z]+\.T)":\s*"([^"]+)"', src))
    return tickers, names


def rsi_series(close, period=14):
    d = close.diff()
    gain = d.clip(lower=0).rolling(period).mean()
    loss = (-d.clip(upper=0)).rolling(period).mean()
    return 100 - 100 / (1 + gain / loss.replace(0, np.nan))


def fetch_macro():
    out = []
    data = yf.download(["^N225", "JPY=X", "NIY=F"], period="5d", progress=False, group_by="ticker")
    for sym, label in [("^N225", "日経"), ("JPY=X", "ドル円"), ("NIY=F", "CME先物")]:
        try:
            c = data[sym]["Close"].dropna()
            chg = (c.iloc[-1] - c.iloc[-2]) / c.iloc[-2] * 100
            out.append(f"{label} {c.iloc[-1]:,.0f}({chg:+.1f}%)")
        except Exception:
            out.append(f"{label} 取得失敗")
    return " | ".join(out)


def screen(tickers):
    """全銘柄の共通テクニカル指標を1パスで計算"""
    data = yf.download(tickers, period="6mo", progress=False, group_by="ticker", threads=True)
    rows, last_date = [], None
    for t in tickers:
        try:
            df = data[t].dropna()
            if len(df) < 60:
                continue
            c, v = df["Close"], df["Volume"]
            last_date = df.index[-1].date()
            price = c.iloc[-1]
            day_chg = (c.iloc[-1] / c.iloc[-2] - 1) * 100
            avg_v = v.iloc[-21:-1].mean()
            vol_ratio = v.iloc[-1] / avg_v if avg_v > 0 else 0
            trend3 = (c.iloc[-1] / c.iloc[-4] - 1) * 100
            ma5, ma25 = c.rolling(5).mean(), c.rolling(25).mean()
            gc = ma5.iloc[-1] > ma25.iloc[-1] and ma5.iloc[-2] <= ma25.iloc[-2]
            ema12, ema26 = c.ewm(span=12).mean(), c.ewm(span=26).mean()
            macd = ema12 - ema26
            sig = macd.ewm(span=9).mean()
            hist = macd - sig
            macd_x = macd.iloc[-1] > sig.iloc[-1] and macd.iloc[-2] <= sig.iloc[-2]
            r = rsi_series(c)
            low90 = c.iloc[-90:].min() if len(c) >= 90 else c.min()
            ma75 = c.rolling(75).mean()
            ma20 = c.rolling(20).mean()
            sd20 = c.rolling(20).std()
            bbw = 4 * sd20 / ma20                       # BB(2σ)幅 / 中心線
            bbw_min60 = bbw.iloc[-61:-1].min()
            bbw_ratio = bbw.iloc[-1] / bbw_min60 if bbw_min60 and bbw_min60 > 0 else None
            idx60 = -min(len(c), 61)
            lows = df["Low"]
            hl_streak = 0  # 安値切り上げの連続日数
            for i in range(len(lows) - 1, 0, -1):
                if lows.iloc[i] > lows.iloc[i - 1]:
                    hl_streak += 1
                else:
                    break

            today_open = df["Open"].iloc[-1]
            rows.append(dict(
                code=t.replace(".T", ""), ticker=t, price=price,
                gap=(today_open / c.iloc[-2] - 1) * 100,
                from_open=(price / today_open - 1) * 100 if today_open > 0 else 0,
                close_pos=price / df["High"].iloc[-1] if df["High"].iloc[-1] > 0 else 0,
                day_chg=day_chg, vol_ratio=vol_ratio, trend3=trend3,
                rsi=r.iloc[-1], rsi_prev=r.iloc[-2], rsi5min=r.iloc[-5:].min(),
                gc=gc, macd_x=macd_x, hist_up=hist.iloc[-1] > hist.iloc[-2],
                brk=price >= c.iloc[-61:-1].max(),
                above_ma5=price > ma5.iloc[-1],
                below_ma25=price < ma25.iloc[-1],
                low90_gap=(price / low90 - 1) * 100,
                hl_streak=hl_streak,
                dev25=(price / ma25.iloc[-1] - 1) * 100,
                ma25_up=ma25.iloc[-1] > ma25.iloc[-6],
                touch_ma25=lows.iloc[-1] <= ma25.iloc[-1] * 1.01 and price >= ma25.iloc[-1],
                above_ma75=bool(pd.notna(ma75.iloc[-1]) and price > ma75.iloc[-1]),
                trend60=(price / c.iloc[idx60] - 1) * 100,
                bbw_ratio=bbw_ratio,
            ))
        except Exception:
            continue
    return rows, last_date


# ─── モード別スコアリング ─────────────────────────────

def score_surge(x):
    s = 0
    if x["vol_ratio"] >= 2.0: s += 40
    elif x["vol_ratio"] >= 1.5: s += 25
    elif x["vol_ratio"] >= 1.2: s += 10
    if x["trend3"] > 3: s += 30
    elif x["trend3"] > 1: s += 15
    if x["day_chg"] > 2: s += 20
    elif x["day_chg"] > 0.5: s += 10
    if x["gc"]: s += 10
    if x["macd_x"]: s += 10
    if x["brk"]: s += 15
    if x["rsi"] > 78: s -= 15  # 過熱は翌日続伸しにくい
    return s


def fetch_fundamentals(tickers):
    """配当利回り・PER・PBR を並列取得"""
    def one(t):
        try:
            info = yf.Ticker(t).info
            price = info.get("currentPrice") or info.get("previousClose")
            rate = info.get("trailingAnnualDividendRate")
            y = rate / price * 100 if rate and price else None
            if y is None:
                y = info.get("dividendYield")
                if y is not None and y < 0.5:  # 比率表記(0.035等)なら%へ
                    y *= 100
            return t, dict(yld=y, per=info.get("trailingPE"), pbr=info.get("priceToBook"))
        except Exception:
            return t, dict(yld=None, per=None, pbr=None)
    with ThreadPoolExecutor(max_workers=16) as ex:
        return dict(ex.map(one, tickers))


def score_value(x, f):
    """割安高配当: 利回り3%以上が対象。明確に割高(PER>18 or PBR>2)は除外"""
    y, per, pbr = f.get("yld"), f.get("per"), f.get("pbr")
    if not y or y < 3.0:
        return None
    if (per and per > 18) or (pbr and pbr > 2.0):
        return None
    s = y * 10                                   # 利回り 3.5% -> 35点
    if per and 0 < per <= 15: s += (15 - per) * 2
    if pbr and 0 < pbr <= 1.3: s += (1.3 - pbr) * 30
    if x["rsi"] < 40: s += 10                    # 売られすぎならさらに妙味
    return s


def score_crash(x):
    """急落スパイク: 当日-5%超かつ出来高2倍超。翌日リバウンド狙い"""
    if x["day_chg"] > -5.0 or x["vol_ratio"] < 2.0:
        return None
    return abs(x["day_chg"]) * 10 + min(x["vol_ratio"], 5) * 10


def score_pullback(x):
    """押し目反発: 上昇トレンド中(MA25上向き+MA75上)にMA25タッチ→反発"""
    if not (x["ma25_up"] and x["touch_ma25"] and x["above_ma75"]):
        return None
    s = 50 + min(max(x["trend60"], 0), 30)          # トレンドの強さ (最大30点)
    if x["day_chg"] > 0: s += 10
    if x["hist_up"]: s += 5
    if x["vol_ratio"] >= 1.2: s += 5
    return s


def score_squeeze(x):
    """ボラ収縮: BB幅が過去60日最小の1.15倍以内。ブレイク前夜候補"""
    if x["bbw_ratio"] is None or x["bbw_ratio"] > 1.15:
        return None
    s = (1.5 - x["bbw_ratio"]) * 100                 # 収縮がきついほど高スコア
    if not x["below_ma25"]: s += 10                  # 上方ブレイク素地
    return s


def score_overheat(x):
    """過熱警告: RSI80以上 or MA25乖離+10%以上。利確検討リスト"""
    if x["rsi"] < 80 and x["dev25"] < 10:
        return None
    return x["rsi"] + max(x["dev25"], 0) * 2


def log_picks(mode, top):
    """選定結果を機械可読ログに追記（週次的中率レポートの元データ）"""
    is_new = not os.path.exists(PICKS_LOG_PATH)
    with open(PICKS_LOG_PATH, "a", encoding="utf-8") as f:
        if is_new:
            f.write("datetime\tmode\trank\tcode\tname\tprice\n")
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        for i, x in enumerate(top, 1):
            f.write(f"{ts}\t{mode}\t{i}\t{x['code']}\t{x.get('name', x['code'])}\t{x['price']:.1f}\n")


def split_factor(splits, pick_date):
    """pick後に実施された株式分割の累積倍率を返す。

    picks-log の price は提案時点の実際の株価（未調整）だが、yfinance の終値は
    分割を遡って調整した値を返す。分割を挟むと -75% 等の幻の損失になるため、
    提案価格を同じ調整済みスケールへ揃えるための除数を求める。
    分割実施日当日の株価はすでに調整後なので、その日自体は対象に含めない。
    """
    factor = 1.0
    if splits is None:
        return factor
    for d, ratio in splits.items():
        if ratio and ratio > 0 and d.date() > pick_date:
            factor *= float(ratio)
    return factor


def save_outcomes(results):
    """評価済みの成績を機械可読ログへ追記する（picks-log は提案のみで結果を持たないため）。

    yfinance の履歴は約2ヶ月で取れなくなり、weekly_report も4週窓しか見ない。
    評価できた時点で残しておかないと、それ以前の実績は後から復元できない。
    同じ (提案日時, mode, code) は再実行しても二重に書かない。
    """
    seen = set()
    is_new = not os.path.exists(OUTCOMES_PATH)
    if not is_new:
        with open(OUTCOMES_PATH, encoding="utf-8") as f:
            next(f, None)
            for line in f:
                p = line.rstrip("\n").split("\t")
                if len(p) >= 3:
                    seen.add((p[0], p[1], p[2]))
    added = 0
    with open(OUTCOMES_PATH, "a", encoding="utf-8") as f:
        if is_new:
            f.write("datetime\tmode\tcode\tname\tentry_adj\texit_close\tret_pct\n")
        for x, entry, target, ret in results:
            key = (x["dt"].strftime("%Y-%m-%d %H:%M"), x["mode"], x["code"])
            if key in seen:
                continue
            seen.add(key)
            added += 1
            f.write(f"{key[0]}\t{x['mode']}\t{x['code']}\t{x['name']}\t"
                    f"{entry:.1f}\t{target:.1f}\t{ret:+.2f}\n")
    return added


def weekly_report():
    """直近7日+4週ローリングの提案を「提案後の翌終値」で評価し、モード別成績を集計"""
    from datetime import timedelta, time as dtime
    if not os.path.exists(PICKS_LOG_PATH):
        return ["提案ログ (picks-log.tsv) がまだありません"]

    cutoff7 = datetime.now() - timedelta(days=7)
    cutoff28 = datetime.now() - timedelta(days=28)
    picks = []
    with open(PICKS_LOG_PATH, encoding="utf-8") as f:
        next(f)  # ヘッダー
        for line in f:
            p = line.rstrip("\n").split("\t")
            if len(p) != 6:
                continue
            dt = datetime.strptime(p[0], "%Y-%m-%d %H:%M")
            if dt >= cutoff28:
                picks.append(dict(dt=dt, mode=p[1], code=p[3], name=p[4], price=float(p[5])))
    if not picks:
        return ["直近4週の提案記録がありません"]

    tickers = sorted({x["code"] + ".T" for x in picks})
    data = yf.download(tickers, period="2mo", progress=False, group_by="ticker", actions=True)

    stats, stats28, pending, results = {}, {}, 0, []
    evaluated, split_fixed = [], 0
    for x in picks:
        try:
            closes = data[x["code"] + ".T"]["Close"].dropna()
        except Exception:
            continue
        try:
            splits = data[x["code"] + ".T"]["Stock Splits"].dropna()
        except Exception:
            splits = None
        # 15時前の提案は当日終値、引け後の提案は翌営業日終値で評価
        pick_d = x["dt"].date()
        target = None
        for idx in closes.index:
            d = idx.date()
            if (x["dt"].time() < dtime(15, 0) and d >= pick_d) or d > pick_d:
                target = closes[idx]
                break
        if target is None:
            pending += 1
            continue
        # 終値は分割調整済みなので、提案価格も同じスケールへ揃える
        factor = split_factor(splits, pick_d)
        if factor != 1.0:
            split_fixed += 1
        entry = x["price"] / factor
        ret = (target / entry - 1) * 100
        evaluated.append((x, entry, target, ret))
        if x["mode"] == "overheat":
            ret_eval = -ret   # 過熱警告は下落で的中
        else:
            ret_eval = ret
        recent = x["dt"] >= cutoff7
        buckets = [stats28] + ([stats] if recent else [])
        for bucket in buckets:
            s = bucket.setdefault(x["mode"], dict(n=0, rets=[], win=0, hit=0))
            s["n"] += 1
            s["rets"].append(ret)
            if ret_eval > 0: s["win"] += 1
            if ret_eval >= 3: s["hit"] += 1
        if recent:
            results.append((ret, x))

    saved = save_outcomes(evaluated)
    n28 = sum(s["n"] for s in stats28.values())
    lines = [f"集計対象: 直近7日 {len(results)}件 / 4週 {n28}件 / 未確定(終値待ち): {pending}件",
             "評価 = 提案価格 → 提案後の翌終値。overheat のみ下落で的中扱い"]
    if split_fixed:
        lines.append(f"株式分割を挟んだ提案 {split_fixed}件は提案価格を分割調整して評価")
    lines.append(f"outcomes.tsv に新規 {saved}件を記録（累計の実績ログ）")
    lines.append("")
    modes_all = sorted(stats28, key=lambda m: -np.mean((stats.get(m) or stats28[m])["rets"]))
    for m in modes_all:
        note = "（下落で的中）" if m == "overheat" else ""
        if m in stats:
            s = stats[m]
            avg = np.mean(s["rets"])
            part7 = (f"7日: {s['n']}件 平均{avg:+.1f}% "
                     f"勝率{s['win']/s['n']*100:.0f}% 的中(+3%){s['hit']/s['n']*100:.0f}%")
        else:
            part7 = "7日: なし"
        s28 = stats28[m]
        avg28 = np.mean(s28["rets"])
        part28 = f"4週: {s28['n']}件 平均{avg28:+.1f}% 勝率{s28['win']/s28['n']*100:.0f}%"
        lines.append(f"**{m}**{note}: {part7} | {part28}")
    if results:
        results.sort(key=lambda r: r[0])
        worst, best = results[0], results[-1]
        lines.append("")
        lines.append(f"ベスト(7日): {best[1]['code']} {best[1]['name']} {best[0]:+.1f}% ({best[1]['mode']} {best[1]['dt']:%m/%d})")
        lines.append(f"ワースト(7日): {worst[1]['code']} {worst[1]['name']} {worst[0]:+.1f}% ({worst[1]['mode']} {worst[1]['dt']:%m/%d})")
    return lines


SECTOR_ETFS = {  # TOPIX-17 ETF (NEXT FUNDS)
    "1617.T": "食品", "1618.T": "エネルギー資源", "1619.T": "建設・資材",
    "1620.T": "素材・化学", "1621.T": "医薬品", "1622.T": "自動車・輸送機",
    "1623.T": "鉄鋼・非鉄", "1624.T": "機械", "1625.T": "電機・精密",
    "1626.T": "情報通信・サービス", "1627.T": "電力・ガス", "1628.T": "運輸・物流",
    "1629.T": "商社・卸売", "1630.T": "小売", "1631.T": "銀行",
    "1632.T": "金融(除く銀行)", "1633.T": "不動産",
}


def sector_report():
    """セクター資金ローテーション: TOPIX-17 ETFの騰落ランキング"""
    data = yf.download(list(SECTOR_ETFS), period="10d", progress=False, group_by="ticker")
    rows = []
    for t, name in SECTOR_ETFS.items():
        try:
            c = data[t]["Close"].dropna()
            if len(c) < 6:
                continue
            rows.append((name, (c.iloc[-1] / c.iloc[-2] - 1) * 100,
                         (c.iloc[-1] / c.iloc[-6] - 1) * 100))
        except Exception:
            continue
    rows.sort(key=lambda x: x[1], reverse=True)
    lines = []
    for i, (name, d1, d5) in enumerate(rows, 1):
        mark = "🔥" if d1 > 1 else "❄️" if d1 < -1 else "・"
        lines.append(f"{i}. {mark} {name} {d1:+.1f}% (5日 {d5:+.1f}%)")
    return lines


def digest_report(date_str=None):
    """夕方ピック各モードの上位を1通にまとめる（picks-log.tsv の当日分から生成）"""
    day = date_str or datetime.now().strftime("%Y-%m-%d")
    picks = {}
    if os.path.exists(PICKS_LOG_PATH):
        with open(PICKS_LOG_PATH, encoding="utf-8") as f:
            next(f)
            for line in f:
                p = line.rstrip("\n").split("\t")
                if len(p) != 6 or not p[0].startswith(day):
                    continue
                _, m, rank, code, name, price = p
                if m in DIGEST_MODES and int(rank) <= DIGEST_TOP_N:
                    picks.setdefault(m, {})[int(rank)] = (code, name, float(price))
    lines = []
    for m in DIGEST_MODES:
        if m not in picks:
            continue
        info = MODES[m]
        lines.append(f"{info['emoji']} **{info['title']}**")
        lines += [f"  {r}. {c} {n} ({pr:,.0f}円)" for r, (c, n, pr) in sorted(picks[m].items())]
    if not lines:
        lines.append("本日の夕方ピックはありません")
    try:
        sec = sector_report()
        if sec:
            lines += ["", "🔀 セクター資金ローテーション（上位/下位3）"]
            lines += sec[:3] + (["…"] + sec[-3:] if len(sec) > 6 else sec[3:])
    except Exception as e:
        lines += ["", f"セクター情報取得失敗: {e}"]
    return lines


def score_gap(x):
    """寄りギャップ: 前日終値比±2%以上で寄った銘柄。|ギャップ|でランキング"""
    if abs(x["gap"]) < 2.0:
        return None
    return abs(x["gap"])


def score_closestrong(x):
    """引け強: 当日高値から1%以内で引けた上昇銘柄。翌朝GU期待"""
    if x["close_pos"] < 0.99 or x["day_chg"] <= 0:
        return None
    s = 50
    s += min(x["day_chg"], 5) * 5              # 上昇率 (最大25点)
    if x["vol_ratio"] >= 2.0: s += 20
    elif x["vol_ratio"] >= 1.2: s += 10
    if x["brk"]: s += 15                        # 60日高値ブレイクなら翌日も注目されやすい
    if x["gc"]: s += 5
    return s


def macro_report():
    """朝の地合い予報: 前夜の米株・先物・為替から寄りの方向感を1通で"""
    syms = ["^GSPC", "^IXIC", "^SOX", "NIY=F", "JPY=X", "^N225"]
    labels = {"^GSPC": "S&P500", "^IXIC": "NASDAQ", "^SOX": "SOX(半導体)",
              "NIY=F": "CME日経先物", "JPY=X": "ドル円"}
    data = yf.download(syms, period="5d", progress=False, group_by="ticker")

    vals = {}
    for s in syms:
        try:
            c = data[s]["Close"].dropna()
            vals[s] = (c.iloc[-1], (c.iloc[-1] - c.iloc[-2]) / c.iloc[-2] * 100)
        except Exception:
            vals[s] = None

    lines = []
    us = []
    for s in ["^GSPC", "^IXIC", "^SOX"]:
        v = vals.get(s)
        us.append(f"{labels[s]} {v[1]:+.1f}%" if v else f"{labels[s]} 取得失敗")
    lines.append("米株: " + " | ".join(us))
    v = vals.get("JPY=X")
    if v:
        lines.append(f"ドル円: {v[0]:.2f} ({v[1]:+.1f}%)")

    fut, n225 = vals.get("NIY=F"), vals.get("^N225")
    mood = "中立"
    if fut and n225:
        gap = (fut[0] / n225[0] - 1) * 100
        direction = "ギャップアップ寄り想定" if gap >= 0.3 else "ギャップダウン寄り想定" if gap <= -0.3 else "フラット寄り想定"
        lines.append(f"CME先物: {fut[0]:,.0f} (前日日経終値比 {gap:+.1f}%) → {direction}")
        sox_chg = vals["^SOX"][1] if vals.get("^SOX") else 0
        if gap >= 0.5 and sox_chg > 0: mood = "強気"
        elif gap <= -0.5 or sox_chg < -2: mood = "弱気"
    lines.append(f"地合い判定: {mood}")
    return lines


def score_higherlow(x):
    """底値切り上げ: 安値を3日以上連続で切り上げ、かつ底値圏（90日安値+15%以内 or MA25未満）"""
    if x["hl_streak"] < 3:
        return None
    if x["low90_gap"] > 15 and not x["below_ma25"]:
        return None
    s = min(x["hl_streak"], 6) * 15                 # 切り上げ日数 (最大90点)
    if x["rsi"] > x["rsi_prev"]: s += 10
    if x["hist_up"]: s += 10
    if x["day_chg"] > 0: s += 5
    if x["vol_ratio"] >= 1.2: s += 10
    return s


def screen_volsurge(tickers):
    """場中の出来高急増: 当日ここまでの累積出来高を過去日の同時刻までの平均と比較"""
    data = yf.download(tickers, period="5d", interval="5m", progress=False,
                       group_by="ticker", threads=True)
    rows, target_date = [], None
    for t in tickers:
        try:
            df = data[t].dropna()
            if df.empty:
                continue
            dates = sorted(set(df.index.date))
            if len(dates) < 3:
                continue
            target_date = max(dates) if target_date is None else max(target_date, max(dates))
        except Exception:
            continue
    if target_date is None:
        return [], None

    for t in tickers:
        try:
            df = data[t].dropna()
            if df.empty:
                continue
            today_df = df[df.index.date == target_date]
            if today_df.empty:
                continue
            cutoff = today_df.index.max().time()
            cum_today = today_df["Volume"].sum()
            prior = []
            for d in sorted(set(df.index.date)):
                if d == target_date:
                    continue
                day = df[(df.index.date == d) & (df.index.time <= cutoff)]
                if not day.empty:
                    prior.append(day["Volume"].sum())
            if len(prior) < 2 or np.mean(prior) <= 0 or cum_today <= 0:
                continue
            ratio = cum_today / np.mean(prior)

            price = today_df["Close"].iloc[-1]
            prev_close = df[df.index.date < target_date]["Close"].iloc[-1]
            day_chg = (price / prev_close - 1) * 100

            rows.append(dict(code=t.replace(".T", ""), ticker=t, price=price,
                             day_chg=day_chg, ratio=ratio, cum_vol=cum_today,
                             score=ratio))  # スコア=同時刻比の出来高倍率
        except Exception:
            continue
    return rows, target_date


def score_bottom(x):
    """底値反転: 90日安値圏 + 直近売られすぎ + 反転シグナル確認が必須"""
    near_low = x["low90_gap"] <= 8.0
    oversold = x["rsi5min"] <= 35
    rsi_turn = x["rsi"] > x["rsi_prev"]
    price_turn = x["day_chg"] > 0 and x["above_ma5"]
    if not (near_low and oversold and (rsi_turn or price_turn)):
        return None
    s = 25 + 20                                  # near_low + oversold
    if rsi_turn: s += 15
    if price_turn: s += 20
    if x["hist_up"]: s += 10
    if x["vol_ratio"] >= 1.2 and x["day_chg"] > 0: s += 10
    return s


# ─── 出力 ─────────────────────────────────────────────

def table_lines(mode, top):
    if mode == "value":
        lines = ["| 順位 | コード | 銘柄 | スコア | 終値 | 利回り | PER | PBR | RSI |",
                 "|---|---|---|---|---|---|---|---|---|"]
        for i, x in enumerate(top, 1):
            f = x["fund"]
            per = f"{f['per']:.1f}" if f.get("per") else "-"
            pbr = f"{f['pbr']:.2f}" if f.get("pbr") else "-"
            lines.append(f"| {i} | {x['code']} | {x['name']} | {x['score']:.0f} | {x['price']:,.0f} | "
                         f"{f['yld']:.2f}% | {per} | {pbr} | {x['rsi']:.0f} |")
    elif mode == "bottom":
        lines = ["| 順位 | コード | 銘柄 | スコア | 終値 | 前日比 | RSI | 90日安値乖離 | 出来高比 |",
                 "|---|---|---|---|---|---|---|---|---|"]
        for i, x in enumerate(top, 1):
            lines.append(f"| {i} | {x['code']} | {x['name']} | {x['score']:.0f} | {x['price']:,.0f} | "
                         f"{x['day_chg']:+.1f}% | {x['rsi']:.0f} | +{x['low90_gap']:.1f}% | {x['vol_ratio']:.1f}x |")
    elif mode == "volsurge":
        lines = ["| 順位 | コード | 銘柄 | 出来高倍率(同時刻比) | 現在値 | 前日終値比 |",
                 "|---|---|---|---|---|---|"]
        for i, x in enumerate(top, 1):
            lines.append(f"| {i} | {x['code']} | {x['name']} | {x['ratio']:.1f}x | "
                         f"{x['price']:,.0f} | {x['day_chg']:+.1f}% |")
    elif mode == "higherlow":
        lines = ["| 順位 | コード | 銘柄 | スコア | 切り上げ日数 | 現在値 | 前日比 | RSI | 90日安値乖離 |",
                 "|---|---|---|---|---|---|---|---|---|"]
        for i, x in enumerate(top, 1):
            lines.append(f"| {i} | {x['code']} | {x['name']} | {x['score']:.0f} | {x['hl_streak']}日 | "
                         f"{x['price']:,.0f} | {x['day_chg']:+.1f}% | {x['rsi']:.0f} | +{x['low90_gap']:.1f}% |")
    elif mode == "gap":
        lines = ["| 順位 | コード | 銘柄 | ギャップ | 寄り後の動き | 現在値 |",
                 "|---|---|---|---|---|---|"]
        for i, x in enumerate(top, 1):
            arrow = "⬆GU" if x["gap"] > 0 else "⬇GD"
            lines.append(f"| {i} | {x['code']} | {x['name']} | {arrow} {x['gap']:+.1f}% | "
                         f"{x['from_open']:+.1f}% | {x['price']:,.0f} |")
    elif mode == "closestrong":
        lines = ["| 順位 | コード | 銘柄 | スコア | 終値 | 前日比 | 高値からの位置 | 出来高比 | 高値BRK |",
                 "|---|---|---|---|---|---|---|---|---|"]
        for i, x in enumerate(top, 1):
            lines.append(f"| {i} | {x['code']} | {x['name']} | {x['score']:.0f} | {x['price']:,.0f} | "
                         f"{x['day_chg']:+.1f}% | {(x['close_pos']-1)*100:+.1f}% | {x['vol_ratio']:.1f}x | "
                         f"{'○' if x['brk'] else '-'} |")
    elif mode == "crash":
        lines = ["| 順位 | コード | 銘柄 | スコア | 終値 | 前日比 | 出来高比 | RSI |",
                 "|---|---|---|---|---|---|---|---|"]
        for i, x in enumerate(top, 1):
            lines.append(f"| {i} | {x['code']} | {x['name']} | {x['score']:.0f} | {x['price']:,.0f} | "
                         f"{x['day_chg']:+.1f}% | {x['vol_ratio']:.1f}x | {x['rsi']:.0f} |")
    elif mode == "pullback":
        lines = ["| 順位 | コード | 銘柄 | スコア | 終値 | 前日比 | 60日騰落 | MA25乖離 |",
                 "|---|---|---|---|---|---|---|---|"]
        for i, x in enumerate(top, 1):
            lines.append(f"| {i} | {x['code']} | {x['name']} | {x['score']:.0f} | {x['price']:,.0f} | "
                         f"{x['day_chg']:+.1f}% | {x['trend60']:+.1f}% | {x['dev25']:+.1f}% |")
    elif mode == "squeeze":
        lines = ["| 順位 | コード | 銘柄 | スコア | BB幅比(60日最小比) | 終値 | 前日比 | RSI |",
                 "|---|---|---|---|---|---|---|---|"]
        for i, x in enumerate(top, 1):
            lines.append(f"| {i} | {x['code']} | {x['name']} | {x['score']:.0f} | {x['bbw_ratio']:.2f} | "
                         f"{x['price']:,.0f} | {x['day_chg']:+.1f}% | {x['rsi']:.0f} |")
    elif mode == "overheat":
        lines = ["| 順位 | コード | 銘柄 | スコア | RSI | MA25乖離 | 終値 | 前日比 |",
                 "|---|---|---|---|---|---|---|---|"]
        for i, x in enumerate(top, 1):
            lines.append(f"| {i} | {x['code']} | {x['name']} | {x['score']:.0f} | {x['rsi']:.0f} | "
                         f"{x['dev25']:+.1f}% | {x['price']:,.0f} | {x['day_chg']:+.1f}% |")
    else:
        lines = ["| 順位 | コード | 銘柄 | スコア | 終値 | 前日比 | 出来高比 | 3日 | RSI | 高値BRK |",
                 "|---|---|---|---|---|---|---|---|---|---|"]
        for i, x in enumerate(top, 1):
            lines.append(f"| {i} | {x['code']} | {x['name']} | {x['score']:.0f} | {x['price']:,.0f} | "
                         f"{x['day_chg']:+.1f}% | {x['vol_ratio']:.1f}x | {x['trend3']:+.1f}% | "
                         f"{x['rsi']:.0f} | {'○' if x['brk'] else '-'} |")
    return lines


def write_picks(mode, top, macro, last_date):
    os.makedirs(PICKS_DIR, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    path = os.path.join(PICKS_DIR, f"{today}-picks.md")
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    m = MODES[mode]

    lines = [f"\n## {m['emoji']} {m['title']} ({stamp} バッチ自動実行, データ最終日 {last_date})\n",
             f"マクロ: {macro}\n"]
    lines += table_lines(mode, top)
    lines.append("\n※テクニカル/指標のみ。材料（ニュース・IR）は未確認。\n")

    mode_w = "a" if os.path.exists(path) else "w"
    with open(path, mode_w, encoding="utf-8") as f:
        if mode_w == "w":
            f.write(f"# デイトレ提案 {today}（バッチ生成）\n")
        f.write("\n".join(lines))
    return path


def notify_discord(mode, top, macro):
    m = MODES[mode]
    body = [f"{m['emoji']} **{m['title']}** {datetime.now().strftime('%m/%d %H:%M')}", macro, ""]
    for i, x in enumerate(top, 1):
        if mode == "value":
            f = x["fund"]
            per = f"PER{f['per']:.1f}" if f.get("per") else "PER-"
            pbr = f"PBR{f['pbr']:.2f}" if f.get("pbr") else "PBR-"
            body.append(f"{i}. **{x['code']} {x['name']}** 利回り{f['yld']:.2f}% {per} {pbr} ({x['price']:,.0f}円)")
        elif mode == "bottom":
            body.append(f"{i}. **{x['code']} {x['name']}** score {x['score']:.0f} "
                        f"({x['price']:,.0f}円 {x['day_chg']:+.1f}% RSI{x['rsi']:.0f} 安値+{x['low90_gap']:.1f}%)")
        elif mode == "volsurge":
            body.append(f"{i}. **{x['code']} {x['name']}** 出来高{x['ratio']:.1f}x "
                        f"({x['price']:,.0f}円 {x['day_chg']:+.1f}%)")
        elif mode == "higherlow":
            body.append(f"{i}. **{x['code']} {x['name']}** {x['hl_streak']}日切上げ "
                        f"({x['price']:,.0f}円 {x['day_chg']:+.1f}% RSI{x['rsi']:.0f})")
        elif mode == "gap":
            arrow = "⬆GU" if x["gap"] > 0 else "⬇GD"
            body.append(f"{i}. **{x['code']} {x['name']}** {arrow}{x['gap']:+.1f}% "
                        f"寄り後{x['from_open']:+.1f}% ({x['price']:,.0f}円)")
        elif mode == "closestrong":
            body.append(f"{i}. **{x['code']} {x['name']}** score {x['score']:.0f} "
                        f"({x['price']:,.0f}円 {x['day_chg']:+.1f}% 出来高{x['vol_ratio']:.1f}x{' BRK' if x['brk'] else ''})")
        elif mode == "crash":
            body.append(f"{i}. **{x['code']} {x['name']}** {x['day_chg']:+.1f}% 出来高{x['vol_ratio']:.1f}x "
                        f"({x['price']:,.0f}円 RSI{x['rsi']:.0f})")
        elif mode == "pullback":
            body.append(f"{i}. **{x['code']} {x['name']}** 60日{x['trend60']:+.0f}% MA25反発 "
                        f"({x['price']:,.0f}円 {x['day_chg']:+.1f}%)")
        elif mode == "squeeze":
            body.append(f"{i}. **{x['code']} {x['name']}** BB幅比{x['bbw_ratio']:.2f} "
                        f"({x['price']:,.0f}円 {x['day_chg']:+.1f}% RSI{x['rsi']:.0f})")
        elif mode == "overheat":
            body.append(f"{i}. **{x['code']} {x['name']}** RSI{x['rsi']:.0f} 乖離{x['dev25']:+.1f}% "
                        f"({x['price']:,.0f}円 {x['day_chg']:+.1f}%)")
        else:
            body.append(f"{i}. **{x['code']} {x['name']}** score {x['score']:.0f} "
                        f"({x['price']:,.0f}円 {x['day_chg']:+.1f}% 出来高{x['vol_ratio']:.1f}x)")
    body.append("\n※テクニカル/指標のみ・材料未確認")
    content = "\n".join(body)
    if len(content) > 1990:  # Discordの2000文字制限
        content = content[:1980] + "\n(以下略)"
    r = requests.post(DISCORD_WEBHOOK_URL, json={"content": content}, timeout=30)
    r.raise_for_status()


def main():
    no_notify = "--no-notify" in sys.argv
    mode = "surge"
    if "--mode" in sys.argv:
        mode = sys.argv[sys.argv.index("--mode") + 1]
    if mode not in MODES:
        print(f"ERROR: 不明なモード: {mode} (surge|value|bottom)")
        sys.exit(1)

    # 土日は休場のため通知しない（週次レポートは土曜実行が前提なので除外）
    if mode != "report" and "--force" not in sys.argv and datetime.now().weekday() >= 5:
        print(f"[{mode}] 土日（休場）— 通知スキップ")
        return

    if mode in ("macro", "sector", "report", "digest"):
        lines = {"macro": macro_report, "sector": sector_report,
                 "report": weekly_report, "digest": digest_report}[mode]()
        m = MODES[mode]
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        os.makedirs(PICKS_DIR, exist_ok=True)
        path = os.path.join(PICKS_DIR, f"{datetime.now().strftime('%Y-%m-%d')}-picks.md")
        mode_w = "a" if os.path.exists(path) else "w"
        with open(path, mode_w, encoding="utf-8") as f:
            if mode_w == "w":
                f.write(f"# デイトレ提案 {datetime.now().strftime('%Y-%m-%d')}（バッチ生成）\n")
            f.write(f"\n## {m['emoji']} {m['title']} ({stamp} バッチ自動実行)\n\n" + "\n".join(lines) + "\n")
        print("\n".join(lines))
        if no_notify or mode in LOG_ONLY_MODES:
            print("(通知スキップ: --no-notify または log-onlyモード)")
        else:
            content = f"{m['emoji']} **{m['title']}** {datetime.now().strftime('%m/%d %H:%M')}\n" + "\n".join(lines)
            requests.post(DISCORD_WEBHOOK_URL, json={"content": content}, timeout=30).raise_for_status()
            print("Discord通知 送信済み")
        return

    tickers, names = nikkei225_universe()
    if mode == "volsurge":
        rows, last_date = screen_volsurge(tickers)
    else:
        rows, last_date = screen(tickers)
    if not rows:
        print("ERROR: 銘柄データを取得できませんでした")
        sys.exit(1)

    # 場中モード: 当日データがなければ休場とみなし通知しない
    if mode in INTRADAY_MODES and "--force" not in sys.argv:
        if last_date != datetime.now().date():
            print(f"[{mode}] 当日データなし (最終日 {last_date}) — 休場とみなし通知スキップ")
            return

    if mode == "value":
        funds = fetch_fundamentals([x["ticker"] for x in rows])
        for x in rows:
            x["fund"] = funds.get(x["ticker"], {})
            x["score"] = score_value(x, x["fund"])
    elif mode == "bottom":
        for x in rows:
            x["score"] = score_bottom(x)
    elif mode == "higherlow":
        for x in rows:
            x["score"] = score_higherlow(x)
    elif mode == "gap":
        for x in rows:
            x["score"] = score_gap(x)
    elif mode == "closestrong":
        for x in rows:
            x["score"] = score_closestrong(x)
    elif mode == "crash":
        for x in rows:
            x["score"] = score_crash(x)
    elif mode == "pullback":
        for x in rows:
            x["score"] = score_pullback(x)
    elif mode == "squeeze":
        for x in rows:
            x["score"] = score_squeeze(x)
    elif mode == "overheat":
        for x in rows:
            x["score"] = score_overheat(x)
    elif mode == "volsurge":
        pass  # score = 出来高倍率 (screen_volsurge で設定済み)
    else:
        for x in rows:
            x["score"] = score_surge(x)

    hits = [x for x in rows if x["score"] is not None]
    hits.sort(key=lambda x: x["score"], reverse=True)
    top = hits[:MODES[mode]["top"]]
    for x in top:
        x["name"] = names.get(x["ticker"], x["ticker"])

    if not top:
        print(f"[{mode}] 該当銘柄なし")
        if not no_notify and mode not in LOG_ONLY_MODES:
            m = MODES[mode]
            requests.post(DISCORD_WEBHOOK_URL, timeout=30,
                          json={"content": f"{m['emoji']} **{m['title']}** 本日は該当銘柄なし"}).raise_for_status()
        return

    macro = fetch_macro()
    path = write_picks(mode, top, macro, last_date)
    log_picks(mode, top)
    print(f"[{mode}] picks written: {path}")
    for i, x in enumerate(top, 1):
        print(f"{i}. {x['code']} {x['name']} score={x['score']:.0f}")

    if no_notify or mode in LOG_ONLY_MODES:
        print("(通知スキップ: --no-notify または log-onlyモード)")
    else:
        notify_discord(mode, top, macro)
        print("Discord通知 送信済み")


if __name__ == "__main__":
    main()
