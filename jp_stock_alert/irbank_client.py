"""irbank.net から財務指標を取得するクライアント
- 実ページ(https://irbank.net/7203, /7203/pl)のHTML構造を確認した上で実装（推測でのパースはしない）
- <dt>ラベル</dt><dd>値</dd> 形式の定義リストを汎用的に辞書化して取得する
- ローカルキャッシュ(cache_ttl_hours)とリクエスト間隔(request_interval_sec)でアクセス頻度を抑制する
"""
import re
import time
import urllib.request
from pathlib import Path

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
BASE = "https://irbank.net"
CACHE_DIR = Path(__file__).resolve().parent / ".cache" / "irbank"

_DT_DD_RE = re.compile(r"<dt[^>]*>(.*?)</dt>\s*<dd[^>]*>(.*?)</dd>", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_TEXT_SPAN_RE = re.compile(r'<span class="text">([^<]*)</span>')

_last_request_ts = 0.0


def _strip_tags(html: str) -> str:
    return _TAG_RE.sub("", html).strip()


def _fetch(url: str, cache_key: str, cache_ttl_hours: float, request_interval_sec: float) -> str:
    """キャッシュが有効ならそれを返す。無効ならレート制限を守って取得しキャッシュする。"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"{cache_key}.html"
    if cache_path.exists():
        age_hours = (time.time() - cache_path.stat().st_mtime) / 3600
        if age_hours < cache_ttl_hours:
            return cache_path.read_text(encoding="utf-8", errors="replace")

    global _last_request_ts
    elapsed = time.time() - _last_request_ts
    if elapsed < request_interval_sec:
        time.sleep(request_interval_sec - elapsed)

    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    _last_request_ts = time.time()

    cache_path.write_text(html, encoding="utf-8")
    return html


def _parse_dt_dd(html: str) -> dict:
    """<dt>...</dt><dd>...</dd> のペアを汎用的に {ラベル: 値} へ変換する。
    ddに <span class="text">値</span> があればそれを優先し、無ければタグを剥いだ全文を使う。
    """
    result = {}
    for dt_html, dd_html in _DT_DD_RE.findall(html):
        label = _strip_tags(dt_html)
        if not label:
            continue
        text_match = _TEXT_SPAN_RE.search(dd_html)
        value = text_match.group(1) if text_match else _strip_tags(dd_html)
        # 同じラベルが複数回出現する場合は最初の出現を採用する（ページ上部のサマリを優先）
        result.setdefault(label, value)
    return result


def _parse_percent(value: str) -> float | None:
    if not value:
        return None
    m = re.search(r"-?[\d.]+", value)
    return float(m.group(0)) if m else None


def _parse_jpy_oku(value: str) -> float | None:
    """「43兆7849億」のような日本語表記を億円単位の数値に変換する。"""
    if not value:
        return None
    cho_m = re.search(r"([\d.]+)兆", value)
    oku_m = re.search(r"([\d.]+)億", value)
    cho = float(cho_m.group(1)) if cho_m else 0.0
    oku = float(oku_m.group(1)) if oku_m else 0.0
    if not cho_m and not oku_m:
        return None
    return cho * 10000 + oku


def fetch_summary_metrics(code: str, cache_ttl_hours: float = 24, request_interval_sec: float = 2.0) -> dict:
    """メインページ(/{code})からROE・自己資本比率・時価総額・PER・配当利回り・EPSを取得する。
    取得できない項目はNoneのまま返す(捏造しない)。配当性向はここでは算出しない(fetch_dividend_payout_ratio参照)。
    """
    html = _fetch(f"{BASE}/{code}", f"{code}_summary", cache_ttl_hours, request_interval_sec)
    dl = _parse_dt_dd(html)

    roe = dl.get("ROE（連）") or dl.get("ROE")
    equity_ratio = dl.get("株主資本比率（連）")
    market_cap = dl.get("時価総額")
    # ページ上部のサマリ欄はラベルに&thinsp;実体参照が混ざり不安定なため、
    # 株式指標セクションの明示ラベル(予想ベースで統一)を優先して使う
    per = dl.get("PER（連）予") or dl.get("PER（連）")
    dividend_yield = dl.get("配当利回り 予") or dl.get("配当利回り")
    eps = dl.get("EPS（連）")

    return {
        "code": code,
        "roe_pct": _parse_percent(roe),
        "equity_ratio_pct": _parse_percent(equity_ratio),
        "market_cap_oku_yen": _parse_jpy_oku(market_cap),
        "per": _parse_percent(per),
        "dividend_yield_pct": _parse_percent(dividend_yield),
        "eps": _parse_percent(eps),
    }


def fetch_dividend_payout_ratio(summary: dict) -> float | None:
    """irbankには配当性向の直接ラベルがないため、
    配当性向(%) = 配当利回り(%, =100*DPS/Price) × PER(倍, =Price/EPS) = 100*DPS/EPS という恒等式から算出する。
    """
    y = summary.get("dividend_yield_pct")
    per = summary.get("per")
    if y is None or per is None:
        return None
    return round(y * per, 1)


_TBODY_RE = re.compile(r"<tbody>(.*?)</tbody>", re.DOTALL)
_PL_TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL)
_PL_YEAR_RE = re.compile(r"(\d{4})年")


def _to_num(td_html: str) -> int | None:
    t = _strip_tags(td_html).replace(",", "")
    m = re.search(r"-?\d+", t)
    return int(m.group(0)) if m else None


def fetch_earnings_trend(code: str, cache_ttl_hours: float = 24, request_interval_sec: float = 2.0) -> dict:
    """/{code}/pl の四半期テーブルから「通期」行を抽出し、直近2期の増収増益を判定する。
    年度セルはrowspanで複数行にまたがり、継続行は<tr>の開始タグ自体を省略しているため
    (ブラウザのHTML5パーサが暗黙にtrを補完する挙動に依存したマークアップ)、
    <tr>単位ではなく</tr>区切りで行を分割し、直近に見た年度を引き継いで処理する。
    """
    html = _fetch(f"{BASE}/{code}/pl", f"{code}_pl", cache_ttl_hours, request_interval_sec)
    tbody_match = _TBODY_RE.search(html)
    body = tbody_match.group(1) if tbody_match else ""

    full_year_rows = []
    current_year = None
    for raw_row in body.split("</tr>"):
        tds = _PL_TD_RE.findall(raw_row)
        if not tds:
            continue

        year_match = _PL_YEAR_RE.search(_strip_tags(tds[0]))
        if year_match:
            current_year = int(year_match.group(1))
            quarter_idx, revenue_idx, op_income_idx = 1, 3, 4
        else:
            quarter_idx, revenue_idx, op_income_idx = 0, 2, 3

        if current_year is None or len(tds) <= op_income_idx:
            continue
        quarter_text = _strip_tags(tds[quarter_idx])
        # 各期に「通期予想/通期修正/通期実績」が並ぶため、確定値の「通期実績」のみを採用する
        if "通期" not in quarter_text or "実績" not in quarter_text:
            continue

        revenue = _to_num(tds[revenue_idx])
        op_income = _to_num(tds[op_income_idx])
        if revenue is None or op_income is None:
            continue
        full_year_rows.append({"year": current_year, "revenue": revenue, "op_income": op_income})

    full_year_rows.sort(key=lambda r: r["year"])
    if len(full_year_rows) < 2:
        return {"code": code, "revenue_growth": None, "op_income_growth": None, "years_available": len(full_year_rows)}

    prev, latest = full_year_rows[-2], full_year_rows[-1]
    revenue_growth = latest["revenue"] > prev["revenue"] if prev["revenue"] else None
    op_income_growth = latest["op_income"] > prev["op_income"] if prev["op_income"] else None

    return {
        "code": code,
        "revenue_growth": revenue_growth,
        "op_income_growth": op_income_growth,
        "years_available": len(full_year_rows),
        "latest_year": latest["year"],
    }


if __name__ == "__main__":
    import sys, io, json
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    code = sys.argv[1] if len(sys.argv) > 1 else "7203"
    summary = fetch_summary_metrics(code)
    summary["payout_ratio_pct"] = fetch_dividend_payout_ratio(summary)
    trend = fetch_earnings_trend(code)
    print(json.dumps({"summary": summary, "trend": trend}, ensure_ascii=False, indent=2))
