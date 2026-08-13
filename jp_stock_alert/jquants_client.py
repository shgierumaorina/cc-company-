"""J-Quants API クライアント（第一候補データソース、日足のみ）
注意: JQUANTS_EMAIL/PASSWORD の実認証情報での動作確認はしていない（未検証）。
公開されているJ-Quants API v1の仕様（/token/auth_user → /token/auth_refresh → /prices/daily_quotes）
に基づいて実装したもので、実際のレスポンス形式が変わっている場合は失敗する可能性がある。
失敗時は例外をそのまま送出する（呼び出し側でyfinanceへフォールバックする）。
無料プランは日足のみでザラ場中のリアルタイム出来高は取得できないため、
当日の累積出来高はJ-Quantsの対象外（signal_detector側でyfinanceを使う）。
"""
import requests

BASE = "https://api.jquants.com/v1"


def get_id_token(email: str, password: str) -> str:
    resp = requests.post(f"{BASE}/token/auth_user",
                          json={"mailaddress": email, "password": password}, timeout=15)
    resp.raise_for_status()
    refresh_token = resp.json()["refreshToken"]

    resp = requests.post(f"{BASE}/token/auth_refresh",
                          params={"refreshtoken": refresh_token}, timeout=15)
    resp.raise_for_status()
    return resp.json()["idToken"]


def fetch_daily_quotes(code: str, id_token: str, from_date: str, to_date: str) -> list[dict]:
    """J-QuantsのコードはTSE4桁の末尾に0を付けた5桁形式を要求するため変換する。"""
    jq_code = f"{code}0" if len(code) == 4 else code
    resp = requests.get(
        f"{BASE}/prices/daily_quotes",
        params={"code": jq_code, "from": from_date, "to": to_date},
        headers={"Authorization": f"Bearer {id_token}"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("daily_quotes", [])
