"""リスク管理情報の算出（許容損失額・損切価格・最大許容株数）
単体実行: python risk_calc.py 2500
"""


def calc_risk(entry_price: float, cfg: dict) -> dict:
    """エントリー想定価格に対する許容損失額・損切価格・最大許容株数をレンジで算出する。
    - 損切価格は stop_loss_pct_min(タイトな損切り) / stop_loss_pct_max(ワイドな損切り) の2点
    - 最大許容株数は「保守的(risk_pct_min ÷ ワイドな損切り距離)」〜「積極的(risk_pct_max ÷ タイトな損切り距離)」のレンジ
    - 単元株数(share_unit)未満は切り捨てる
    """
    rm = cfg["risk_management"]
    balance = rm["account_balance_yen"]
    unit = rm["share_unit"]

    loss_min = balance * rm["risk_pct_min"] / 100
    loss_max = balance * rm["risk_pct_max"] / 100

    stop_price_tight = entry_price * (1 - rm["stop_loss_pct_min"] / 100)
    stop_price_wide = entry_price * (1 - rm["stop_loss_pct_max"] / 100)

    dist_tight = entry_price - stop_price_tight
    dist_wide = entry_price - stop_price_wide

    shares_conservative = int(loss_min / dist_wide // unit * unit) if dist_wide > 0 else 0
    shares_aggressive = int(loss_max / dist_tight // unit * unit) if dist_tight > 0 else 0
    shares_min = min(shares_conservative, shares_aggressive)
    shares_max = max(shares_conservative, shares_aggressive)

    return {
        "balance_yen": balance,
        "loss_min_yen": round(loss_min),
        "loss_max_yen": round(loss_max),
        "risk_pct_min": rm["risk_pct_min"],
        "risk_pct_max": rm["risk_pct_max"],
        "stop_price_tight": round(stop_price_tight, 1),
        "stop_price_wide": round(stop_price_wide, 1),
        "stop_loss_pct_min": rm["stop_loss_pct_min"],
        "stop_loss_pct_max": rm["stop_loss_pct_max"],
        "shares_min": shares_min,
        "shares_max": shares_max,
    }


if __name__ == "__main__":
    import sys
    import io
    import json
    from pathlib import Path

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import config_loader

    price = float(sys.argv[1]) if len(sys.argv) > 1 else 2500.0
    cfg = config_loader.load_config()
    print(json.dumps(calc_risk(price, cfg), ensure_ascii=False, indent=2))
