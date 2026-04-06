"""
リサーチ部署 バッチデータ収集スクリプト
毎朝実行 → .company/research/raw/YYYY-MM-DD-raw.md に保存
Claudeはこのファイルを読むだけでWebSearch不要になる
"""

import json
import os
from datetime import date, datetime

import feedparser
from pytrends.request import TrendReq

TODAY = date.today().strftime("%Y-%m-%d")
OUTPUT_PATH = f".company/research/raw/{TODAY}-raw.md"

# -----------------------------------------------
# 設定: 追跡キーワード・RSSフィード
# -----------------------------------------------

TREND_KEYWORDS = [
    ["AI副業", "アフィリエイト", "note収益化"],
    ["生成AI", "Claude API", "ChatGPT"],
    ["副業", "マネタイズ", "SaaS"],
]

RSS_FEEDS = {
    "はてブ（テクノロジー）": "https://b.hatena.ne.jp/hotentry/it.rss",
    "はてブ（一般）": "https://b.hatena.ne.jp/hotentry.rss",
    "TechCrunch Japan": "https://jp.techcrunch.com/feed/",
    "note（おすすめ）": "https://note.com/intent/rss",
}

RSS_MAX_ITEMS = 5  # フィードごとの最大取得件数


# -----------------------------------------------
# Google Trends 取得
# -----------------------------------------------

def fetch_google_trends() -> str:
    lines = ["## Google Trends（国内・過去7日）\n"]
    try:
        pytrends = TrendReq(hl="ja-JP", tz=540, timeout=(10, 30))
        for keywords in TREND_KEYWORDS:
            pytrends.build_payload(keywords, timeframe="now 7-d", geo="JP")
            data = pytrends.interest_over_time()
            if data.empty:
                continue
            avg = data[keywords].mean().sort_values(ascending=False)
            lines.append(f"**{' / '.join(keywords)}**")
            for kw, score in avg.items():
                lines.append(f"- {kw}: {score:.0f}")
            lines.append("")
    except Exception as e:
        lines.append(f"（取得失敗: {e}）\n")
    return "\n".join(lines)


# -----------------------------------------------
# RSS フィード取得
# -----------------------------------------------

def fetch_rss() -> str:
    lines = ["## RSS ヘッドライン\n"]
    for name, url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            lines.append(f"### {name}")
            for entry in feed.entries[:RSS_MAX_ITEMS]:
                title = entry.get("title", "").strip()
                link = entry.get("link", "")
                lines.append(f"- [{title}]({link})")
            lines.append("")
        except Exception as e:
            lines.append(f"### {name}\n（取得失敗: {e}）\n")
    return "\n".join(lines)


# -----------------------------------------------
# 関連トレンドキーワード取得
# -----------------------------------------------

def fetch_related_queries() -> str:
    lines = ["## 関連急上昇キーワード\n"]
    try:
        pytrends = TrendReq(hl="ja-JP", tz=540, timeout=(10, 30))
        flat_keywords = [kw for group in TREND_KEYWORDS for kw in group]
        pytrends.build_payload(flat_keywords[:5], timeframe="now 7-d", geo="JP")
        related = pytrends.related_queries()
        for kw, data in related.items():
            rising = data.get("rising")
            if rising is not None and not rising.empty:
                lines.append(f"**{kw}の急上昇ワード:**")
                for _, row in rising.head(3).iterrows():
                    lines.append(f"- {row['query']} (急上昇値: {row['value']})")
                lines.append("")
    except Exception as e:
        lines.append(f"（取得失敗: {e}）\n")
    return "\n".join(lines)


# -----------------------------------------------
# メイン
# -----------------------------------------------

def main():
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    sections = [
        f"# リサーチ生データ - {TODAY}",
        f"_自動収集: {now} JST_\n",
        fetch_google_trends(),
        fetch_related_queries(),
        fetch_rss(),
        "---",
        "_このファイルはバッチ自動生成。Claudeはこれを読んで分析する。_",
    ]

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(sections))

    print(f"[OK] 保存完了: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
