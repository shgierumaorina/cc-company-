"""
FXアラート（MXNJPY / USDJPY 対応）

通知トリガー:
- 急落速報: ATR×倍率以上の下落を検出した時点で即時通知（RSI・クールダウン・BoJ退避を問わない。買い判断とは別の速報）
- 急落: ATR×倍率以上の下落 かつ RSI<閾値 → Discord通知（買い増し検討）
- 急騰: 基準価格からrise_threshold以上上昇 → Discord通知（利確検討）
- 絶対値: level_low以下 → Discord通知（サポートライン）
- BoJ退避: 政策決定会合前後3日は買いアラート停止（ルール9）

使い方:
  python fx_alert.py              # 全ペアを1回チェック
  python fx_alert.py --loop       # 全ペアを5分ごとに繰り返しチェック
  python fx_alert.py USDJPY       # USDJPYのみ1回チェック
  python fx_alert.py USDJPY --loop
"""

import json
import sys
import io
import time
from datetime import date, datetime
from pathlib import Path

import requests

from envutil import get_secret

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

LOG_FILE = Path(__file__).parent / "logs" / "fx_alert.log"
LOG_FILE.parent.mkdir(exist_ok=True)

def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    for _ in range(5):
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            break
        except PermissionError:
            time.sleep(0.5)


# --- グローバル設定 ---
DISCORD_WEBHOOK_URL = get_secret("DISCORD_WEBHOOK_URL")

RSI_PERIOD = 14
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

CHECK_INTERVAL = 60       # 1分
ACTIVE_HOUR_START = 7
ACTIVE_HOUR_END = 24
ALERT_COOLDOWN_MIN = 5
BASELINE_RESET_HOURS = 1
HOURLY_REPORT = True

BOJ_BLACKOUT_PERIODS = [
    (date(2026, 6, 12), date(2026, 6, 19)),
    (date(2026, 7, 27), date(2026, 8, 3)),
    (date(2026, 10, 26), date(2026, 11, 2)),
    (date(2026, 12, 14), date(2026, 12, 21)),
]


# --- 通貨ペア設定 ---
PAIR_CONFIGS = {
    "MXNJPY": {
        "ticker": "MXNJPY=X",
        "state_file": Path(__file__).parent / "fx_state.json",
        "rise_threshold": 0.01,    # 急騰判定（円）
        "level_low": 9.05,         # サポートライン（円）
        "atr_multiplier": 0.2,
        "atr_min": 0.01,
        "atr_max": 0.10,
        "rsi_buy_threshold": 50,
        "rsi_level_threshold": 45,
    },
    "USDJPY": {
        "ticker": "USDJPY=X",
        "state_file": Path(__file__).parent / "usdjpy_state.json",
        "rise_threshold": 0.50,    # 急騰判定（50銭以上）
        "level_low": 145.00,       # サポートライン（145円以下）
        "atr_multiplier": 0.2,
        "atr_min": 0.20,
        "atr_max": 2.00,
        "rsi_buy_threshold": 50,
        "rsi_level_threshold": 45,
    },
}


# ===== ユーティリティ =====

def is_boj_blackout() -> bool:
    today = date.today()
    return any(s <= today <= e for s, e in BOJ_BLACKOUT_PERIODS)


def is_active_hours() -> bool:
    now = datetime.now()
    end = 23 if ACTIVE_HOUR_END >= 24 else ACTIVE_HOUR_END
    return ACTIVE_HOUR_START <= now.hour <= end


def is_market_open() -> bool:
    """FX市場が開いているか（土日は休場）"""
    return datetime.now().weekday() < 5


DEFAULT_STATE = {"baseline": None, "last_checked": None, "low_alerted": False, "last_hourly": None, "last_alerted": None, "crash_alerted": False}


def load_state(state_file: Path) -> dict:
    if state_file.exists():
        try:
            return json.loads(state_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            log(f"⚠️ {state_file.name} が壊れていたためデフォルト状態にリセットします: {e}")
            return dict(DEFAULT_STATE)
    return dict(DEFAULT_STATE)


def save_state(state_file: Path, state: dict):
    tmp_file = state_file.with_suffix(state_file.suffix + ".tmp")
    tmp_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_file.replace(state_file)


def send_discord(message: str) -> bool:
    try:
        res = requests.post(DISCORD_WEBHOOK_URL, json={"content": message}, timeout=10)
        return res.status_code in (200, 204)
    except Exception as e:
        log(f"Discord送信エラー: {e}")
        return False


# ===== 価格・ローソク足取得 =====

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


# ===== テクニカル指標計算 =====

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
        macd, signal, hist = calc_macd(closes)
        atr  = calc_atr(highs, lows, closes)

        dynamic_drop = round(
            max(config["atr_min"], min(config["atr_max"], atr * config["atr_multiplier"])), 3
        )

        return {
            "current": candles["current"],
            "rsi": rsi,
            "macd": macd,
            "macd_signal": signal,
            "macd_hist": hist,
            "atr": atr,
            "dynamic_drop": dynamic_drop,
            "macd_bullish": macd > signal,
            "macd_rising": hist > 0,
            "error": None,
        }
    except Exception as e:
        return {"error": str(e)}


# ===== メインチェック =====

def check(pair_name: str, config: dict):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    state_file = config["state_file"]

    ind = get_indicators(config)
    if ind.get("error"):
        log(f"[{pair_name}] データ取得エラー: {ind['error']}")
        return

    current       = ind["current"]
    rsi           = ind["rsi"]
    macd_bullish  = ind["macd_bullish"]
    atr           = ind["atr"]
    dynamic_drop  = ind["dynamic_drop"]
    rise_threshold = config["rise_threshold"]
    level_low     = config["level_low"]
    rsi_buy_th    = config["rsi_buy_threshold"]

    log(
        f"[{pair_name}] 価格:{current:.4f}円 | "
        f"RSI:{rsi:.1f} | "
        f"MACD:{'強気↑' if macd_bullish else '弱気↓'} | "
        f"ATR:{atr:.4f} | "
        f"急落閾値:-{dynamic_drop:.3f}円"
    )

    state = load_state(state_file)

    if state["baseline"] is None:
        state["baseline"] = current
        state["last_checked"] = now_str
        state.setdefault("low_alerted", False)
        state.setdefault("crash_alerted", False)
        save_state(state_file, state)
        log(f"[{pair_name}] 基準価格を設定しました: {current:.4f}円")
        return

    baseline = state["baseline"]
    change   = current - baseline
    log(f"[{pair_name}] 基準価格:{baseline:.4f}円 / 変動:{change:+.4f}円")

    alerted  = False
    blackout = is_boj_blackout()

    last_alerted = state.get("last_alerted")
    in_cooldown = False
    if last_alerted:
        try:
            last_dt = datetime.strptime(last_alerted, "%Y-%m-%d %H:%M")
            mins_since = (datetime.now() - last_dt).total_seconds() / 60
            if mins_since < ALERT_COOLDOWN_MIN:
                in_cooldown = True
                log(f"[{pair_name}] ⏳ クールダウン中（残り{ALERT_COOLDOWN_MIN - mins_since:.0f}分）")
        except ValueError:
            pass

    if blackout:
        log(f"[{pair_name}] 🔕 BoJ退避期間中 → 買いアラート停止中")

    # ルール1: 急落チェック
    drop_triggered = change <= -dynamic_drop
    rsi_ok = rsi < rsi_buy_th

    # ルール0: 急落速報（RSI条件・クールダウンを問わず、閾値超え検出時に即時通知。買い判断とは別扱い）
    crash_alerted = state.get("crash_alerted", False)
    if drop_triggered and not crash_alerted:
        crash_message = (
            f"🚨 {pair_name} 価格急落検出（速報）\n\n"
            f"現在価格: {current:.4f}円\n"
            f"変動: {change:+.4f}円（閾値: -{dynamic_drop:.3f}円）\n"
            f"RSI: {rsi:.1f}\n\n"
            f"※これは速報です。買いシグナルはRSI条件を満たした場合に別途通知されます。\n"
            f"時刻: {now_str}"
        )
        if send_discord(crash_message):
            log(f"[{pair_name}] 🚨 急落速報をDiscordに送信しました")
            state["crash_alerted"] = True
        else:
            log(f"[{pair_name}] ❌ 急落速報のDiscord送信失敗")
    elif not drop_triggered and crash_alerted:
        state["crash_alerted"] = False

    if drop_triggered and not in_cooldown:
        if blackout:
            log(f"[{pair_name}] ⏸️  急落検出(-{dynamic_drop:.3f}円超) → BoJ退避期間中のため買い停止")
            alerted = True
        elif not rsi_ok:
            log(f"[{pair_name}] ⚠️  急落検出したがRSIフィルター未達のため見送り (RSI:{rsi:.1f}/{rsi_buy_th})")
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
            if send_discord(message):
                log(f"[{pair_name}] ✅ 買いシグナルをDiscordに送信しました")
            else:
                log(f"[{pair_name}] ❌ Discord送信失敗")
            alerted = True
    elif drop_triggered and in_cooldown:
        log(f"[{pair_name}] ⚠️  急落検出 → クールダウン中のためスキップ（変動:{change:+.4f}円）")

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
        if send_discord(message):
            log(f"[{pair_name}] ✅ 上昇アラートをDiscordに送信しました")
        else:
            log(f"[{pair_name}] ❌ Discord送信失敗")
        alerted = True
    elif not drop_triggered and change >= rise_threshold and in_cooldown:
        log(f"[{pair_name}] 🚀 上昇検出 → クールダウン中のためスキップ（変動:{change:+.4f}円）")

    # ルール3: サポートラインアラート
    low_alerted = state.get("low_alerted", False)
    if current <= level_low and not low_alerted:
        if blackout:
            log(f"[{pair_name}] ⏸️  {level_low}円以下 → BoJ退避期間中のため買い停止")
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
            if send_discord(message):
                log(f"[{pair_name}] ✅ サポートラインアラートをDiscordに送信しました")
                state["low_alerted"] = True
            else:
                log(f"[{pair_name}] ❌ Discord送信失敗")
    elif current > level_low and low_alerted:
        state["low_alerted"] = False

    if alerted:
        state["baseline"] = current
        state["last_alerted"] = now_str
        log(f"[{pair_name}] 基準価格をリセット: {current:.4f}円")
    else:
        last_ts = state.get("last_alerted") or state.get("last_checked") or now_str
        try:
            last_dt = datetime.strptime(last_ts, "%Y-%m-%d %H:%M")
            hours_since = (datetime.now() - last_dt).total_seconds() / 3600
            if hours_since >= BASELINE_RESET_HOURS:
                state["baseline"] = current
                state["last_alerted"] = now_str
                log(f"[{pair_name}] ⏱️ {BASELINE_RESET_HOURS}時間アラートなし → baseline自動リセット: {current:.4f}円")
        except ValueError:
            pass

    # 定期レポート（1時間ごと）
    if HOURLY_REPORT:
        current_hour = datetime.now().strftime("%Y-%m-%d %H")
        if state.get("last_hourly") != current_hour:
            report = (
                f"🕐 {pair_name} 定期レポート {now_str}\n\n"
                f"現在価格: {current:.4f}円\n"
                f"RSI: {ind['rsi']:.1f}\n"
                f"MACD: {'強気↑' if ind['macd_bullish'] else '弱気↓'}\n"
                f"ATR: {ind['atr']:.4f}円\n"
                f"基準価格: {state['baseline']:.4f}円\n"
                f"変動: {change:+.4f}円"
            )
            if send_discord(report):
                state["last_hourly"] = current_hour
                log(f"[{pair_name}] ✅ 定期レポートをDiscordに送信しました")
            else:
                log(f"[{pair_name}] ❌ 定期レポートのDiscord送信失敗")

    state["last_checked"] = now_str
    save_state(state_file, state)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    loop = "--loop" in sys.argv

    # 引数でペア名指定があればそのペアだけ、なければ全ペア
    if args and args[0].upper() in PAIR_CONFIGS:
        target_pairs = [args[0].upper()]
    else:
        target_pairs = list(PAIR_CONFIGS.keys())

    if loop:
        log(f"ループ監視開始（{CHECK_INTERVAL}秒間隔）対象: {', '.join(target_pairs)}")
        while True:
            if not is_market_open():
                log("🔕 FX休場（土日）→ チェックスキップ")
                time.sleep(CHECK_INTERVAL)
                continue
            for pair_name in target_pairs:
                try:
                    check(pair_name, PAIR_CONFIGS[pair_name])
                except Exception as e:
                    log(f"[{pair_name}] エラー: {e}")
            time.sleep(CHECK_INTERVAL)
    else:
        if not is_market_open():
            log("🔕 FX休場（土日）→ チェックスキップ")
            return
        for pair_name in target_pairs:
            try:
                check(pair_name, PAIR_CONFIGS[pair_name])
            except Exception as e:
                log(f"[{pair_name}] エラー: {e}")


if __name__ == "__main__":
    main()
