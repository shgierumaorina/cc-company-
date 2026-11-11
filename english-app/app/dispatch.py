"""「準備する」を押した直後に、GitHub Actions の文字起こしを起動する。

環境変数 GITHUB_DISPATCH_TOKEN（Actions: Read and write 権限のトークン）がある時だけ動く。
なければ何もせず、30分ごとの定期実行に任せる。
"""
import json
import os
import urllib.error
import urllib.request

WORKFLOW = "english-prepare.yml"


def trigger(mode="queue"):
    """起動できたら True。トークン未設定や失敗時は False（理由は戻り値の2つ目）。"""
    token = os.environ.get("GITHUB_DISPATCH_TOKEN", "").strip()
    if not token:
        return False, "no-token"
    repo = os.environ.get("GITHUB_REPO", "shgierumaorina/cc-company-").strip()
    url = f"https://api.github.com/repos/{repo}/actions/workflows/{WORKFLOW}/dispatches"
    body = json.dumps({"ref": os.environ.get("GITHUB_REF_NAME", "main"), "inputs": {"mode": mode}})
    req = urllib.request.Request(url, data=body.encode("utf-8"), method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "ListeningLab")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status == 204, f"HTTP {r.status}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}"
    except urllib.error.URLError as e:
        return False, f"接続エラー: {e.reason}"
    except Exception as e:  # noqa: BLE001  タイムアウト等でも画面の操作は止めない
        return False, f"{type(e).__name__}: {e}"
