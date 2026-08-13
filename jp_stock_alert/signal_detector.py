"""安値圏×出来高急増の判定ロジック
単体テスト実行: python signal_detector.py 7203
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from envutil import get_secret
sys.path.insert(0, str(Path(__file__).resolve().parent))
import jquants_client


def trading_minutes_elapsed(now: datetime, sessions: list) -> float:
    """取引時間中に経過した「ザラ場分数」を返す(昼休みを除く)。取引時間外は0。
    sessions例: [["09:00","11:30"],["12:30","15:00"]]
    """
    now_min = now.hour * 60 + now.minute
    elapsed = 0.0
    for start_s, end_s in sessions:
        sh, sm = map(int, start_s.split(":"))
        eh, em = map(int, end_s.split(":"))
        start_min, end_min = sh * 60 + sm, eh * 60 + em
        if now_min <= start_min:
            continue
        elapsed += min(now_min, end_min) - start_min
    return max(elapsed, 0.0)


def total_session_minutes(sessions: list) -> float:
    total = 0.0
    for start_s, end_s in sessions:
        sh, sm = map(int, start_s.split(":"))
        eh, em = map(int, end_s.split(":"))
        total += (eh * 60 + em) - (sh * 60 + sm)
    return total


def _fetch_history_yfinance(code: str):
    t = yf.Ticker(f"{code}.T")
    hist = t.history(period="1y")
    return hist if not hist.empty else None


def _fetch_today_row_yfinance(code: str):
    """J-Quants無料プランは日足EODのみでザラ場中のリアルタイム出来高が取れないため、
    当日分だけyfinanceで補う。当日分がまだ配信されていなければNoneを返す。
    """
    t = yf.Ticker(f"{code}.T")
    recent = t.history(period="5d")
    if recent.empty:
        return None
    last = recent.iloc[[-1]]
    if last.index[0].date() != datetime.now().date():
        return None
    return last[["Close", "High", "Low", "Volume"]]


def _fetch_history_jquants(code: str):
    """未検証(実認証情報での動作確認をしていない)。失敗時は例外を送出し、呼び出し側でyfinanceにフォールバックする。"""
    email = get_secret("JQUANTS_EMAIL")
    password = get_secret("JQUANTS_PASSWORD")
    if not email or not password:
        return None

    id_token = jquants_client.get_id_token(email, password)
    to_date = datetime.now().strftime("%Y-%m-%d")
    from_date = (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d")
    quotes = jquants_client.fetch_daily_quotes(code, id_token, from_date, to_date)

    rows = []
    for q in quotes:
        if q.get("Close") is None:
            continue  # 権利落ち等で当日欠測の日はスキップ
        rows.append({"Date": pd.to_datetime(q["Date"]), "Close": q["Close"],
                      "High": q["High"], "Low": q["Low"], "Volume": q["Volume"]})
    if not rows:
        return None
    hist = pd.DataFrame(rows).set_index("Date").sort_index()

    today_row = _fetch_today_row_yfinance(code)
    if today_row is not None:
        hist = hist[hist.index.date != datetime.now().date()]  # J-Quants側に当日分があれば重複を避ける
        hist = pd.concat([hist, today_row])
    return hist


def fetch_history(code: str):
    """MA75・52週安値・20日平均出来高すべてに対応できるよう1年分の日足を取得する。
    仕様通りJ-Quants(.envにJQUANTS_EMAIL/PASSWORDがあれば)を優先し、
    未設定または失敗時はyfinanceにフォールバックする。
    最終行は取引時間中なら当日の未確定(部分)バーになる点に注意。
    """
    if get_secret("JQUANTS_EMAIL"):
        try:
            hist = _fetch_history_jquants(code)
            if hist is not None and len(hist) >= 20:
                return hist
            print(f"[警告] {code}: J-Quantsのデータが不十分なためyfinanceにフォールバックします")
        except Exception as e:
            print(f"[警告] {code}: J-Quants取得に失敗しました({e})。yfinanceにフォールバックします")

    return _fetch_history_yfinance(code)


def check_low_price(hist, cfg: dict) -> dict:
    lp = cfg["signal"]["low_price"]
    closes = hist["Close"]
    highs = hist["High"]
    lows = hist["Low"]
    price = closes.iloc[-1]

    checks = {}

    if "ma_deviation" in lp["checks"]:
        ma25 = closes.rolling(25).mean().iloc[-1] if len(closes) >= 25 else None
        ma75 = closes.rolling(75).mean().iloc[-1] if len(closes) >= 75 else None
        devs = []
        if ma25 and ma25 > 0:
            devs.append((price - ma25) / ma25 * 100)
        if ma75 and ma75 > 0:
            devs.append((price - ma75) / ma75 * 100)
        dev = min(devs) if devs else None
        checks["ma_deviation"] = {
            "value": round(dev, 2) if dev is not None else None,
            "passed": bool(dev is not None and dev <= lp["ma_deviation_pct"]),
        }

    if "week52_low" in lp["checks"]:
        week52_low = lows.iloc[-252:].min() if len(lows) > 0 else None
        uplift = (price - week52_low) / week52_low * 100 if week52_low else None
        checks["week52_low"] = {
            "value": round(uplift, 2) if uplift is not None else None,
            "passed": bool(uplift is not None and uplift <= lp["week52_low_upper_pct"]),
        }

    if "drawdown" in lp["checks"]:
        n = lp["drawdown_lookback_days"]
        recent_high = highs.iloc[-n:].max() if len(highs) > 0 else None
        drawdown = (price - recent_high) / recent_high * 100 if recent_high else None
        checks["drawdown"] = {
            "value": round(drawdown, 2) if drawdown is not None else None,
            "passed": bool(drawdown is not None and drawdown <= lp["drawdown_pct"]),
        }

    results = [c["passed"] for c in checks.values()]
    passed = any(results) if lp["require"] == "any" else all(results) if results else False

    return {"price": round(price, 1), "checks": checks, "passed": passed}


def check_volume_surge(hist, cfg: dict, now: datetime = None) -> dict:
    vs = cfg["signal"]["volume_surge"]
    sessions = cfg["market_hours"]["sessions"]
    now = now or datetime.now()

    volumes = hist["Volume"]
    n = vs["avg_period_days"]
    # 最終行は当日(取引時間中は部分バー)の可能性があるため平均算出からは除外する
    past_volumes = volumes.iloc[:-1] if len(volumes) > 1 else volumes
    avg_vol = past_volumes.iloc[-n:].mean() if len(past_volumes) >= 1 else None
    today_vol = volumes.iloc[-1]

    elapsed = trading_minutes_elapsed(now, sessions)
    total = total_session_minutes(sessions)

    prorated = False
    if vs["intraday_prorate"] and 0 < elapsed < total:
        if elapsed < vs["min_elapsed_minutes"]:
            # 寄り付き直後は按分の分母が小さすぎて誤検知するため判定自体を保留する
            return {"today_volume": int(today_vol), "avg_volume": None, "ratio": None,
                    "passed": False, "note": f"経過{elapsed:.0f}分 < min_elapsed_minutes、判定保留"}
        avg_vol = avg_vol * (elapsed / total) if avg_vol else None
        prorated = True

    ratio = today_vol / avg_vol if avg_vol else None
    passed = bool(ratio is not None and ratio >= vs["multiplier"])

    return {
        "today_volume": int(today_vol),
        "avg_volume": round(avg_vol, 0) if avg_vol is not None else None,
        "ratio": round(ratio, 2) if ratio is not None else None,
        "prorated": prorated,
        "passed": passed,
    }


def evaluate(code: str, cfg: dict, now: datetime = None) -> dict | None:
    hist = fetch_history(code)
    if hist is None or len(hist) < 20:
        return None
    low_price = check_low_price(hist, cfg)
    volume_surge = check_volume_surge(hist, cfg, now)
    return {
        "code": code,
        "price": low_price["price"],
        "low_price": low_price,
        "volume_surge": volume_surge,
        "signal": low_price["passed"] and volume_surge["passed"],
    }


if __name__ == "__main__":
    import io
    import json
    from pathlib import Path

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import config_loader

    code = sys.argv[1] if len(sys.argv) > 1 else "7203"
    cfg = config_loader.load_config()
    result = evaluate(code, cfg)
    print(json.dumps(result, ensure_ascii=False, indent=2))
