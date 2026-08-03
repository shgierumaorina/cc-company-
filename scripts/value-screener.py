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

    try:
        result = subprocess.run(
            ["claude", "-p", prompt],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
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
