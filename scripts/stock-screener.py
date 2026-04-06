"""
国内株スクリーナー - GitHub Actions用（AI不使用）
環境変数: LINE_NOTIFY_TOKEN
データソース: Yahoo Finance API（無料・APIキー不要）
"""
import urllib.request, json, urllib.parse, os
from datetime import datetime

LINE_TOKEN = os.environ["LINE_NOTIFY_TOKEN"]

# ウォッチリスト（銘柄追加・削除はここを編集）
WATCHLIST = [
    {"code": "7011.T", "name": "三菱重工", "theme": "防衛"},
    {"code": "7012.T", "name": "川崎重工", "theme": "防衛"},
    {"code": "7013.T", "name": "IHI",     "theme": "防衛"},
    {"code": "1605.T", "name": "INPEX",   "theme": "エネルギー"},
]

def fetch(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?interval=1d&range=10d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read())
    q = data["chart"]["result"][0]["indicators"]["quote"][0]
    closes  = [x for x in q["close"]  if x is not None]
    volumes = [x for x in q["volume"] if x is not None]
    return closes, volumes

def calc_score(closes, volumes):
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
        closes, volumes = fetch(s["code"])
        sc, day_chg, vol_ratio = calc_score(closes, volumes)
        results.append({**s, "price": closes[-1], "day_chg": day_chg, "vol_ratio": vol_ratio, "score": sc})
        print(f"  {s['name']}: スコア{sc} 出来高{vol_ratio:.1f}倍 {day_chg:+.1f}%")
    except Exception as e:
        print(f"  {s['name']}: エラー {e}")

results.sort(key=lambda x: x["score"], reverse=True)
top = results[:5]

# 指数取得
try:
    nikkei = fetch("^N225")[0][-1]
    usdjpy = fetch("JPY=X")[0][-1]
except:
    nikkei = usdjpy = 0

date_str = datetime.now().strftime("%Y-%m-%d")
lines = [
    f"📈デイトレ候補 {date_str}",
    f"日経:{nikkei:,.0f} ドル円:{usdjpy:.2f}",
]
for i, s in enumerate(top, 1):
    code = s["code"].replace(".T", "")
    lines.append(f"{i}位 {s['name']}({code}) スコア{s['score']} 出来高{s['vol_ratio']:.1f}倍 {s['day_chg']:+.1f}%")

msg = "\n".join(lines)
print("\n" + msg)

data = urllib.parse.urlencode({"message": msg}).encode()
req = urllib.request.Request(
    "https://notify-api.line.me/api/notify", data=data,
    headers={"Authorization": f"Bearer {LINE_TOKEN}"}
)
urllib.request.urlopen(req)
print("LINE送信完了")
