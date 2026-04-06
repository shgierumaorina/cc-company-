"""
国内株スクリーナー - GitHub Actions用（AI不使用）
データソース: stooq.com（無料・APIキー不要）
環境変数: LINE_NOTIFY_TOKEN
"""
import urllib.request, csv, io, urllib.parse, json, os
from datetime import datetime, timedelta

DISCORD_URL = os.environ["DISCORD_WEBHOOK_URL"]

WATCHLIST = [
    {"code": "7011.jp", "name": "三菱重工", "theme": "防衛"},
    {"code": "7012.jp", "name": "川崎重工", "theme": "防衛"},
    {"code": "7013.jp", "name": "IHI",     "theme": "防衛"},
    {"code": "1605.jp", "name": "INPEX",   "theme": "エネルギー"},
]

def fetch_stooq(symbol, days=20):
    end = datetime.now()
    start = end - timedelta(days=days)
    url = (f"https://stooq.com/q/d/l/?s={urllib.parse.quote(symbol)}"
           f"&d1={start.strftime('%Y%m%d')}&d2={end.strftime('%Y%m%d')}&i=d")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        rows = list(csv.DictReader(io.StringIO(r.read().decode())))
    return rows[-10:] if len(rows) >= 10 else rows

def calc_score(rows):
    if len(rows) < 3:
        return 0, 0, 0
    closes  = [float(r["Close"])  for r in rows if r.get("Close")  and r["Close"]  != "N/D"]
    volumes = [float(r["Volume"]) for r in rows if r.get("Volume") and r["Volume"] != "N/D"]
    if len(closes) < 3 or len(volumes) < 2:
        return 0, 0, 0
    day_chg   = (closes[-1] - closes[-2]) / closes[-2] * 100
    avg_vol   = sum(volumes[:-1]) / len(volumes[:-1]) or 1
    vol_ratio = volumes[-1] / avg_vol
    trend     = (closes[-1] - closes[-3]) / closes[-3] * 100
    s = 0
    if vol_ratio >= 2.0: s += 40
    elif vol_ratio >= 1.5: s += 25
    if trend > 3:        s += 30
    elif trend > 1:      s += 15
    if day_chg > 2:      s += 20
    elif day_chg > 0.5:  s += 10
    return s, day_chg, vol_ratio

# スクリーニング
results = []
for s in WATCHLIST:
    try:
        rows = fetch_stooq(s["code"])
        sc, day_chg, vol_ratio = calc_score(rows)
        price = float(rows[-1]["Close"]) if rows else 0
        results.append({**s, "price": price, "day_chg": day_chg, "vol_ratio": vol_ratio, "score": sc})
        print(f"  {s['name']}: スコア{sc} 出来高{vol_ratio:.1f}倍 {day_chg:+.1f}%")
    except Exception as e:
        print(f"  {s['name']}: エラー {e}")

results.sort(key=lambda x: x["score"], reverse=True)
top = results[:5]

# 指数取得
nikkei = usdjpy = 0
try:
    rows = fetch_stooq("^nkx")
    nikkei = float(rows[-1]["Close"]) if rows else 0
except Exception as e:
    print(f"日経取得エラー: {e}")
try:
    rows = fetch_stooq("usdjpy")
    usdjpy = float(rows[-1]["Close"]) if rows else 0
except Exception as e:
    print(f"ドル円取得エラー: {e}")

date_str = datetime.now().strftime("%Y-%m-%d")
lines = [
    f"📈デイトレ候補 {date_str}",
    f"日経:{nikkei:,.0f} ドル円:{usdjpy:.2f}",
]
for i, s in enumerate(top, 1):
    code = s["code"].replace(".jp", "")
    lines.append(f"{i}位 {s['name']}({code}) スコア{s['score']} 出来高{s['vol_ratio']:.1f}倍 {s['day_chg']:+.1f}%")

msg = "\n".join(lines)
print("\n" + msg)

# 全スコア0＝データなし（休場日）はスキップ
if all(s["score"] == 0 for s in top):
    print("市場データなし（休場日の可能性）- Discord送信スキップ")
else:
    data = json.dumps({"content": msg}).encode()
    req = urllib.request.Request(DISCORD_URL, data=data, headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req)
    print("Discord送信完了")
