"""エンドツーエンドのデモシナリオ。

実行: rececon/ ディレクトリで `python -m rececon.demo`
受付→診療行為→算定→会計→月次レセプト生成の一連の流れを実演する。
"""

from . import audit, billing, db, encounter, patient, receipt

ACTOR = "demo-clerk"


def main():
    conn = db.connect(":memory:")

    print("=== 1. 患者登録 ===")
    patient_id, similar = patient.register_patient(
        conn, ACTOR, "0001234", "東京 太郎", "トウキョウ タロウ",
        "1990-01-01", "1")
    print(f"患者ID: {patient_id}（類似患者: {len(similar)}件）")

    print("\n=== 2. 保険資格登録 ===")
    patient.add_insurance(
        conn, ACTOR, patient_id, "01130012", "あ12", "3456789",
        0.3, "2026-04-01")
    print("保険者番号=01130012 負担割合=3割")

    print("\n=== 3. 診療イベント・診療行為 ===")
    enc_id = encounter.create_encounter(
        conn, ACTOR, patient_id, "2026-06-15", "01")
    encounter.add_act(conn, ACTOR, enc_id, "11", "111000110",
                      "初診料", 291, 1)
    encounter.add_act(conn, ACTOR, enc_id, "40", "140000610",
                      "創傷処置", 45, 2)
    encounter.close_encounter(conn, ACTOR, enc_id)
    print("初診料291点 + 創傷処置45点×2 を登録して確定")

    print("\n=== 4. 算定・会計 ===")
    calc = billing.run_calculation(conn, ACTOR, enc_id)
    print(f"総点数: {calc['total_points']}点 / "
          f"医療費: {calc['total_amount']}円 / "
          f"患者負担: {calc['patient_burden']}円")
    payment = billing.confirm_payment(
        conn, ACTOR, enc_id, calc["patient_burden"])
    print(f"収納完了 領収書番号: {payment['receipt_no']}")

    print("\n=== 5. 月次レセプト生成（2026年6月分） ===")
    results = receipt.generate_monthly_receipts(conn, ACTOR, "202606")
    for r in results:
        print(f"患者 {r['patient_id'][:8]}...: {r['status']}")

    print("\n=== 6. UKE出力（簡易形式） ===")
    print(receipt.export_uke(conn, "202606"))

    print("\n=== 7. 監査ログ ===")
    for log in audit.search(conn, patient_id=patient_id):
        print(f"{log['at']} {log['actor']} {log['action']} "
              f"{log['resource_type']} {log['detail']}")


if __name__ == "__main__":
    main()
