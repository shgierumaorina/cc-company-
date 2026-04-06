"""
MXNJPY監視 - GitHub Actions用（AI不使用）
環境変数: DISCORD_WEBHOOK_URL
状態ファイル: state/fx-prev.txt（リポジトリに保存）
"""
import urllib.request, json, os
from datetime import datetime

DISCORD_URL = os.environ["DISCORD_WEBHOOK_URL"]
STATE_FILE = os.path.join(os.path.dirname(__file__), "../state/fx-prev.txt")

# レート取得
with urllib.request.urlopen("https://open.er-api.com/v6/latest/MXN", timeout=10) as r:
    rate = json.loads(r.read())["rates"]["JPY"]

# 前回価格読み込み
try:
    prev = float(open(STATE_FILE).read().strip())
except:
    prev = None

# 状態保存
open(STATE_FILE, "w").write(str(rate))

diff = rate - prev if prev else 0
jst = datetime.now().strftime("%Y-%m-%d %H:%M JST")
print(f"MXNJPY: {rate:.4f} | 前回: {f'{prev:.4f}' if prev else '-'} | 変動: {diff:+.4f}")

# アラート判定
alert = ""
if prev and diff <= -0.3:
    alert = f"🔴SELL {rate:.4f}円 (前回{prev:.4f} {diff:.4f})"
elif prev and diff >= 0.5:
    alert = f"🟢BUY利確 {rate:.4f}円 (前回{prev:.4f} +{diff:.4f})"
elif rate <= 8.65:
    alert = f"🟡BUY候補 {rate:.4f}円 (サポートライン以下)"

if alert:
    msg = f"🔔MXNJPY {alert} {jst}"
    data = json.dumps({"content": msg}).encode()
    req = urllib.request.Request(DISCORD_URL, data=data, headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req)
    print(f"Discord送信: {alert}")
else:
    print("アラートなし")
