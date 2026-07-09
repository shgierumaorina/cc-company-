"""レセコンMVP コア業務フローのテスト。

実行: rececon/ ディレクトリで `python -m unittest discover tests -v`
"""

import unittest

from rececon import audit, billing, db, encounter, patient, receipt
from rececon.calculator import SimpleCalculator, round_to_10yen
from rececon.errors import BillingError, DuplicateError, ValidationError

ACTOR = "test-user"


def setup_patient(conn, patient_no="0000001", with_insurance=True):
    patient_id, _ = patient.register_patient(
        conn, ACTOR, patient_no, "検証 太郎", "ケンショウ タロウ",
        "1980-05-05", "1")
    if with_insurance:
        patient.add_insurance(
            conn, ACTOR, patient_id, "01130012", "あ", "1234567",
            0.3, "2026-01-01")
    return patient_id


class PatientTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")

    def test_register_and_search(self):
        patient_id = setup_patient(self.conn)
        results = patient.search_patients(self.conn, "0000001")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], patient_id)
        results = patient.search_patients(self.conn, "ケンショウ")
        self.assertEqual(len(results), 1)

    def test_duplicate_patient_no_rejected(self):
        setup_patient(self.conn)
        with self.assertRaises(DuplicateError):
            setup_patient(self.conn, patient_no="0000001")

    def test_similar_patient_detected(self):
        setup_patient(self.conn, patient_no="0000001")
        _, similar = patient.register_patient(
            self.conn, ACTOR, "0000002", "検証 太郎", "ケンショウ タロウ",
            "1980-05-05", "1")
        self.assertEqual(len(similar), 1)

    def test_invalid_input_rejected(self):
        with self.assertRaises(ValidationError):
            patient.register_patient(
                self.conn, ACTOR, "0000003", "検証 花子",
                "ケンショウ ハナコ", "1980/05/05", "2")
        with self.assertRaises(ValidationError):
            patient.register_patient(
                self.conn, ACTOR, "0000003", "検証 花子",
                "ケンショウ ハナコ", "1980-05-05", "F")

    def test_insurance_validity_period(self):
        patient_id = setup_patient(self.conn, with_insurance=False)
        patient.add_insurance(
            self.conn, ACTOR, patient_id, "01130012", None, "111",
            0.3, "2026-01-01", "2026-03-31")
        self.assertIsNotNone(
            patient.get_valid_insurance(self.conn, patient_id, "2026-02-15"))
        self.assertIsNone(
            patient.get_valid_insurance(self.conn, patient_id, "2026-04-01"))
        self.assertIsNone(
            patient.get_valid_insurance(self.conn, patient_id, "2025-12-31"))


class EncounterTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.patient_id = setup_patient(self.conn)

    def test_idempotent_import_by_source_ref(self):
        enc_id = encounter.create_encounter(
            self.conn, ACTOR, self.patient_id, "2026-06-01", "01")
        act_id1, created1 = encounter.add_act(
            self.conn, ACTOR, enc_id, "11", "111000110", "初診料", 291,
            source="ehr", source_ref="ORD-001")
        act_id2, created2 = encounter.add_act(
            self.conn, ACTOR, enc_id, "11", "111000110", "初診料", 291,
            source="ehr", source_ref="ORD-001")
        self.assertTrue(created1)
        self.assertFalse(created2)
        self.assertEqual(act_id1, act_id2)
        self.assertEqual(len(encounter.list_acts(self.conn, enc_id)), 1)

    def test_close_requires_acts(self):
        enc_id = encounter.create_encounter(
            self.conn, ACTOR, self.patient_id, "2026-06-01", "01")
        with self.assertRaises(BillingError):
            encounter.close_encounter(self.conn, ACTOR, enc_id)

    def test_no_act_after_close(self):
        enc_id = encounter.create_encounter(
            self.conn, ACTOR, self.patient_id, "2026-06-01", "01")
        encounter.add_act(self.conn, ACTOR, enc_id, "12", "112007410",
                          "再診料", 75)
        encounter.close_encounter(self.conn, ACTOR, enc_id)
        with self.assertRaises(BillingError):
            encounter.add_act(self.conn, ACTOR, enc_id, "40", "140000610",
                              "創傷処置", 45)


class CalculatorTest(unittest.TestCase):
    def test_round_to_10yen(self):
        self.assertEqual(round_to_10yen(384), 380)   # 38.4 -> 38
        self.assertEqual(round_to_10yen(385), 390)   # 38.5 -> 39 (HALF_UP)
        self.assertEqual(round_to_10yen(1143), 1140)
        self.assertEqual(round_to_10yen(0), 0)

    def test_simple_calculation(self):
        acts = [
            {"act_type": "11", "master_code": "111000110",
             "name": "初診料", "points": 291, "quantity": 1},
            {"act_type": "40", "master_code": "140000610",
             "name": "創傷処置", "points": 45, "quantity": 2},
        ]
        result = SimpleCalculator().calculate(acts, 0.3)
        self.assertEqual(result["total_points"], 381)
        self.assertEqual(result["total_amount"], 3810)
        # 3810 * 0.3 = 1143 -> 1140円（10円未満四捨五入）
        self.assertEqual(result["patient_burden"], 1140)
        self.assertEqual(len(result["details"]), 2)


class BillingTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.patient_id = setup_patient(self.conn)
        self.enc_id = encounter.create_encounter(
            self.conn, ACTOR, self.patient_id, "2026-06-15", "01")
        encounter.add_act(self.conn, ACTOR, self.enc_id, "11", "111000110",
                          "初診料", 291)

    def test_calculation_requires_closed(self):
        with self.assertRaises(BillingError):
            billing.run_calculation(self.conn, ACTOR, self.enc_id)

    def test_calculation_and_payment(self):
        encounter.close_encounter(self.conn, ACTOR, self.enc_id)
        calc = billing.run_calculation(self.conn, ACTOR, self.enc_id)
        self.assertEqual(calc["total_points"], 291)
        self.assertEqual(calc["patient_burden"], 870)  # 2910*0.3=873 -> 870
        payment = billing.confirm_payment(
            self.conn, ACTOR, self.enc_id, 870)
        self.assertEqual(payment["receipt_no"], "00000001")

    def test_payment_amount_mismatch_rejected(self):
        encounter.close_encounter(self.conn, ACTOR, self.enc_id)
        billing.run_calculation(self.conn, ACTOR, self.enc_id)
        with self.assertRaises(BillingError):
            billing.confirm_payment(self.conn, ACTOR, self.enc_id, 999)

    def test_recalculation_supersedes(self):
        encounter.close_encounter(self.conn, ACTOR, self.enc_id)
        first = billing.run_calculation(self.conn, ACTOR, self.enc_id)
        second = billing.run_calculation(self.conn, ACTOR, self.enc_id)
        self.assertNotEqual(first["id"], second["id"])
        rows = self.conn.execute(
            "SELECT status FROM calculations WHERE encounter_id = ? "
            "ORDER BY calculated_at",
            (self.enc_id,),
        ).fetchall()
        statuses = [r["status"] for r in rows]
        self.assertEqual(statuses.count("calculated"), 1)
        self.assertEqual(statuses.count("superseded"), 1)

    def test_calculation_requires_valid_insurance(self):
        pid2 = setup_patient(self.conn, "0000009", with_insurance=False)
        enc2 = encounter.create_encounter(
            self.conn, ACTOR, pid2, "2026-06-15", "01")
        encounter.add_act(self.conn, ACTOR, enc2, "12", "112007410",
                          "再診料", 75)
        encounter.close_encounter(self.conn, ACTOR, enc2)
        with self.assertRaises(BillingError):
            billing.run_calculation(self.conn, ACTOR, enc2)


