"""業務例外定義（詳細設計書8.2 エラーハンドリング共通方針）。"""


class RececonError(Exception):
    """業務エラー基底。"""


class ValidationError(RececonError):
    """入力検証エラー（HTTP 400相当）。"""


class NotFoundError(RececonError):
    """対象リソースなし（HTTP 404相当）。"""


class DuplicateError(RececonError):
    """一意制約違反・二重登録（HTTP 409相当）。"""


class BillingError(RececonError):
    """算定・会計の業務ルール違反（HTTP 422相当）。"""
