"""過去データで「安値圏×出来高急増」シグナルを再現し、その後の値動きを検証するバックテスト
実行例:
  python backtest.py                          # 優良銘柄マスタ(passed=true)・過去2年
  python backtest.py --universe watchlist      # 監視リストのみ
  python backtest.py --years 3 --codes 7203,6758
"""
import sys
import io
import argparse
from pathlib import Path
from datetime import datetime, time as dtime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import numpy as np
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config_loader
import universe_manager as um
import signal_detector

RESULTS_DIR = Path(__file__).resolve().parent / "backtest_results"
FORWARD_DAYS = (5, 10)
WARMUP_DAYS = 100          # MA75・出来高平均が安定するまでの最低営業日数
VOL_RATIO_GRID = [2.0, 2.5, 3.0, 3.5]
STOP_LOSS_GRID = [7.0, 8.0, 9.0, 10.0]


def load_universe(source: str, codes_arg: str | None) -> list[dict]:
    if codes_arg:
        codes = [c.strip() for c in codes_arg.split(",") if c.strip()]
        return [{"code": c, "name": c} for c in codes]
    if source == "watchlist":
        return [{"code": w["code"], "name": w.get("name", w["code"])} for w in um.load_watchlist()]
    return [{"code": m["code"], "name": m.get("name", m["code"])}
            for m in um.load_master() if m.get("passed")]


def fetch_batch(tickers: list[str], years: int) -> dict:
    data = yf.download(tickers, period=f"{years}y", progress=False, group_by="ticker", threads=True)
    out = {}
    for t in tickers:
        try:
            df = data[t].dropna(subset=["Open", "High", "Low", "Close", "Volume"])
            if len(df) >= WARMUP_DAYS + max(FORWARD_DAYS) + 1:
                out[t] = df
        except Exception:
            continue
    return out


def replay_signals(code: str, df, cfg: dict) -> list[dict]:
    """1銘柄分、ルックアヘッドなしで各日のシグナルを再現し、その後の値動きを記録する。"""
    records = []
    forward_max = max(FORWARD_DAYS)
    for i in range(WARMUP_DAYS, len(df) - forward_max):
        hist_slice = df.iloc[:i + 1]
        eval_date = df.index[i]
        now = datetime.combine(eval_date.date(), dtime(15, 1))  # 場後扱い=按分なしで判定させる

        low_price = signal_detector.check_low_price(hist_slice, cfg)
        volume_surge = signal_detector.check_volume_surge(hist_slice, cfg, now)
        liquidity = signal_detector.check_liquidity(hist_slice, cfg)
        confirmation = signal_detector.check_confirmation(hist_slice, cfg)
        strength = signal_detector.classify_strength(low_price, volume_surge, liquidity, confirmation)
        if strength is None:
            continue

        entry = df["Close"].iloc[i]
        rec = {
            "code": code, "date": eval_date.strftime("%Y-%m-%d"),
            "strength": strength, "entry": float(entry),
            "vol_ratio": volume_surge["ratio"],
        }
        window_low = df["Low"].iloc[i + 1:i + forward_max + 1]
        rec["max_drawdown_pct"] = float((window_low.min() / entry - 1) * 100) if not window_low.empty else None
        for d in FORWARD_DAYS:
            fwd_close = df["Close"].iloc[i + d]
            rec[f"ret_{d}d_pct"] = float((fwd_close / entry - 1) * 100)
        records.append(rec)
    return records


def summarize(records: list[dict], key_filter=None) -> dict:
    rows = [r for r in records if key_filter is None or key_filter(r)]
    out = {"n": len(rows)}
    for d in FORWARD_DAYS:
        rets = [r[f"ret_{d}d_pct"] for r in rows]
        if rets:
            out[f"win_rate_{d}d"] = sum(1 for x in rets if x > 0) / len(rets) * 100
            out[f"avg_ret_{d}d"] = float(np.mean(rets))
        else:
            out[f"win_rate_{d}d"] = None
            out[f"avg_ret_{d}d"] = None
    dds = [r["max_drawdown_pct"] for r in rows if r["max_drawdown_pct"] is not None]
    out["avg_max_drawdown"] = float(np.mean(dds)) if dds else None
    return out


def simulate_stop_loss(records: list[dict], stop_loss_pct: float) -> dict:
    """各シグナルについて、10営業日の窓内でstop_loss_pctを下回ったら-stop_loss_pct%で損切りしたとみなして
    シミュレーション後リターンを計算する。損切りに触れなければ実際の10営業日後リターンを使う。
    """
    sim_rets = []
    for r in records:
        if r["max_drawdown_pct"] is not None and r["max_drawdown_pct"] <= -stop_loss_pct:
            sim_rets.append(-stop_loss_pct)
        else:
            sim_rets.append(r["ret_10d_pct"])
    if not sim_rets:
        return {"n": 0, "avg_ret": None, "win_rate": None}
    return {
        "n": len(sim_rets),
        "avg_ret": float(np.mean(sim_rets)),
        "win_rate": sum(1 for x in sim_rets if x > 0) / len(sim_rets) * 100,
    }
