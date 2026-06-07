"""
MXNJPY ポジション管理 Webアプリ

- ブラウザからポジションを追加・削除
- バックグラウンドで1分ごとに価格監視
- 含み損・損切りアラートをDiscordに送信
"""

import os
import threading
import time
import uuid
from datetime import datetime

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, url_for

load_dotenv()

app = Flask(__name__)

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
TICKER = "MXNJPY=X"
HOLD_PRICE_DROP = 0.01        # 放置ポジション エントリーから0.01下落でアラート
INCOME_STOP_LOSS = -500       # 利益取りポジション 損切りアラート（円）

ACTIVE_HOUR_START = 8   # 通知開始時刻（JST）
ACTIVE_HOUR_END   = 24  # 通知終了時刻（JST）


def is_market_open() -> bool:
    """FX市場が開いているか（平日8:00〜24:00 JSTのみ通知）"""
    now = datetime.now()
    if now.weekday() >= 5:  # 土日はスキップ
        return False
    end_hour = 23 if ACTIVE_HOUR_END >= 24 else ACTIVE_HOUR_END
    return ACTIVE_HOUR_START <= now.hour <= end_hour

# --- スレッドセーフな状態管理 ---
state_lock = threading.Lock()
state = {
    "hold_positions": [],      # [{id, entry_price, units, alerted, created_at}]
    "income_positions": [],    # [{id, entry_price, units, alerted, created_at}]
    "current_price": None,
    "last_checked": None,
}


# --- ユーティリティ ---

def get_price() -> float:
    # stooq.com: MXNJPY=X → mxnjpy (クラウドIPでも安定して取得可能)
    url = "https://stooq.com/q/l/?s=mxnjpy&f=sd2t2ohlcv&h&e=csv"
    headers = {"User-Agent": "Mozilla/5.0"}
    for attempt in range(3):
        try:
            res = requests.get(url, headers=headers, timeout=15)
            res.raise_for_status()
            lines = res.text.strip().splitlines()
            if len(lines) >= 2:
                close = lines[1].split(",")[6]
                if close and close != "N/D":
                    return float(close)
        except Exception:
            pass
        if attempt < 2:
            time.sleep(3)
    raise RuntimeError("価格取得失敗")


def send_discord(message: str) -> bool:
    if not DISCORD_WEBHOOK_URL:
        print("[WARN] DISCORD_WEBHOOK_URL が未設定です")
        return False
    try:
        res = requests.post(DISCORD_WEBHOOK_URL, json={"content": message}, timeout=10)
        return res.status_code in (200, 204)
    except Exception as e:
        print(f"[ERROR] Discord送信失敗: {e}")
        return False


def calc_pnl(positions: list, current_price: float) -> float:
    return sum((current_price - p["entry_price"]) * p["units"] for p in positions)


# --- 監視ループ（バックグラウンドスレッド） ---

def monitor_loop():
    print("[Monitor] 監視スレッド開始")
    while True:
        try:
            price = get_price()
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

            with state_lock:
                state["current_price"] = price
                state["last_checked"] = now_str

            if not is_market_open():
                print(f"[Monitor] 市場時間外のため通知スキップ ({now_str})")
                time.sleep(60)
                continue

            with state_lock:
                # 放置ポジション エントリーから0.01下落チェック
                for pos in state["hold_positions"]:
                    drop = pos["entry_price"] - price
                    if drop >= HOLD_PRICE_DROP and not pos.get("alerted", False):
                        pnl = (price - pos["entry_price"]) * pos["units"]
                        msg = (
                            f"⚠️ MXNJPY 放置ポジション アラート\n"
                            f"エントリー: {pos['entry_price']:.4f}円\n"
                            f"現在価格: {price:.4f}円\n"
                            f"下落幅: -{drop:.4f}円\n"
                            f"含み損益: {pnl:+.0f}円\n"
                            f"時刻: {now_str}"
                        )
                        send_discord(msg)
                        pos["alerted"] = True
                    elif drop < HOLD_PRICE_DROP * 0.5:
                        pos["alerted"] = False

                # 利益取りポジション 損切りチェック
                for pos in state["income_positions"]:
                    pos_pnl = (price - pos["entry_price"]) * pos["units"]
                    if pos_pnl <= INCOME_STOP_LOSS and not pos.get("alerted", False):
                        msg = (
                            f"🛑 MXNJPY 損切りアラート\n"
                            f"含み損: {pos_pnl:+.0f}円\n"
                            f"エントリー: {pos['entry_price']:.4f}円\n"
                            f"現在価格: {price:.4f}円\n"
                            f"ロット: {pos['units']:,}通貨\n"
                            f"時刻: {now_str}\n"
                            f"⛔ 今すぐ損切りしてください！"
                        )
                        send_discord(msg)
                        pos["alerted"] = True
                    elif pos_pnl > INCOME_STOP_LOSS * 0.5:
                        pos["alerted"] = False

        except Exception as e:
            print(f"[Monitor] エラー: {e}")

        time.sleep(60)


# --- ルート ---

@app.route("/")
def index():
    with state_lock:
        price = state["current_price"]
        last_checked = state["last_checked"]
        hold = [
            {**p, "pnl": round((price - p["entry_price"]) * p["units"]) if price else None}
            for p in state["hold_positions"]
        ]
        income = [
            {**p, "pnl": round((price - p["entry_price"]) * p["units"]) if price else None}
            for p in state["income_positions"]
        ]
        hold_total_pnl = round(calc_pnl(state["hold_positions"], price)) if price and state["hold_positions"] else None
        income_total_pnl = round(calc_pnl(state["income_positions"], price)) if price and state["income_positions"] else None

    return render_template(
        "index.html",
        price=price,
        last_checked=last_checked,
        hold_positions=hold,
        income_positions=income,
        hold_total_pnl=hold_total_pnl,
        income_total_pnl=income_total_pnl,
    )


@app.route("/add-hold", methods=["POST"])
def add_hold():
    entry_price = float(request.form["entry_price"])
    lots = float(request.form["units"])
    with state_lock:
        state["hold_positions"].append({
            "id": str(uuid.uuid4())[:8],
            "entry_price": entry_price,
            "units": int(lots * 10000),
            "lots": lots,
            "alerted": False,
            "created_at": datetime.now().strftime("%m/%d %H:%M"),
        })
    return redirect(url_for("index"))


@app.route("/add-income", methods=["POST"])
def add_income():
    entry_price = float(request.form["entry_price"])
    lots = float(request.form["units"])
    with state_lock:
        state["income_positions"].append({
            "id": str(uuid.uuid4())[:8],
            "entry_price": entry_price,
            "units": int(lots * 10000),
            "lots": lots,
            "alerted": False,
            "created_at": datetime.now().strftime("%m/%d %H:%M"),
        })
    return redirect(url_for("index"))


@app.route("/close/<pos_type>/<pos_id>", methods=["POST"])
def close_position(pos_type, pos_id):
    with state_lock:
        key = "hold_positions" if pos_type == "hold" else "income_positions"
        state[key] = [p for p in state[key] if p["id"] != pos_id]
    return redirect(url_for("index"))


@app.route("/api/status")
def api_status():
    with state_lock:
        price = state["current_price"]
        return jsonify({
            "price": price,
            "last_checked": state["last_checked"],
            "hold_count": len(state["hold_positions"]),
            "income_count": len(state["income_positions"]),
        })


@app.route("/health")
def health():
    return "OK", 200


# --- 起動 ---

monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
monitor_thread.start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
