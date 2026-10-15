"""Unit tests for LifeVault privacy guardrails and data management tools.

Tests:
1. Sensitive-data filter unit tests:
   - Valid vs. invalid Luhn card numbers (13-19 digits).
   - Normal records: dates, amounts, phone models, serial-like short tokens, purchase IDs < 13 digits, bare 12 digits.
   - CVV, PIN, password, OTP phrasing.
   - Bank accounts and IBAN patterns.
   - SSN, Aadhaar (grouped or keyword-based), and passport patterns.
   - Verifies sensitive values are never echoed, logged, or included in outputs.
2. Server integration:
   - add_record rejects sensitive inputs in name, vendor, notes, renewal_cycle without writing to storage.
   - add_record_from_text intercepts sensitive input before external AI call.
   - renew_record rejects sensitive inputs.
3. export_my_data tool:
   - Formats records as concise JSON.
   - Caps output at 100 records and adds overflow indicator for > 100.
4. delete_all_data tool:
   - First call without confirm returns confirmation question.
   - Second call with confirm=True deletes records without dropping table.
5. SqliteStorage.clear_all and seed.py compatibility:
   - Table schema is preserved (DELETE FROM records instead of DROP TABLE).
"""

from datetime import date, timedelta
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

# Ensure server module is discoverable
server_dir = Path(__file__).resolve().parent.parent / "server"
if str(server_dir) not in sys.path:
    sys.path.insert(0, str(server_dir))

from privacy import is_sensitive, check_sensitive_data, is_luhn_valid, PRIVACY_REJECTION_MESSAGE
from storage import SqliteStorage
import server
from server import add_record, add_record_from_text, renew_record, export_my_data, delete_all_data
from seed import seed_database


class TestSensitiveDataFilter(unittest.TestCase):
    """Test suite for privacy guardrails regex and Luhn validator."""

    def test_luhn_validator(self):
        # Known valid card numbers
        self.assertTrue(is_luhn_valid("4111111111111111"))
        self.assertTrue(is_luhn_valid("378282246310005"))
        # Known invalid card numbers (checksum mismatch)
        self.assertFalse(is_luhn_valid("4111111111111112"))
        self.assertFalse(is_luhn_valid("1234567890123456"))
        # Invalid lengths (< 13 or > 19)
        self.assertFalse(is_luhn_valid("123456789012"))
        self.assertFalse(is_luhn_valid("12345678901234567890"))

    def test_card_numbers_detected_only_when_luhn_valid(self):
        # Valid Luhn card with spaces / hyphens / raw
        self.assertTrue(is_sensitive("My card number is 4111 1111 1111 1111"))
        self.assertTrue(is_sensitive("Card: 4111-1111-1111-1111"))
        self.assertTrue(is_sensitive("Payment 4111111111111111"))
        self.assertTrue(is_sensitive("Amex 3782-822463-10005"))

        # Invalid Luhn 16-digit run must NOT be blocked under card rule
        self.assertFalse(is_sensitive("Reference code 4111111111111112"))
        self.assertFalse(is_sensitive("Order tracking 4111-1111-1111-1112"))

    def test_normal_records_accepted(self):
        # Dates (YYYY-MM-DD)
        self.assertFalse(is_sensitive("Expires on 2026-10-16"))
        self.assertFalse(is_sensitive("Purchased on 2024-01-01"))

        # Amounts
        self.assertFalse(is_sensitive("Paid $249 for headphones"))
        self.assertFalse(is_sensitive("Amount is 1200.50 dollars"))

        # Phone-model numbers
        self.assertFalse(is_sensitive("iPhone 15 Pro Max warranty"))
        self.assertFalse(is_sensitive("Google Pixel 8 phone"))
        self.assertFalse(is_sensitive("Samsung Galaxy S24 Ultra"))

        # Short serial-like tokens
        self.assertFalse(is_sensitive("Serial number SN-123456"))
        self.assertFalse(is_sensitive("Model AB12CD34"))

        # Purchase IDs under 13 digits
        self.assertFalse(is_sensitive("Order #987654321"))
        self.assertFalse(is_sensitive("Receipt 1234567890"))

        # Bare 12-digit runs without Aadhaar keyword or 4-4-4 grouping
        self.assertFalse(is_sensitive("Item code 123456789012"))

        # Legitimate document terms
        self.assertFalse(is_sensitive("US Passport"))
        self.assertFalse(is_sensitive("10-year adult passport renewal"))
        self.assertFalse(is_sensitive("California Driver License"))

        # Pin words that are not security PINs
        self.assertFalse(is_sensitive("Safety pin pack"))
        self.assertFalse(is_sensitive("Bowling pin set"))

    def test_cvv_pin_password_otp_detected(self):
        # CVV / CVC
        self.assertTrue(is_sensitive("My card cvv is 123"))
        self.assertTrue(is_sensitive("cvv: 456"))
        self.assertTrue(is_sensitive("Security code 789"))

        # PIN
        self.assertTrue(is_sensitive("My pin is 1234"))
        self.assertTrue(is_sensitive("pin: 5678"))
        self.assertTrue(is_sensitive("ATM pin 9999"))
        self.assertTrue(is_sensitive("card pin: 4321"))
        self.assertTrue(is_sensitive("pin code 1122"))

        # Passwords
        self.assertTrue(is_sensitive("The password is secret"))
        self.assertTrue(is_sensitive("Router password: admin123"))
        self.assertTrue(is_sensitive("Passcode 123456"))
        self.assertTrue(is_sensitive("pwd: supersecret"))

        # OTP
        self.assertTrue(is_sensitive("My OTP is 987654"))
        self.assertTrue(is_sensitive("One-time password: 123456"))
        self.assertTrue(is_sensitive("Verification code 654321"))

    def test_bank_and_iban_detected(self):
        # IBAN formats
        self.assertTrue(is_sensitive("IBAN GB29NWBK60161331926819"))
        self.assertTrue(is_sensitive("GB29 NWBK 6016 1331 9268 19"))

        # Bank account phrasing
        self.assertTrue(is_sensitive("Bank account 123456789"))
        self.assertTrue(is_sensitive("Account number: 9876543210"))
        self.assertTrue(is_sensitive("Acct no 555666777"))
        self.assertTrue(is_sensitive("Checking account 1122334455"))
        self.assertTrue(is_sensitive("Routing number 123456789"))

    def test_government_ids_detected(self):
        # SSN
        self.assertTrue(is_sensitive("SSN: 123-45-6789"))
        self.assertTrue(is_sensitive("123-45-6789"))
        self.assertTrue(is_sensitive("Social security number 123456789"))

        # Aadhaar: 4-4-4 grouped format
        self.assertTrue(is_sensitive("1234 5678 9012"))
        self.assertTrue(is_sensitive("1234-5678-9012"))

        # Aadhaar: with keyword
        self.assertTrue(is_sensitive("Aadhaar: 123456789012"))
        self.assertTrue(is_sensitive("My aadhaar card"))

        # Passport: only with adjacent keyword / ID
        self.assertTrue(is_sensitive("Passport number A12345678"))
        self.assertTrue(is_sensitive("Passport: 98765432"))
        self.assertTrue(is_sensitive("Passport A12345678"))

        # General ID numbers
        self.assertTrue(is_sensitive("ID number: AB987654"))
        self.assertTrue(is_sensitive("National ID: 123456789"))

    def test_friendly_sentence_response(self):
        res = check_sensitive_data("My card is 4111 1111 1111 1111")
        self.assertEqual(res, PRIVACY_REJECTION_MESSAGE)
        self.assertEqual(
            res,
            "I can't store card numbers, passwords or ID numbers. Tell me just the item and dates.",
        )


class TestServerPrivacyGuardrails(unittest.TestCase):
    """Test privacy enforcement at the server MCP tool boundaries."""

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.temp_db_path = str(Path(cls.temp_dir.name) / "test_privacy_server.db")
        cls.test_storage = SqliteStorage(db_path=cls.temp_db_path)
        cls.orig_storage = server.storage
        server.storage = cls.test_storage

    @classmethod
    def tearDownClass(cls):
        server.storage = cls.orig_storage
        cls.temp_dir.cleanup()

    def setUp(self):
        self.test_storage.clear_all()

    def test_add_record_rejects_sensitive_name(self):
        res = add_record(
            type="warranty",
            name="Card 4111 1111 1111 1111",
            amount=50.0,
        )
        self.assertEqual(res, PRIVACY_REJECTION_MESSAGE)
        self.assertEqual(len(self.test_storage.list_records()), 0)

    def test_add_record_rejects_sensitive_notes(self):
        res = add_record(
            type="subscription",
            name="Netflix",
            notes="My password is secret123",
        )
        self.assertEqual(res, PRIVACY_REJECTION_MESSAGE)
        self.assertEqual(len(self.test_storage.list_records()), 0)

    def test_add_record_rejects_sensitive_vendor(self):
        res = add_record(
            type="bill",
            name="Electricity",
            vendor="Bank account 1234567890",
        )
        self.assertEqual(res, PRIVACY_REJECTION_MESSAGE)
        self.assertEqual(len(self.test_storage.list_records()), 0)

    def test_add_record_accepts_clean_record(self):
        res = add_record(
            type="warranty",
            name="MacBook Pro",
            vendor="Apple",
            amount=1999.0,
            notes="Receipt in drawer",
        )
        self.assertIn("Saved MacBook Pro", res)
        self.assertEqual(len(self.test_storage.list_records()), 1)

    @patch("server.extract_record")
    def test_add_record_from_text_rejects_before_ai_call(self, mock_extract):
        res = add_record_from_text("Save my card 4111 1111 1111 1111 expiring next month")
        self.assertEqual(res, PRIVACY_REJECTION_MESSAGE)
        # Verify AI extractor was never called!
        mock_extract.assert_not_called()
        self.assertEqual(len(self.test_storage.list_records()), 0)

    def test_renew_record_rejects_sensitive_name(self):
        # First add a valid record
        add_record(type="subscription", name="Spotify Family", amount=16.99)
        # Attempt to renew with sensitive input
        res = renew_record(name="Spotify password is secret", extend_months=12)
        self.assertEqual(res, PRIVACY_REJECTION_MESSAGE)


class TestDataExportAndDeletionTools(unittest.TestCase):
    """Test export_my_data and two-step delete_all_data tools."""

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.temp_db_path = str(Path(cls.temp_dir.name) / "test_data_tools.db")
        cls.test_storage = SqliteStorage(db_path=cls.temp_db_path)
        cls.orig_storage = server.storage
        server.storage = cls.test_storage

    @classmethod
    def tearDownClass(cls):
        server.storage = cls.orig_storage
        cls.temp_dir.cleanup()

    def setUp(self):
        self.test_storage.clear_all()

    def test_export_empty_data(self):
        res = export_my_data()
        self.assertEqual(res, "You have no records stored in LifeVault.")

    def test_export_stored_records_concise_json(self):
        add_record(type="warranty", name="MacBook Pro", amount=1999.0)
        add_record(type="subscription", name="Netflix", amount=15.99)

        res = export_my_data()
        data = json.loads(res)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 2)
        names = {item["name"] for item in data}
        self.assertEqual(names, {"MacBook Pro", "Netflix"})

    def test_export_caps_at_100_records(self):
        # Insert 105 mock records directly
        today = date.today().isoformat()
        for i in range(105):
            self.test_storage.add_record({
                "type": "bill",
                "name": f"Utility Bill {i}",
                "amount": 50.0,
                "purchase_date": today,
            })

        res = export_my_data()
        self.assertIn("... and 5 more records.", res)
        # The JSON part before the ellipsis should have 100 items
        json_part = res.split("\n\n... and 5 more records.")[0]
        data = json.loads(json_part)
        self.assertEqual(len(data), 100)

    def test_delete_all_data_two_step_confirmation(self):
        add_record(type="warranty", name="iPad Air", amount=599.0)
        self.assertEqual(len(self.test_storage.list_records()), 1)

        # Step 1: Call without confirm=True
        first_call = delete_all_data(confirm=False)
        self.assertIn("Are you sure you want to delete all your records?", first_call)
        self.assertIn("Please confirm to proceed.", first_call)
        # Ensure data is still preserved!
        self.assertEqual(len(self.test_storage.list_records()), 1)

        # Step 2: Call with confirm=True
        confirmed_call = delete_all_data(confirm=True)
        self.assertEqual(confirmed_call, "All your records have been permanently deleted.")
        self.assertEqual(len(self.test_storage.list_records()), 0)

        # Step 3: Verify table is not dropped (subsequent add succeeds)
        add_res = add_record(type="bill", name="Water Bill", amount=35.0)
        self.assertIn("Saved Water Bill", add_res)
        self.assertEqual(len(self.test_storage.list_records()), 1)


class TestSqliteClearAllPreservesTable(unittest.TestCase):
    """Test SqliteStorage.clear_all preserves table structure and works with seed.py."""

    def setUp(self):
        self.temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_file.close()
        self.storage = SqliteStorage(db_path=self.temp_file.name)

    def tearDown(self):
        try:
            os.unlink(self.temp_file.name)
        except OSError:
            pass

    def test_clear_all_uses_delete_from_and_table_remains(self):
        self.storage.add_record({"type": "bill", "name": "Power Bill", "amount": 100.0})
        self.assertEqual(len(self.storage.list_records()), 1)

        # clear_all must not drop table
        self.storage.clear_all()
        self.assertEqual(len(self.storage.list_records()), 0)

        # Can immediately query without re-init
        with self.storage._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT count(*) FROM records")
            count = cursor.fetchone()[0]
            self.assertEqual(count, 0)

    def test_seed_database_works_seamlessly(self):
        seed_database(storage_instance=self.storage)
        records = self.storage.list_records()
        self.assertGreater(len(records), 10)


if __name__ == "__main__":
    unittest.main()
