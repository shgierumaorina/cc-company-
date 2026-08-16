"""
PostToolUseフック: post.py実行後にLINE通知 + Claudeへ Notion登録を促す
stdin: {"tool_name": "Bash", "tool_input": {"command": "..."}, "tool_response": {...}}
"""
import sys
import json
import re
import requests
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

from envutil import get_secret

LINE_CHANNEL_ACCESS_TOKEN = get_secret("LINE_CHANNEL_ACCESS_TOKEN")
LINE_TO_USER_ID = "U3f262fa723717ae421201059739cdb04"


def send_line(message: str):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    data = {
        "to": LINE_TO_USER_ID,
        "messages": [{"type": "text", "text": message.strip()}],
    }
    requests.post(url, headers=headers, json=data, timeout=10)


def main():
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except Exception:
        sys.exit(0)

    command = data.get("tool_input", {}).get("command", "")

    # post.py の実行でなければスキップ（hook_after_post.py 等のファイル名言及には反応しない）
    if not re.search(r"(?<![\w.])post\.py\b", command):
        sys.exit(0)

    # tool_response からメディアIDを取得
    response_output = ""
    tool_response = data.get("tool_response", {})
    if isinstance(tool_response, dict):
        response_output = tool_response.get("output", "") or tool_response.get("stdout", "") or str(tool_response)
    else:
        response_output = str(tool_response)

    # メディアIDは17桁前後の数字
    media_id_match = re.search(r"\b(\d{15,20})\b", response_output)
    media_id = media_id_match.group(1) if media_id_match else "不明"

    # 投稿テキストを取得（コマンドの引数から）
    text_match = re.search(r'post\.py\s+"(.*?)"', command, re.DOTALL)
    if not text_match:
        text_match = re.search(r"post\.py\s+'(.*?)'", command, re.DOTALL)
    post_text = text_match.group(1)[:50] + "..." if text_match else "（テキスト取得失敗）"

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # LINE通知
    message = f"🧵 Threads投稿完了！\n\n【投稿内容】{post_text}\n【メディアID】{media_id}\n【日時】{now}\n\n✅ Notion登録はClaudeが処理中"
    send_line(message)

    # Claudeへの追加コンテキストを返す（Notion登録を促す）
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": (
                f"Threads投稿が完了しました（メディアID: {media_id}）。"
                f"次のステップ: Notionの記事管理DB（data_source_id: af833b65-9f1d-4bc9-ac67-e833d05d16c6）に"
                f"この投稿を登録してください。タイトル・プラットフォーム(Threads)・ステータス(published)・投稿日({datetime.now().strftime('%Y-%m-%d')})を設定すること。"
            )
        }
    }
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
