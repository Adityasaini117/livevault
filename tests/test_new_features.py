"""Unit tests for LifeVault new features.

Tests:
1. Bill anomaly detection (thresholds: exactly 2 vs 3 earlier bills, > 25% spike, normal variation).
2. Renew date math (YYYY-MM-DD validation, future date check, month extension, cycle extension, reminder date calculation).
3. Warranty claim template (data mapping, placeholders, expired notice, legal disclaimer).
4. Access protection ASGI middleware (constant-time token check, 401 response on missing/wrong token, pass-through on valid token).

Uses a temporary SQLite database to avoid modifying any real data.
"""

from datetime import date, timedelta
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

# Ensure server module is discoverable
server_dir = Path(__file__).resolve().parent.parent / "server"
if str(server_dir) not in sys.path:
    sys.path.insert(0, str(server_dir))

from storage import SqliteStorage
import server
from server import (
    ApiTokenAuthMiddleware,
    _detect_bill_anomalies,
    bill_anomalies,
    draft_warranty_claim,
    morning_brief,
    renew_record,
)


class TestNewFeatures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Create an isolated temporary SQLite database
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.temp_db_path = str(Path(cls.temp_dir.name) / "test_lifevault.db")
        cls.test_storage = SqliteStorage(db_path=cls.temp_db_path)
        # Point server.storage to isolated test database
        cls.orig_storage = server.storage
        server.storage = cls.test_storage

    @classmethod
    def tearDownClass(cls):
        server.storage = cls.orig_storage
        cls.temp_dir.cleanup()

    def setUp(self):
        # Reset database tables before each test
        self.test_storage.init_db(drop_existing=True)

    # -------------------------------------------------------------------------
    # 1. BILL ANOMALIES & THRESHOLD TESTS
    # -------------------------------------------------------------------------

    def test_bill_anomalies_insufficient_history_exactly_2_earlier(self):
        """A series with exactly 2 earlier bills + 1 latest (3 total) must NOT flag an anomaly."""
        today = date.today()
        # 2 earlier bills
        self.test_storage.add_record({
            "type": "bill",
            "name": "Electric Utility Bill",
            "amount": 100.00,
            "purchase_date": (today - timedelta(days=60)).isoformat(),
        })
        self.test_storage.add_record({
            "type": "bill",
            "name": "Electric Utility Bill",
            "amount": 100.00,
            "purchase_date": (today - timedelta(days=30)).isoformat(),
        })
        # 1 latest bill with 100% spike
        self.test_storage.add_record({
            "type": "bill",
            "name": "Electric Utility Bill",
            "amount": 200.00,
            "purchase_date": today.isoformat(),
        })

        # When queried specifically by name, says not enough history
        res_named = bill_anomalies("Electric Utility Bill")
        self.assertIn("not enough billing history", res_named.lower())

        # When queried without name, no anomaly is flagged
        res_all = bill_anomalies()
        self.assertEqual(res_all, "No unusual bill amounts detected.")

    def test_bill_anomalies_flag_allowed_with_exactly_3_earlier(self):
        """A series with exactly 3 earlier bills + 1 latest (4 total) CAN flag an anomaly if > 25% above median."""
        today = date.today()
        # 3 earlier bills: median is 100.00
        for days_ago, amt in [(90, 100.00), (60, 105.00), (30, 95.00)]:
            self.test_storage.add_record({
                "type": "bill",
                "name": "Electric Utility Bill",
                "amount": amt,
                "purchase_date": (today - timedelta(days=days_ago)).isoformat(),
            })
        # Latest bill: 140.00 (40% above median of 100)
        self.test_storage.add_record({
            "type": "bill",
            "name": "Electric Utility Bill",
            "amount": 140.00,
            "purchase_date": today.isoformat(),
        })

        res_named = bill_anomalies("Electric Utility Bill")
        self.assertIn("40 percent higher than usual", res_named)
        self.assertIn("140 dollars against about 100", res_named)

        res_all = bill_anomalies()
        self.assertIn("40 percent higher than usual", res_all)

    def test_bill_anomalies_normal_variation_not_flagged(self):
        """A series with 3 earlier bills and a normal variation latest bill (<= 25%) is not flagged."""
        today = date.today()
        for days_ago, amt in [(90, 80.00), (60, 81.00), (30, 79.00)]:
            self.test_storage.add_record({
                "type": "bill",
                "name": "Internet Bill",
                "amount": amt,
                "purchase_date": (today - timedelta(days=days_ago)).isoformat(),
            })
        # Latest bill: 85.00 (6.25% above median of 80 -> below 25% threshold)
        self.test_storage.add_record({
            "type": "bill",
            "name": "Internet Bill",
            "amount": 85.00,
            "purchase_date": today.isoformat(),
        })

        res = bill_anomalies("Internet Bill")
        self.assertEqual(res, "No unusual bill amounts detected for Internet Bill.")

    # -------------------------------------------------------------------------
    # 2. RENEW DATE MATH TESTS
    # -------------------------------------------------------------------------

    def test_renew_record_validation(self):
        """Validates record lookup and new_expiry_date constraints."""
        today = date.today()
        self.test_storage.add_record({
            "type": "subscription",
            "name": "Gym Pass",
            "expiry_date": (today + timedelta(days=10)).isoformat(),
            "reminder_date": (today - timedelta(days=20)).isoformat(),
        })

        # Nonexistent record
        self.assertIn("couldn't find any records", renew_record("Nonexistent"))

        # Invalid date format
        res_bad_fmt = renew_record("Gym Pass", new_expiry_date="invalid-date")
        self.assertIn("YYYY-MM-DD", res_bad_fmt)

        # Date in past or today
        past_date = (today - timedelta(days=2)).isoformat()
        res_past = renew_record("Gym Pass", new_expiry_date=past_date)
        self.assertIn("must be after today", res_past)

    def test_renew_record_new_expiry_date(self):
        """Sets new expiry date directly and updates reminder date to 30 days prior."""
        today = date.today()
        target_expiry = today + timedelta(days=60)
        self.test_storage.add_record({
            "type": "subscription",
            "name": "Gym Pass",
            "amount": 50.00,
            "expiry_date": (today + timedelta(days=10)).isoformat(),
            "reminder_date": (today - timedelta(days=20)).isoformat(),
        })

        res = renew_record("Gym Pass", new_expiry_date=target_expiry.isoformat(), amount=55.00)
        expected_reminder = target_expiry - timedelta(days=30)
        self.assertIn(f"new expiry is {target_expiry.isoformat()}", res)
        self.assertIn(f"reminder is set for {expected_reminder.isoformat()}", res)

        # Check updated record in storage
        matches = self.test_storage.search_records("Gym Pass")
        self.assertEqual(matches[0]["expiry_date"], target_expiry.isoformat())
        self.assertEqual(matches[0]["reminder_date"], expected_reminder.isoformat())
        self.assertEqual(matches[0]["amount"], 55.00)

    def test_renew_record_extend_months_active_and_expired(self):
        """Adds extend_months to current expiry if active, or to today if expired."""
        today = date.today()

        # Active record
        active_expiry = today + timedelta(days=40)
        self.test_storage.add_record({
            "type": "subscription",
            "name": "Active Stream",
            "expiry_date": active_expiry.isoformat(),
        })
        res_active = renew_record("Active Stream", extend_months=3)
        self.assertIn("Renewed Active Stream", res_active)

        # Expired record: base date should be today
        expired_date = today - timedelta(days=20)
        self.test_storage.add_record({
            "type": "subscription",
            "name": "Old Magazine",
            "expiry_date": expired_date.isoformat(),
        })
        res_expired = renew_record("Old Magazine", extend_months=2)
        self.assertIn("Renewed Old Magazine", res_expired)
        # Expected new expiry is today + 2 months
        from server import _add_months
        expected_new = _add_months(today, 2).isoformat()
        self.assertIn(f"new expiry is {expected_new}", res_expired)

    def test_renew_record_renewal_cycle_and_unspecified(self):
        """Renews by renewal_cycle if present, otherwise asks how long to renew for."""
        today = date.today()
        self.test_storage.add_record({
            "type": "subscription",
            "name": "Cloud Storage",
            "expiry_date": (today + timedelta(days=10)).isoformat(),
            "renewal_cycle": "monthly",
        })
        res_cycle = renew_record("Cloud Storage")
        self.assertIn("Renewed Cloud Storage", res_cycle)

        self.test_storage.add_record({
            "type": "subscription",
            "name": "Custom Membership",
            "expiry_date": (today + timedelta(days=10)).isoformat(),
            "renewal_cycle": None,
        })
        res_ask = renew_record("Custom Membership")
        self.assertIn("How long would you like to renew Custom Membership for?", res_ask)

    # -------------------------------------------------------------------------
    # 3. WARRANTY CLAIM TEMPLATE TESTS
    # -------------------------------------------------------------------------

    def test_draft_warranty_claim_active(self):
        """Generates email draft with stored details and placeholders, no expired notice."""
        today = date.today()
        expiry = today + timedelta(days=90)
        self.test_storage.add_record({
            "type": "warranty",
            "name": "Espresso Machine",
            "vendor": "Breville",
            "amount": 699.95,
            "purchase_date": (today - timedelta(days=275)).isoformat(),
            "expiry_date": expiry.isoformat(),
        })

        draft = draft_warranty_claim("Espresso Machine")
        self.assertIn("Subject: Warranty Claim - Espresso Machine", draft)
        self.assertIn("Dear Breville Support Team,", draft)
        self.assertIn("$699.95", draft)
        self.assertIn(expiry.isoformat(), draft)
        self.assertIn("[describe the problem]", draft)
        self.assertIn("[your name]", draft)
        self.assertIn("Note: This is a draft and not legal advice.", draft)
        self.assertNotIn("Notice: The warranty for Espresso Machine expired", draft)

    def test_draft_warranty_claim_expired(self):
        """When warranty has expired, prepends clear notice at top while still returning draft."""
        today = date.today()
        expired_date = today - timedelta(days=15)
        self.test_storage.add_record({
            "type": "warranty",
            "name": "Coffee Grinder",
            "vendor": "Baratza",
            "amount": 199.00,
            "purchase_date": (today - timedelta(days=380)).isoformat(),
            "expiry_date": expired_date.isoformat(),
        })

        draft = draft_warranty_claim("Coffee Grinder")
        self.assertTrue(draft.startswith(f"Notice: The warranty for Coffee Grinder expired on {expired_date.isoformat()}."))
        self.assertIn("Subject: Warranty Claim - Coffee Grinder", draft)
        self.assertIn("Note: This is a draft and not legal advice.", draft)

    # -------------------------------------------------------------------------
    # 4. MORNING BRIEF TESTS
    # -------------------------------------------------------------------------

    def test_morning_brief_aggregation(self):
        """Aggregates items due in 7 days, expired in 14 days, and bill anomalies."""
        today = date.today()
        # Due in 3 days
        self.test_storage.add_record({
            "type": "subscription",
            "name": "Gym Auto-Renew",
            "expiry_date": (today + timedelta(days=3)).isoformat(),
        })
        # Expired 5 days ago
        self.test_storage.add_record({
            "type": "document",
            "name": "Parking Permit",
            "expiry_date": (today - timedelta(days=5)).isoformat(),
        })

        brief = morning_brief()
        self.assertIn("Gym Auto-Renew renews in 3 days", brief)
        self.assertIn("Parking Permit expired 5 days ago", brief)

    def test_morning_brief_spoken_wording_examples_and_cap(self):
        """Verifies specific natural spoken wording examples and the 5-item limit."""
        today = date.today()
        # 1. Equinox Gym renews in 4 days
        d_oct16 = today + timedelta(days=4)
        self.test_storage.add_record({
            "type": "subscription",
            "name": "Equinox Gym",
            "expiry_date": d_oct16.isoformat(),
        })
        # 2. Verizon Fios Internet expired 13 days ago
        d_past13 = today - timedelta(days=13)
        self.test_storage.add_record({
            "type": "document",
            "name": "Verizon Fios Internet",
            "expiry_date": d_past13.isoformat(),
        })
        # 3. Bill anomaly: City Electric (name doesn't contain bill -> appends bill)
        for days_ago, amt in [(120, 118.0), (90, 118.0), (60, 118.0)]:
            self.test_storage.add_record({
                "type": "bill",
                "name": "City Electric",
                "amount": amt,
                "purchase_date": (today - timedelta(days=days_ago)).isoformat(),
            })
        self.test_storage.add_record({
            "type": "bill",
            "name": "City Electric",
            "amount": 168.0,
            "purchase_date": today.isoformat(),
        })

        brief = morning_brief()
        from server import _spoken_date
        self.assertIn(f"Equinox Gym renews in 4 days, on {_spoken_date(d_oct16)}", brief)
        self.assertIn(f"Verizon Fios Internet expired 13 days ago, on {_spoken_date(d_past13)}", brief)
        self.assertIn("Your City Electric bill is 42 percent higher than usual: 168 dollars against about 118.", brief)

        # Add more items to exceed 5 items
        for i in range(4):
            self.test_storage.add_record({
                "type": "subscription",
                "name": f"Extra Sub {i}",
                "expiry_date": (today + timedelta(days=2)).isoformat(),
            })

        brief_capped = morning_brief()
        self.assertIn("and 2 more.", brief_capped)

    # -------------------------------------------------------------------------
    # 5. ACCESS PROTECTION (ASGI MIDDLEWARE) TESTS
    # -------------------------------------------------------------------------

    def test_auth_middleware_disabled_when_token_unset(self):
        """Allows requests without auth when expected_token is None or blank."""
        import asyncio

        async def dummy_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"OK", "more_body": False})

        middleware = ApiTokenAuthMiddleware(dummy_app, expected_token=None)

        events = []
        async def send(event):
            events.append(event)
        async def receive():
            return {"type": "http.request"}

        scope = {"type": "http", "headers": []}
        asyncio.run(middleware(scope, receive, send))
        self.assertEqual(events[0]["status"], 200)

    def test_auth_middleware_rejects_missing_or_wrong_token(self):
        """Returns 401 Unauthorized with JSON body when token is missing or wrong."""
        import asyncio

        async def dummy_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})

        middleware = ApiTokenAuthMiddleware(dummy_app, expected_token="secure-test-token")

        # Missing token
        events_missing = []
        async def send_missing(event):
            events_missing.append(event)
        asyncio.run(middleware({"type": "http", "headers": []}, None, send_missing))
        self.assertEqual(events_missing[0]["status"], 401)
        self.assertEqual(events_missing[1]["body"], b'{"error": "Unauthorized"}')

        # Wrong token
        events_wrong = []
        async def send_wrong(event):
            events_wrong.append(event)
        headers_wrong = [(b"authorization", b"Bearer wrong-token")]
        asyncio.run(middleware({"type": "http", "headers": headers_wrong}, None, send_wrong))
        self.assertEqual(events_wrong[0]["status"], 401)

    def test_auth_middleware_accepts_valid_token(self):
        """Passes request through when valid Bearer token is provided."""
        import asyncio

        async def dummy_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"Authorized", "more_body": False})

        middleware = ApiTokenAuthMiddleware(dummy_app, expected_token="secure-test-token")

        events = []
        async def send_ok(event):
            events.append(event)
        headers_ok = [(b"authorization", b"Bearer secure-test-token")]
        asyncio.run(middleware({"type": "http", "headers": headers_ok}, None, send_ok))
        self.assertEqual(events[0]["status"], 200)
        self.assertEqual(events[1]["body"], b"Authorized")


if __name__ == "__main__":
    unittest.main()
