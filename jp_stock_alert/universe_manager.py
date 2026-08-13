"""優良銘柄マスタ・監視リストの管理
- master_candidates.json: irbankスコアリングの結果全件（優良/非優良を問わず記録し、閾値通過分をpassed=trueにする）
- watchlist.json: ユーザーが監視対象に選んだ銘柄コードのリスト
"""
import json
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent))
import irbank_client

try:
    import yfinance as yf
except ImportError:
    yf = None

UNIVERSE_DIR = Path(__file__).resolve().parent / "universe"
MASTER_PATH = UNIVERSE_DIR / "master_candidates.json"
WATCHLIST_PATH = UNIVERSE_DIR / "watchlist.json"


def _load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _save_json(path: Path, data) -> None:
    UNIVERSE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_master() -> list[dict]:
    return _load_json(MASTER_PATH, [])


def save_master(entries: list[dict]) -> None:
    _save_json(MASTER_PATH, entries)


def load_watchlist() -> list[dict]:
    return _load_json(WATCHLIST_PATH, [])


def save_watchlist(entries: list[dict]) -> None:
    _save_json(WATCHLIST_PATH, entries)


def _fetch_name(code: str) -> str:
    if yf is None:
        return ""
    try:
        info = yf.Ticker(f"{code}.T").info
        return info.get("shortName") or info.get("longName") or ""
    except Exception as e:
        print(f"[警告] {code} の銘柄名取得に失敗: {e}")
        return ""


def score_code(code: str, cfg: dict) -> dict:
    """1銘柄分をirbankから取得し、config.yamlのuniverse設定に基づきスコアリングする。
    データ取得に失敗した項目は加点せず、data_incompleteフラグを立てる(捏造しない)。
    """
    u = cfg["universe"]
    errors = []
    try:
        summary = irbank_client.fetch_summary_metrics(
            code, u["cache_ttl_hours"], u["request_interval_sec"])
        summary["payout_ratio_pct"] = irbank_client.fetch_dividend_payout_ratio(summary)
    except Exception as e:
        print(f"[エラー] {code} のirbank summary取得に失敗: {e}")
        summary = {"roe_pct": None, "equity_ratio_pct": None, "market_cap_oku_yen": None,
                   "per": None, "dividend_yield_pct": None, "eps": None, "payout_ratio_pct": None}
        errors.append(str(e))

    try:
        trend = irbank_client.fetch_earnings_trend(
            code, u["cache_ttl_hours"], u["request_interval_sec"])
    except Exception as e:
        print(f"[エラー] {code} のirbank pl取得に失敗: {e}")
        trend = {"revenue_growth": None, "op_income_growth": None}
        errors.append(str(e))

    score = 0
    data_incomplete = False

    roe = summary.get("roe_pct")
    if roe is None:
        data_incomplete = True
    elif roe >= u["roe_full_score"]:
        score += 25
    elif roe >= u["min_roe"]:
        score += 15

    eq = summary.get("equity_ratio_pct")
    if eq is None:
        data_incomplete = True
    elif eq >= u["min_equity_ratio"]:
        score += 20
    elif eq >= u["equity_ratio_partial"]:
        score += 10

    rg, og = trend.get("revenue_growth"), trend.get("op_income_growth")
    if rg is None or og is None:
        data_incomplete = True
    elif rg and og:
        score += 25
    elif rg or og:
        score += 12

    cap = summary.get("market_cap_oku_yen")
    if cap is None:
        data_incomplete = True
    elif cap >= u["min_market_cap_oku_yen"]:
        score += 15

    payout = summary.get("payout_ratio_pct")
    if payout is None:
        data_incomplete = True
    elif payout <= u["max_payout_ratio"]:
        score += 15
    elif payout <= u["payout_ratio_partial"]:
        score += 7

    return {
        "code": code,
        "name": _fetch_name(code),
        "score": score,
        "passed": score >= u["score_pass_threshold"],
        "data_incomplete": data_incomplete,
        "metrics": summary,
        "trend": trend,
        "errors": errors,
        "scored_at": datetime.now().isoformat(timespec="seconds"),
    }


def upsert_master(entries: list[dict], new_result: dict) -> list[dict]:
    entries = [e for e in entries if e["code"] != new_result["code"]]
    entries.append(new_result)
    entries.sort(key=lambda e: e["code"])
    return entries


def add_to_watchlist(watchlist: list[dict], code: str, name: str = "") -> tuple[list[dict], bool]:
    if any(w["code"] == code for w in watchlist):
        return watchlist, False
    watchlist.append({"code": code, "name": name, "added_at": datetime.now().isoformat(timespec="seconds")})
    watchlist.sort(key=lambda w: w["code"])
    return watchlist, True


def remove_from_watchlist(watchlist: list[dict], code: str) -> tuple[list[dict], bool]:
    new_list = [w for w in watchlist if w["code"] != code]
    return new_list, len(new_list) != len(watchlist)
