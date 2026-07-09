"""算定エンジン（詳細設計書5.1）。

本番では共通算定モジュール（支払基金）へのAPI連携に差し替える。
Calculator を抽象IFとし、integration-svc 実装（CommonCalcModuleClient）が
製品版API公開後に追加される想定（詳細設計書 T-01）。
"""

from decimal import ROUND_HALF_UP, Decimal

YEN_PER_POINT = 10  # 1点=10円


def round_to_10yen(amount):
    """一部負担金の10円未満四捨五入（療担規則）。"""
    d = Decimal(amount)
    return int((d / 10).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * 10)


class Calculator:
    """算定エンジン抽象IF。"""

    def calculate(self, acts, ratio):
        """診療行為リストと負担割合から算定結果dictを返す。

        acts: medical_acts 行の列挙（points, quantity, master_code, name, act_type）
        ratio: 患者負担割合（例 0.3）
        戻り値: {total_points, total_amount, patient_burden, details}
        """
        raise NotImplementedError


class SimpleCalculator(Calculator):
    """共通算定モジュール接続までのスタブ実装。

    単純積算のみ（加算・逓減等の算定ルールは共通算定モジュール側の責務）。
    """

    def calculate(self, acts, ratio):
        details = []
        total_points = 0
        for act in acts:
            subtotal = act["points"] * act["quantity"]
            total_points += subtotal
            details.append({
                "act_type": act["act_type"],
                "master_code": act["master_code"],
                "name": act["name"],
                "points": act["points"],
                "quantity": act["quantity"],
                "subtotal_points": subtotal,
            })
        total_amount = total_points * YEN_PER_POINT
        burden_raw = Decimal(total_amount) * Decimal(str(ratio))
        patient_burden = round_to_10yen(burden_raw)
        return {
            "total_points": total_points,
            "total_amount": total_amount,
            "patient_burden": patient_burden,
            "details": details,
        }
