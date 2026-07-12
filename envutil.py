"""シークレット読み込み共通ヘルパー
環境変数 → リポジトリ直下の .env の順で探す。
.env は gitignore 対象（コミット禁止）。
"""
import os
from pathlib import Path

_ENV_FILE = Path(__file__).resolve().parent / ".env"


def get_secret(name: str, default: str = "") -> str:
    v = os.environ.get(name)
    if v:
        return v
    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip()
    return default
