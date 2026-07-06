"""
MXNJPY ポジション管理 Webアプリ

- ブラウザからポジションを追加・削除
- バックグラウンドで1分ごとに価格監視
- 含み損・損切りアラートをDiscordに送信
"""

import os
import sys
import threading
import time
import uuid
from datetime import date, datetime, timedelta

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, url_for

load_dotenv()

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

app = Flask(__name__)

JST_OFFSET = timedelta(hours=9)


def now_jst() -> datetime:
    """Renderのコンテナ時計はUTCのため、JSTの壁時計時刻を返す（tzinfoなし）"""
    return datetime.utcnow() + JST_OFFSET

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
TICKER = "MXNJPY=X"
HOLD_PRICE_DROP = 0.01        # 放置ポジション エントリーから0.01下落でアラート
INCOME_STOP_LOSS = -500       # 利益取りポジション 損切りアラート（円）

ACTIVE_HOUR_START = 8   # 通知開始時刻（JST）
ACTIVE_HOUR_END   = 24  # 通知終了時刻（JST）


def is_market_open() -> bool:
    """FX市場が開いているか（平日8:00〜24:00 JSTのみ通知）"""
    now = now_jst()
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
    "last_checked_ts": None,
}


# --- ユーティリティ ---

def get_price() -> float:
    url = "https://query2.finance.yahoo.com/v8/finance/chart/MXNJPY=X?interval=1m&range=1d"
    headers = {"User-Agent": "Mozilla/5.0"}
    for attempt in range(3):
        try:
            res = requests.get(url, headers=headers, timeout=15)
            res.raise_for_status()
            return float(res.json()["chart"]["result"][0]["meta"]["regularMarketPrice"])
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
            now_str = now_jst().strftime("%Y-%m-%d %H:%M")

            with state_lock:
                state["current_price"] = price
                state["last_checked"] = now_str
                state["last_checked_ts"] = time.time()

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


# --- 自動シグナル監視（fx_alert.py 移植: RSI/MACD/ATRベースの急落・急騰・サポートライン判定） ---

RSI_PERIOD = 14
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

SIGNAL_CHECK_INTERVAL = 60   # 1分
ALERT_COOLDOWN_MIN = 5
BASELINE_RESET_HOURS = 1
HOURLY_REPORT = True

BOJ_BLACKOUT_PERIODS = [
    (date(2026, 6, 12), date(2026, 6, 19)),
    (date(2026, 7, 27), date(2026, 8, 3)),
    (date(2026, 10, 26), date(2026, 11, 2)),
    (date(2026, 12, 14), date(2026, 12, 21)),
]

SIGNAL_PAIR_CONFIGS = {
    "MXNJPY": {
        "ticker": "MXNJPY=X",
        "rise_threshold": 0.01,
        "level_low": 9.05,
        "atr_multiplier": 0.2,
        "atr_min": 0.01,
        "atr_max": 0.10,
        "rsi_buy_threshold": 50,
    },
    "USDJPY": {
        "ticker": "USDJPY=X",
        "rise_threshold": 0.50,
        "level_low": 145.00,
        "atr_multiplier": 0.2,
        "atr_min": 0.20,
        "atr_max": 2.00,
        "rsi_buy_threshold": 50,
    },
}

signal_lock = threading.Lock()
signal_state = {
    name: {"baseline": None, "last_checked": None, "low_alerted": False, "last_hourly": None, "last_alerted": None}
    for name in SIGNAL_PAIR_CONFIGS
}


def is_boj_blackout() -> bool:
    today = now_jst().date()
    return any(s <= today <= e for s, e in BOJ_BLACKOUT_PERIODS)


def get_candles(ticker: str) -> dict:
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1h&range=10d"
    headers = {"User-Agent": "Mozilla/5.0"}
    res = requests.get(url, headers=headers, timeout=10)
    res.raise_for_status()
    data = res.json()["chart"]["result"][0]

    quotes = data["indicators"]["quote"][0]
    ohlc = [
        (h, l, c)
        for h, l, c in zip(quotes["high"], quotes["low"], quotes["close"])
        if h is not None and l is not None and c is not None
    ]
    if len(ohlc) < 2:
        raise ValueError("ローソク足データが不足しています")

    highs  = [h for h, _, _ in ohlc]
    lows   = [l for _, l, _ in ohlc]
    closes = [c for _, _, c in ohlc]

    current_price = float(data["meta"]["regularMarketPrice"])
    return {"current": current_price, "closes": closes, "highs": highs, "lows": lows}


def calc_ema(data: list, period: int) -> list:
    k = 2 / (period + 1)
    ema = [data[0]]
    for price in data[1:]:
        ema.append(price * k + ema[-1] * (1 - k))
    return ema


def calc_rsi(closes: list, period: int = RSI_PERIOD) -> float:
    if len(closes) < period + 1:
        return 50.0
    diffs = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains  = [max(d, 0) for d in diffs]
    losses = [max(-d, 0) for d in diffs]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(diffs)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def calc_macd(closes: list) -> tuple:
    if len(closes) < MACD_SLOW + MACD_SIGNAL:
        return 0.0, 0.0, 0.0
    ema_fast  = calc_ema(closes, MACD_FAST)
    ema_slow  = calc_ema(closes, MACD_SLOW)
    macd_line = [ema_fast[i] - ema_slow[i] for i in range(len(ema_slow))]
    signal_line = calc_ema(macd_line, MACD_SIGNAL)
    histogram   = [macd_line[i] - signal_line[i] for i in range(len(signal_line))]
    return round(macd_line[-1], 6), round(signal_line[-1], 6), round(histogram[-1], 6)


def calc_atr(highs: list, lows: list, closes: list, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 0.3
    trs = []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        trs.append(tr)
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return round(atr, 5)


def get_indicators(config: dict) -> dict:
    try:
        candles = get_candles(config["ticker"])
        closes  = candles["closes"]
        highs   = candles["highs"]
        lows    = candles["lows"]

        rsi  = calc_rsi(closes)
        macd, macd_signal, hist = calc_macd(closes)
        atr  = calc_atr(highs, lows, closes)

        dynamic_drop = round(
            max(config["atr_min"], min(config["atr_max"], atr * config["atr_multiplier"])), 3
        )

        return {
            "current": candles["current"],
            "rsi": rsi,
            "atr": atr,
            "dynamic_drop": dynamic_drop,
            "macd_bullish": macd > macd_signal,
            "error": None,
        }
    except Exception as e:
        return {"error": str(e)}


def check_signal(pair_name: str, config: dict):
    now_str = now_jst().strftime("%Y-%m-%d %H:%M")

    ind = get_indicators(config)
    if ind.get("error"):
        print(f"[Signal][{pair_name}] データ取得エラー: {ind['error']}")
        return

    current       = ind["current"]
    rsi           = ind["rsi"]
    macd_bullish  = ind["macd_bullish"]
    atr           = ind["atr"]
    dynamic_drop  = ind["dynamic_drop"]
    rise_threshold = config["rise_threshold"]
    level_low     = config["level_low"]
    rsi_buy_th    = config["rsi_buy_threshold"]

    print(
        f"[Signal][{pair_name}] 価格:{current:.4f}円 | RSI:{rsi:.1f} | "
        f"MACD:{'強気↑' if macd_bullish else '弱気↓'} | ATR:{atr:.4f} | 急落閾値:-{dynamic_drop:.3f}円"
    )

    with signal_lock:
        state = signal_state[pair_name]

        if state["baseline"] is None:
            state["baseline"] = current
            state["last_checked"] = now_str
            print(f"[Signal][{pair_name}] 基準価格を設定しました: {current:.4f}円")
            return

        baseline = state["baseline"]
        change   = current - baseline
        blackout = is_boj_blackout()
        alerted  = False

        last_alerted = state.get("last_alerted")
        in_cooldown = False
        if last_alerted:
            try:
                mins_since = (now_jst() - datetime.strptime(last_alerted, "%Y-%m-%d %H:%M")).total_seconds() / 60
                in_cooldown = mins_since < ALERT_COOLDOWN_MIN
            except ValueError:
                pass

        # ルール1: 急落チェック
        drop_triggered = change <= -dynamic_drop
        rsi_ok = rsi < rsi_buy_th

        if drop_triggered and not in_cooldown:
            if blackout:
                print(f"[Signal][{pair_name}] ⏸️ 急落検出 → BoJ退避期間中のため買い停止")
                alerted = True
            elif not rsi_ok:
                print(f"[Signal][{pair_name}] ⚠️ 急落検出したがRSIフィルター未達のため見送り (RSI:{rsi:.1f}/{rsi_buy_th})")
            else:
                message = (
                    f"⚠️ {pair_name} 買いシグナル！\n\n"
                    f"現在価格: {current:.4f}円\n"
                    f"変動: {change:+.4f}円（閾値: -{dynamic_drop:.3f}円）\n\n"
                    f"📊 テクニカル確認\n"
                    f"  RSI: {rsi:.1f}\n"
                    f"  MACD: {'強気↑' if macd_bullish else '弱気↓'}\n"
                    f"  ATR: {atr:.4f}円\n\n"
                    f"📌 急落検出 → 買い増し検討\n"
                    f"時刻: {now_str}"
                )
                send_discord(message)
                alerted = True

        # ルール2: 急騰チェック
        if not drop_triggered and change >= rise_threshold and not in_cooldown:
            message = (
                f"🚀 {pair_name} 上昇アラート！\n\n"
                f"現在価格: {current:.4f}円\n"
                f"変動: {change:+.4f}円\n"
                f"RSI: {rsi:.1f}\n\n"
                f"📌 利確を検討してください\n"
                f"時刻: {now_str}"
            )
            send_discord(message)
            alerted = True

        # ルール3: サポートラインアラート
        low_alerted = state.get("low_alerted", False)
        if current <= level_low and not low_alerted:
            if blackout:
                print(f"[Signal][{pair_name}] ⏸️ {level_low}円以下 → BoJ退避期間中のため買い停止")
                state["low_alerted"] = True
            else:
                message = (
                    f"🔔 {pair_name} サポートライン到達！\n\n"
                    f"現在価格: {current:.4f}円（閾値: {level_low}円以下）\n\n"
                    f"📊 テクニカル確認\n"
                    f"  RSI: {rsi:.1f}\n"
                    f"  MACD: {'強気↑' if macd_bullish else '弱気↓'}\n\n"
                    f"📌 段階的買い増し候補\n"
                    f"時刻: {now_str}"
                )
                send_discord(message)
                state["low_alerted"] = True
        elif current > level_low and low_alerted:
            state["low_alerted"] = False

        if alerted:
            state["baseline"] = current
            state["last_alerted"] = now_str
        else:
            last_ts = state.get("last_alerted") or state.get("last_checked") or now_str
            try:
                hours_since = (now_jst() - datetime.strptime(last_ts, "%Y-%m-%d %H:%M")).total_seconds() / 3600
                if hours_since >= BASELINE_RESET_HOURS:
                    state["baseline"] = current
                    state["last_alerted"] = now_str
            except ValueError:
                pass

        # 定期レポート（1時間ごと）
        if HOURLY_REPORT:
            current_hour = now_jst().strftime("%Y-%m-%d %H")
            if state.get("last_hourly") != current_hour:
                report = (
                    f"🕐 {pair_name} 定期レポート {now_str}\n\n"
                    f"現在価格: {current:.4f}円\n"
                    f"RSI: {rsi:.1f}\n"
                    f"MACD: {'強気↑' if macd_bullish else '弱気↓'}\n"
                    f"ATR: {atr:.4f}円\n"
                    f"基準価格: {state['baseline']:.4f}円\n"
                    f"変動: {change:+.4f}円"
                )
                if send_discord(report):
                    state["last_hourly"] = current_hour

        state["last_checked"] = now_str


def signal_monitor_loop():
    print("[Signal] シグナル監視スレッド開始")
    while True:
        for pair_name, config in SIGNAL_PAIR_CONFIGS.items():
            try:
                check_signal(pair_name, config)
            except Exception as e:
                print(f"[Signal][{pair_name}] エラー: {e}")
        time.sleep(SIGNAL_CHECK_INTERVAL)


# --- ルート ---

@app.route("/")
def index():
    with state_lock:
        price = state["current_price"]
        last_checked = state["last_checked"]
        last_checked_ts = state["last_checked_ts"]

    stale = last_checked_ts is None or (time.time() - last_checked_ts > 60)
    if price is None or stale:
        try:
            price = get_price()
            last_checked = now_jst().strftime("%Y-%m-%d %H:%M")
            with state_lock:
                state["current_price"] = price
                state["last_checked"] = last_checked
                state["last_checked_ts"] = time.time()
        except Exception as e:
            print(f"[Index] 価格取得失敗: {e}")

    with state_lock:
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
            "created_at": now_jst().strftime("%m/%d %H:%M"),
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
            "created_at": now_jst().strftime("%m/%d %H:%M"),
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


@app.route("/debug/fetch")
def debug_fetch():
    result = {}
    try:
        p = get_price()
        result["get_price"] = {"ok": True, "value": p}
    except Exception as e:
        result["get_price"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    try:
        c = get_candles("MXNJPY=X")
        result["get_candles"] = {"ok": True, "current": c["current"], "n_closes": len(c["closes"])}
    except Exception as e:
        result["get_candles"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    return jsonify(result)


# --- 起動 ---

monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
monitor_thread.start()

signal_thread = threading.Thread(target=signal_monitor_loop, daemon=True)
signal_thread.start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
