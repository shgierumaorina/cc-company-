"""
バリュー株センチメントスクリーナー - 手動実行専用（stock-screener.pyの無人デイトレフローとは独立）
① TDnetの日別開示一覧ページを遡って対象銘柄の決算短信PDFを取得
② pdfplumberでPDFから「経営成績の概況」「今後の見通し」セクションを中心に抽出
③ claude -p（Pro/Maxプラン認証、API課金なし）で複数期分をまとめてセンチメントスコアリング
④ スコア推移から改善/悪化/横ばいのトレンドを判定
⑤ 既存の価値指標（PER/PBR）と合わせてExcel出力

データソースの制約（実測で確認済み）:
- TDnetの検索フォーム(POST)はボット向けに応答せず機能しないため、日別一覧ページ
  (I_list_XXX_YYYYMMDD.html、直近31日分のみ)を遡って対象コードを探す方式にしている。
- 過去の四半期分はTDnet単体では取得できないため、実行のたびにヒストリーファイルへ
  自前で1件ずつ蓄積し、複数回実行して初めてトレンド判定ができる（自前蓄積方式）。
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import re
import json
import os
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

import subprocess
import argparse
import pdfplumber
import yfinance as yf
import pandas as pd

TDNET_BASE = "https://www.release.tdnet.info/inbs/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

DATA_DIR = Path(__file__).resolve().parent.parent / "value_screener_data"

ROW_RE = re.compile(
    r'kjCode"[^>]*>(?P<code>\d+)\s*</td>.*?'
    r'kjName"[^>]*>(?P<name>[^<]*)</td>.*?'
    r'kjTitle"[^>]*><a href="(?P<href>[^"]+)"[^>]*>(?P<title>[^<]*)</a>',
    re.DOTALL,
)


def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _fetch_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def find_latest_tanshin(code: str, lookback_days: int = 45) -> dict | None:
    """直近lookback_days日分のTDnet日別一覧を新しい日付から遡って走査し、
    指定コードの「決算短信」（訂正を除く）を見つけたら1件返す。見つからなければNone。
    """
    target_code = f"{code}0"  # TDnetは4桁コードに末尾0を付けた5桁で管理
    today = datetime.now()
    for offset in range(lookback_days):
        date = today - timedelta(days=offset)
        ymd = date.strftime("%Y%m%d")
        page = 1
        while True:
            page_no = f"{page:03d}"
            url = f"{TDNET_BASE}I_list_{page_no}_{ymd}.html"
            try:
                html = _fetch(url)
            except Exception:
                break  # その日のページが存在しない（休日等）
            if "見つかりませんでした" in html or "<table" not in html:
                break

            for m in ROW_RE.finditer(html):
                if m.group("code") != target_code:
                    continue
                title = m.group("title")
                if "決算短信" not in title or "訂正" in title:
                    continue
                return {
                    "date": date.strftime("%Y-%m-%d"),
                    "code": code,
                    "name": m.group("name").strip(),
                    "title": title,
                    "pdf_url": TDNET_BASE + m.group("href"),
                }

            # 次ページの有無をkaijiSumの総件数から簡易判定
            total_match = re.search(r"1[～~](\d+)件&nbsp;/&nbsp;全(\d+)件", html)
            if not total_match:
                break
            per_page, total = int(total_match.group(1)), int(total_match.group(2))
            if page * per_page >= total:
                break
            page += 1
            time.sleep(0.3)  # 同一日の連続ページ取得間隔
    return None


SECTION_HEADS = ["経営成績の概況", "経営成績に関する説明", "今後の見通し"]


def extract_sections(pdf_bytes: bytes, max_chars: int = 4000) -> str:
    """PDF全文から「経営成績の概況」「今後の見通し」を含む段落を中心に抽出する。
    見出しが見つからない場合は先頭max_charsをそのまま返し、その旨をログに出す。
    """
    full_text = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for p in pdf.pages:
            t = p.extract_text() or ""
            full_text.append(t)
    text = "\n".join(full_text)

    chunks = []
    for head in SECTION_HEADS:
        idx = text.rfind(head)  # 目次にも同じ見出しが出るため、本文側(後方)を採用
        if idx == -1:
            continue
        chunks.append(text[idx: idx + max_chars])

    if not chunks:
        print(f"[警告] セクション見出し{SECTION_HEADS}が見つからず、先頭{max_chars}文字を使用します")
        return text[:max_chars]
    return "\n\n".join(chunks)


def load_history(code: str) -> list[dict]:
    path = DATA_DIR / f"{code}.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def save_history(code: str, entries: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f"{code}.json"
    path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")


def upsert_entry(entries: list[dict], new_entry: dict, history_limit: int) -> list[dict]:
    """同じ日付があれば置き換え、日付昇順に並べ替えてhistory_limit件に切り詰める（自前蓄積方式）。"""
    entries = [e for e in entries if e["date"] != new_entry["date"]]
    entries.append(new_entry)
    entries.sort(key=lambda e: e["date"])
    return entries[-history_limit:]


CLAUDE_PROMPT_TEMPLATE = """あなたは日本株の決算短信を読むアナリストです。
以下は同一企業の決算短信から抽出した複数期分の「経営成績の概況」「今後の見通し」です。
各期について、sentiment(positive/neutral/negative)・score(0.0〜1.0、1.0が最も強気)・
reason(前期との比較を含む日本語1〜2文。表現が強気になったか弱気になったかに言及)を判定してください。
出力は次のJSON配列のみとし、説明文やコードブロック記号は付けないこと。

[{{"date": "YYYY-MM-DD", "sentiment": "positive", "score": 0.0, "reason": "..."}}]

--- 対象期間データ ---
{periods_text}
"""


def score_with_claude(entries: list[dict], timeout: int = 180) -> dict[str, dict]:
    """entries(抽出テキスト付き、日付昇順)をまとめてclaude -pに渡し、
    日付をキーにした{sentiment, score, reason}辞書を返す。
    claude CLI(Pro/Maxプランの認証セッション、API課金なし)を使う。
    失敗時は空辞書を返し、生の標準エラー/出力をそのまま表示する(スコアの捏造をしない)。
    """
    periods_text = "\n\n".join(f"[{e['date']}]\n{e['extracted_text']}" for e in entries)
    prompt = CLAUDE_PROMPT_TEMPLATE.format(periods_text=periods_text)

    # OmniRoute（ローカルプロキシ、圧縮・キャッシュで節約）経由でclaude -pを呼ぶ。
    # このスクリプトの子プロセスだけに適用し、他のセッション設定には影響しない。
    env = {**os.environ, "ANTHROPIC_BASE_URL": "http://localhost:20128/v1", "ANTHROPIC_AUTH_TOKEN": "omniroute-local"}

    try:
        result = subprocess.run(
            ["claude", "-p", prompt],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
            env=env,
        )
    except FileNotFoundError:
        print("[エラー] claude CLIが見つかりません。Claude CodeがインストールされPATHが通っているか確認してください")
        return {}
    except subprocess.TimeoutExpired:
        print(f"[エラー] claude -p がタイムアウトしました({timeout}秒)")
        return {}

    if result.returncode != 0:
        print(f"[エラー] claude -p が失敗しました(exit={result.returncode})")
        print(result.stderr)
        return {}

    raw = re.sub(r"^```(json)?|```$", "", result.stdout.strip(), flags=re.MULTILINE).strip()
    # 指示してもclaudeがJSON配列の前後に補足説明文を付け足すことがあるため、
    # 配列部分(最初の[から最後の]まで)だけを抜き出してから解析する
    array_match = re.search(r"\[.*\]", raw, re.DOTALL)
    if array_match:
        raw = array_match.group(0)
    try:
        scored = json.loads(raw)
    except json.JSONDecodeError:
        print("[エラー] claudeの出力をJSONとして解釈できませんでした:")
        print(raw)
        return {}

    return {item["date"]: item for item in scored if "date" in item}


def compute_trend(entries: list[dict]) -> str:
    """スコア推移から「改善傾向/悪化傾向/横ばい」を判定する。
    3期以上あれば線形回帰の傾き、2期のみなら単純差分を使う。2期未満は「データ不足」。
    """
    scored = sorted((e for e in entries if "score" in e), key=lambda e: e["date"])
    if len(scored) < 2:
        return "データ不足"

    if len(scored) >= 3:
        n = len(scored)
        xs = list(range(n))
        ys = [e["score"] for e in scored]
        mean_x, mean_y = sum(xs) / n, sum(ys) / n
        num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
        den = sum((x - mean_x) ** 2 for x in xs)
        slope = num / den if den else 0.0
    else:
        slope = scored[-1]["score"] - scored[-2]["score"]

    if slope > 0.05:
        return "改善傾向"
    if slope < -0.05:
        return "悪化傾向"
    return "横ばい"


def process_code(code: str, history_limit: int, lookback_days: int) -> dict | None:
    """1銘柄分の取得→抽出→蓄積→スコアリング→トレンド判定を実行する。履歴が1件も無ければNone。"""
    found = find_latest_tanshin(code, lookback_days=lookback_days)
    history = load_history(code)

    if found is None:
        print(f"[{code}] 直近{lookback_days}日以内に決算短信が見つかりませんでした")
    elif any(e["date"] == found["date"] for e in history):
        print(f"[{code}] {found['date']}分は取得済みです")
    else:
        print(f"[{code}] {found['date']} {found['title']} を取得します")
        pdf_bytes = _fetch_bytes(found["pdf_url"])
        found["extracted_text"] = extract_sections(pdf_bytes)
        history = upsert_entry(history, found, history_limit)

    if not history:
        return None

    scored_map = score_with_claude(history)
    for e in history:
        if e["date"] in scored_map:
            e.update({k: v for k, v in scored_map[e["date"]].items() if k != "date"})
    save_history(code, history)

    latest = history[-1]
    return {
        "code": code,
        "name": latest.get("name", ""),
        "latest_date": latest["date"],
        "latest_sentiment": latest.get("sentiment", "不明"),
        "latest_score": latest.get("score"),
        "trend": compute_trend(history),
        "history_count": len(history),
    }


def fetch_value_metrics(code: str) -> dict:
    """PER/PBR/株価をyfinanceから取得する。取得できない項目はNoneのまま返す(捏造しない)。"""
    try:
        info = yf.Ticker(f"{code}.T").info
    except Exception as e:
        print(f"[警告] {code}のyfinance取得に失敗: {e}")
        return {"per": None, "pbr": None, "price": None}
    return {
        "per": info.get("trailingPE"),
        "pbr": info.get("priceToBook"),
        "price": info.get("currentPrice"),
    }


def export_excel(results: list[dict], out_path: str, per_max: float, pbr_max: float) -> None:
    rows = []
    for r in results:
        m = fetch_value_metrics(r["code"])
        is_value = m["per"] is not None and m["per"] < per_max and m["pbr"] is not None and m["pbr"] < pbr_max
        is_improving = r["trend"] == "改善傾向"
        rows.append({
            "コード": r["code"],
            "会社名": r["name"],
            "PER": m["per"],
            "PBR": m["pbr"],
            "株価": m["price"],
            "バリュー型": is_value,
            "直近開示日": r["latest_date"],
            "直近センチメント": r["latest_sentiment"],
            "直近スコア": r["latest_score"],
            "センチメント推移件数": r["history_count"],
            "トレンド判定": r["trend"],
            "バリュー×改善": is_value and is_improving,
        })
    pd.DataFrame(rows).to_excel(out_path, index=False, engine="openpyxl")
    print(f"Excel出力: {out_path} ({len(rows)}銘柄)")


def main():
    parser = argparse.ArgumentParser(description="TDnet決算短信センチメント×バリュースクリーナー(手動実行)")
    parser.add_argument("--codes", required=True, help="銘柄コードをカンマ区切りで指定 例: 7203,6758")
    parser.add_argument("--history-limit", type=int, default=4, help="蓄積する履歴の最大件数(デフォルト4)")
    parser.add_argument("--lookback-days", type=int, default=45, help="TDnetを遡る日数(デフォルト45)")
    parser.add_argument("--export-excel", help="出力するExcelファイルパス(指定時のみExcel出力)")
    parser.add_argument("--per-max", type=float, default=15.0, help="バリュー型判定のPER上限(デフォルト15)")
    parser.add_argument("--pbr-max", type=float, default=1.0, help="バリュー型判定のPBR上限(デフォルト1.0)")
    args = parser.parse_args()

    codes = [c.strip() for c in args.codes.split(",") if c.strip()]
    results = [r for c in codes if (r := process_code(c, args.history_limit, args.lookback_days))]

    print("\n=== 結果サマリ ===")
    for r in results:
        print(
            f"[{r['code']}] {r['name']} | 直近{r['latest_date']} "
            f"{r['latest_sentiment']}(score={r['latest_score']}) | "
            f"トレンド={r['trend']}(履歴{r['history_count']}件)"
        )

    if args.export_excel:
        export_excel(results, args.export_excel, args.per_max, args.pbr_max)


if __name__ == "__main__":
    main()
