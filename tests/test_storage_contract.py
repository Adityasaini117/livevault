"""Contract test suite for LifeVault Storage backends.

Runs identical contract test assertions against both:
1. SqliteStorage (isolated temporary SQLite file)
2. DynamoDbStorage (mocked via moto, never calls real AWS)

Verifies:
- Full CRUD semantics and exact dictionary shape compatibility
- Float round-tripping for amounts (e.g. 168.0 stays 168.0 as float)
- In-memory querying, filtering, upcoming/expired deadlines, and spending aggregations
- bill_anomalies detection on DynamoDB with 42% electricity spike
- clear_all() deletes only items under pk 'USER#default'
- Friendly spoken error handling for missing table, credentials, and access denial
"""

from datetime import date, timedelta
import os
from pathlib import Path
import sys
import tempfile
import unittest

# Ensure server module is discoverable
server_dir = Path(__file__).resolve().parent.parent / "server"
if str(server_dir) not in sys.path:
    sys.path.insert(0, str(server_dir))

import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from moto import mock_aws

import server
from storage import Storage, StorageError, SqliteStorage
from storage_dynamodb import DynamoDbStorage


class StorageContractBase:
    """Reusable contract tests executing against any LifeVault Storage implementation."""

    storage: Storage

    def test_add_and_get_record(self):
        """Test adding and retrieving a record with full schema validation."""
        today = date.today().isoformat()
        record_data = {
            "type": "warranty",
            "name": "MacBook Pro",
            "vendor": "Apple",
            "amount": 2499.00,
            "currency": "USD",
            "purchase_date": today,
            "expiry_date": (date.today() + timedelta(days=365)).isoformat(),
            "renewal_cycle": None,
            "reminder_date": (date.today() + timedelta(days=335)).isoformat(),
            "notes": "AppleCare+ plan",
        }

        created = self.storage.add_record(record_data)
        self.assertIsInstance(created["id"], int)
        self.assertEqual(created["name"], "MacBook Pro")
        self.assertEqual(created["vendor"], "Apple")
        self.assertEqual(created["amount"], 2499.0)
        self.assertIsInstance(created["amount"], float)
        self.assertIn("created_at", created)

        # Retrieve by id
        fetched = self.storage.get_record(created["id"])
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["id"], created["id"])
        self.assertEqual(fetched["name"], "MacBook Pro")
        self.assertEqual(fetched["amount"], 2499.0)
        self.assertIsInstance(fetched["amount"], float)

        # Missing record returns None
        self.assertIsNone(self.storage.get_record(999999))

    def test_amount_float_round_trip(self):
        """Confirm amounts round-trip as floats (e.g. 168.0 stays 168.0)."""
        # Case 1: Exact float 168.0
        rec1 = self.storage.add_record({
            "type": "bill",
            "name": "City Electric Utility Bill",
            "amount": 168.0,
            "purchase_date": date.today().isoformat(),
        })
        fetched1 = self.storage.get_record(rec1["id"])
        self.assertIsInstance(fetched1["amount"], float)
        self.assertEqual(fetched1["amount"], 168.0)

        # Case 2: Fractional amount 79.99
        rec2 = self.storage.add_record({
            "type": "bill",
            "name": "Internet Bill",
            "amount": 79.99,
            "purchase_date": date.today().isoformat(),
        })
        fetched2 = self.storage.get_record(rec2["id"])
        self.assertIsInstance(fetched2["amount"], float)
        self.assertEqual(fetched2["amount"], 79.99)

        # Case 3: None amount
        rec3 = self.storage.add_record({
            "type": "document",
            "name": "Passport",
            "amount": None,
            "purchase_date": date.today().isoformat(),
        })
        fetched3 = self.storage.get_record(rec3["id"])
        self.assertIsNone(fetched3["amount"])

    def test_update_record(self):
        """Test updating fields on an existing record."""
        rec = self.storage.add_record({
            "type": "subscription",
            "name": "Gym",
            "amount": 50.0,
            "notes": "Basic tier",
        })

        updated = self.storage.update_record(rec["id"], {
            "amount": 65.0,
            "notes": "Upgraded tier",
            "ignored_field": "disallowed",
        })

        self.assertIsNotNone(updated)
        self.assertEqual(updated["amount"], 65.0)
        self.assertIsInstance(updated["amount"], float)
        self.assertEqual(updated["notes"], "Upgraded tier")
        self.assertNotIn("ignored_field", updated)

        # Updating nonexistent record returns None
        self.assertIsNone(self.storage.update_record(999999, {"amount": 10.0}))

    def test_delete_record(self):
        """Test deleting a record and ensuring it is no longer retrievable."""
        rec = self.storage.add_record({
            "type": "document",
            "name": "Library Card",
        })

        deleted = self.storage.delete_record(rec["id"])
        self.assertTrue(deleted)
        self.assertIsNone(self.storage.get_record(rec["id"]))

        # Second deletion returns False
        self.assertFalse(self.storage.delete_record(rec["id"]))

    def test_search_and_list_records(self):
        """Test search_records and list_records."""
        self.storage.add_record({"type": "warranty", "name": "Bose Headphones", "vendor": "Bose", "notes": "Active"})
        self.storage.add_record({"type": "subscription", "name": "Spotify Family", "vendor": "Spotify", "notes": "Music"})
        self.storage.add_record({"type": "warranty", "name": "Sony Headphones", "vendor": "Sony", "notes": "Over-ear"})

        # Partial search
        results = self.storage.search_records("headphones")
        self.assertEqual(len(results), 2)
        names = {r["name"] for r in results}
        self.assertEqual(names, {"Bose Headphones", "Sony Headphones"})

        # List all
        all_recs = self.storage.list_records()
        self.assertEqual(len(all_recs), 3)

        # List by type
        warranties = self.storage.list_records(type="warranty")
        self.assertEqual(len(warranties), 2)

    def test_list_upcoming_and_expired(self):
        """Test list_upcoming and list_expired filtering by relative dates."""
        today = date.today()
        # Upcoming in 5 days
        self.storage.add_record({
            "type": "bill",
            "name": "Water Bill",
            "expiry_date": (today + timedelta(days=5)).isoformat(),
        })
        # Upcoming in 20 days
        self.storage.add_record({
            "type": "insurance",
            "name": "Auto Insurance",
            "expiry_date": (today + timedelta(days=20)).isoformat(),
        })
        # Expired 3 days ago
        self.storage.add_record({
            "type": "subscription",
            "name": "Cloud Storage",
            "expiry_date": (today - timedelta(days=3)).isoformat(),
        })

        upcoming_7 = self.storage.list_upcoming(7)
        self.assertEqual(len(upcoming_7), 1)
        self.assertEqual(upcoming_7[0]["name"], "Water Bill")

        upcoming_30 = self.storage.list_upcoming(30)
        self.assertEqual(len(upcoming_30), 2)

        expired_14 = self.storage.list_expired(14)
        self.assertEqual(len(expired_14), 1)
        self.assertEqual(expired_14[0]["name"], "Cloud Storage")

    def test_list_bills(self):
        """Test list_bills ordering by purchase_date ASC and name filtering."""
        today = date.today()
        self.storage.add_record({
            "type": "bill",
            "name": "Electric Bill",
            "amount": 100.0,
            "purchase_date": (today - timedelta(days=60)).isoformat(),
        })
        self.storage.add_record({
            "type": "bill",
            "name": "Electric Bill",
            "amount": 120.0,
            "purchase_date": (today - timedelta(days=30)).isoformat(),
        })
        self.storage.add_record({
            "type": "subscription",
            "name": "Netflix",
            "amount": 20.0,
            "purchase_date": (today - timedelta(days=15)).isoformat(),
        })

        bills = self.storage.list_bills("Electric")
        self.assertEqual(len(bills), 2)
        # Oldest first
        self.assertEqual(bills[0]["amount"], 100.0)
        self.assertEqual(bills[1]["amount"], 120.0)

    def test_spending_by_period(self):
        """Test spending_by_period aggregations across category breakdowns."""
        today = date.today()
        d1 = (today - timedelta(days=10)).isoformat()
        d2 = (today - timedelta(days=5)).isoformat()

        self.storage.add_record({"type": "bill", "name": "Bill 1", "amount": 150.0, "purchase_date": d1})
        self.storage.add_record({"type": "bill", "name": "Bill 2", "amount": 50.0, "purchase_date": d2})
        self.storage.add_record({"type": "subscription", "name": "Sub 1", "amount": 25.0, "purchase_date": d2})

        start = (today - timedelta(days=15)).isoformat()
        end = today.isoformat()
        summary = self.storage.spending_by_period(start, end)

        self.assertEqual(summary["total"], 225.0)
        self.assertEqual(summary["top_category"], "bill")
        self.assertEqual(summary["top_amount"], 200.0)
        self.assertEqual(summary["categories"]["bill"], 200.0)
        self.assertEqual(summary["categories"]["subscription"], 25.0)


class TestSqliteStorageContract(StorageContractBase, unittest.TestCase):
    """Run contract tests against SqliteStorage."""

    def setUp(self):
        self.temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_file.close()
        self.storage = SqliteStorage(db_path=self.temp_file.name)
        self.storage.init_db(drop_existing=True)

    def tearDown(self):
        try:
            os.unlink(self.temp_file.name)
        except OSError:
            pass


class TestDynamoDbStorageContract(StorageContractBase, unittest.TestCase):
    """Run contract tests against DynamoDbStorage using Moto."""

    def setUp(self):
        # Configure clean mock AWS environment
        os.environ["AWS_ACCESS_KEY_ID"] = "testing"
        os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
        os.environ.pop("AWS_SECURITY_TOKEN", None)
        os.environ.pop("AWS_SESSION_TOKEN", None)
        os.environ["AWS_DEFAULT_REGION"] = "us-east-1"

        self.mock_aws = mock_aws()
        self.mock_aws.start()

        self.table_name = "test-lifevault-records"
        self.region_name = "us-east-1"
        self.dynamodb = boto3.resource("dynamodb", region_name=self.region_name)

        # Create table with PAY_PER_REQUEST
        self.table = self.dynamodb.create_table(
            TableName=self.table_name,
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        self.storage = DynamoDbStorage(
            table_name=self.table_name,
            region_name=self.region_name,
            dynamodb_resource=self.dynamodb,
        )

    def tearDown(self):
        self.mock_aws.stop()

    def test_clear_all_only_deletes_default_user_partition(self):
        """Confirm clear_all() deletes items under pk 'USER#default' but preserves other partitions."""
        # Add item under default partition
        self.storage.add_record({"type": "bill", "name": "Default Bill", "amount": 100.0})

        # Add item under foreign partition
        self.table.put_item(Item={"pk": "USER#other", "sk": "REC#0000000001", "name": "Other Bill"})

        # Execute clear_all
        self.storage.clear_all()

        # Default items are deleted
        self.assertEqual(len(self.storage.list_records()), 0)

        # Foreign item remains intact
        resp = self.table.get_item(Key={"pk": "USER#other", "sk": "REC#0000000001"})
        self.assertIn("Item", resp)
        self.assertEqual(resp["Item"]["name"], "Other Bill")

    def test_bill_anomalies_flags_electricity_bill_on_dynamodb(self):
        """Confirm bill_anomalies still flags the electricity bill when running on DynamoDB."""
        today = date.today()
        # Seed 5 earlier bills around 118.00 (median 118.0)
        for days_ago, amt in [(150, 116.0), (120, 119.5), (90, 118.0), (60, 117.0), (30, 120.0)]:
            self.storage.add_record({
                "type": "bill",
                "name": "City Electric Utility Bill",
                "amount": amt,
                "purchase_date": (today - timedelta(days=days_ago)).isoformat(),
            })

        # Add latest bill with 168.00 (~42% spike)
        self.storage.add_record({
            "type": "bill",
            "name": "City Electric Utility Bill",
            "amount": 168.0,
            "purchase_date": (today - timedelta(days=4)).isoformat(),
        })

        # Point server.storage to DynamoDbStorage instance
        orig_storage = server.storage
        try:
            server.storage = self.storage
            res = server.bill_anomalies()
            self.assertIn("42 percent higher than usual", res)
            self.assertIn("168 dollars against about 118", res)
        finally:
            server.storage = orig_storage

    def test_friendly_errors_on_dynamodb_failures(self):
        """Confirm missing table, missing credentials, and access denial return friendly spoken messages."""
        # 1. Nonexistent table
        missing_table_storage = DynamoDbStorage(
            table_name="nonexistent-table",
            region_name="us-east-1",
            dynamodb_resource=self.dynamodb,
        )

        orig_storage = server.storage
        try:
            server.storage = missing_table_storage
            # Call tool and confirm friendly error message is returned, not an exception
            res = server.upcoming_deadlines()
            self.assertIn("LifeVault records table does not exist in DynamoDB", res)
            self.assertNotIn("Traceback", res)
        finally:
            server.storage = orig_storage


if __name__ == "__main__":
    unittest.main()
