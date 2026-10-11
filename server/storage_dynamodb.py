"""DynamoDB storage backend for LifeVault.

Table Design:
- Single-table design with partition key 'pk' (string) and sort key 'sk' (string).
- Partition key 'pk' is fixed to 'USER#default' for single-user life-admin records.
- Sort key 'sk' is formatted as 'REC#' plus zero-padded 10-digit integer ID (e.g. 'REC#0000000001').
- Auto-increment IDs are managed with an atomic counter item: pk='USER#default', sk='COUNTER',
  incremented via DynamoDB atomic ADD expression on attribute 'last_id'.
- Amounts are stored as Decimal and converted back to float upon read. Attributes with None are omitted.
- Partition Query (pk='USER#default', sk begins_with 'REC#') with in-code filtering is used for
  search_records, list_records, list_upcoming, list_expired, list_bills, and spending_by_period.
- Never hardcodes or logs AWS credentials; relies on ambient credentials or AWS CLI profile.
"""

from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
import os
from typing import Any, Dict, List, Optional

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import (
    ClientError,
    EndpointConnectionError,
    NoCredentialsError,
)

from storage import Storage, StorageError


def _handle_dynamo_error(e: Exception) -> StorageError:
    """Translate AWS SDK exceptions into speech-friendly StorageError messages."""
    if isinstance(e, StorageError):
        return e
    if isinstance(e, NoCredentialsError):
        return StorageError(
            "I couldn't access your records because AWS credentials were not found. "
            "Please configure your AWS credentials."
        )
    if isinstance(e, EndpointConnectionError):
        return StorageError(
            "I couldn't connect to DynamoDB. Please check your network connection."
        )
    if isinstance(e, ClientError):
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code == "ResourceNotFoundException":
            return StorageError(
                "The LifeVault records table does not exist in DynamoDB. "
                "Please run create_table.py first."
            )
        if error_code in ("AccessDeniedException", "UnauthorizedOperation", "UnrecognizedClientException"):
            return StorageError(
                "Access to the LifeVault DynamoDB table was denied. "
                "Please verify your AWS permissions."
            )
        return StorageError(
            "A DynamoDB service error occurred while accessing your records."
        )
    return StorageError(
        "An unexpected error occurred while accessing your records in DynamoDB."
    )


class DynamoDbStorage(Storage):
    """Concrete Storage implementation using Amazon DynamoDB."""

    def __init__(
        self,
        table_name: Optional[str] = None,
        region_name: Optional[str] = None,
        dynamodb_resource: Optional[Any] = None,
    ):
        self.table_name = table_name or os.getenv("DYNAMODB_TABLE", "lifevault-records")
        self.region_name = region_name or os.getenv("AWS_REGION", "us-east-1")
        if dynamodb_resource is not None:
            self._dynamodb = dynamodb_resource
        else:
            self._dynamodb = boto3.resource("dynamodb", region_name=self.region_name)
        self._table = self._dynamodb.Table(self.table_name)

    # -------------------------------------------------------------------------
    # Serialization Helpers
    # -------------------------------------------------------------------------

    def _to_item(self, record_id: int, record_data: Dict[str, Any]) -> Dict[str, Any]:
        """Convert record dictionary to a DynamoDB item, omitting None attributes."""
        sk = f"REC#{record_id:010d}"
        item: Dict[str, Any] = {
            "pk": "USER#default",
            "sk": sk,
            "id": record_id,
            "type": str(record_data.get("type", "")).strip().lower(),
            "name": str(record_data.get("name", "")).strip(),
            "currency": str(record_data.get("currency", "USD")),
            "created_at": record_data.get("created_at") or datetime.now(timezone.utc).isoformat(),
        }

        if record_data.get("vendor"):
            item["vendor"] = str(record_data["vendor"]).strip()

        if record_data.get("amount") is not None:
            amt_float = round(float(record_data["amount"]), 2)
            item["amount"] = Decimal(str(amt_float))

        if record_data.get("purchase_date"):
            item["purchase_date"] = str(record_data["purchase_date"]).strip()

        if record_data.get("expiry_date"):
            item["expiry_date"] = str(record_data["expiry_date"]).strip()

        if record_data.get("renewal_cycle"):
            item["renewal_cycle"] = str(record_data["renewal_cycle"]).strip()

        if record_data.get("reminder_date"):
            item["reminder_date"] = str(record_data["reminder_date"]).strip()

        if record_data.get("notes"):
            item["notes"] = str(record_data["notes"]).strip()

        return item

    def _from_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Convert DynamoDB item back to record dict with same shape as SqliteStorage."""
        raw_amount = item.get("amount")
        amount_val = float(raw_amount) if raw_amount is not None else None

        return {
            "id": int(item["id"]),
            "type": str(item.get("type", "")),
            "name": str(item.get("name", "")),
            "vendor": str(item["vendor"]) if item.get("vendor") is not None else None,
            "amount": amount_val,
            "currency": str(item.get("currency", "USD")),
            "purchase_date": str(item["purchase_date"]) if item.get("purchase_date") is not None else None,
            "expiry_date": str(item["expiry_date"]) if item.get("expiry_date") is not None else None,
            "renewal_cycle": str(item["renewal_cycle"]) if item.get("renewal_cycle") is not None else None,
            "reminder_date": str(item["reminder_date"]) if item.get("reminder_date") is not None else None,
            "notes": str(item["notes"]) if item.get("notes") is not None else None,
            "created_at": str(item.get("created_at", "")),
        }

    def _query_all_records(self) -> List[Dict[str, Any]]:
        """Query partition 'USER#default' where sk begins with 'REC#'."""
        try:
            items: List[Dict[str, Any]] = []
            response = self._table.query(
                KeyConditionExpression=Key("pk").eq("USER#default") & Key("sk").begins_with("REC#")
            )
            items.extend(response.get("Items", []))
            while "LastEvaluatedKey" in response:
                response = self._table.query(
                    KeyConditionExpression=Key("pk").eq("USER#default") & Key("sk").begins_with("REC#"),
                    ExclusiveStartKey=response["LastEvaluatedKey"],
                )
                items.extend(response.get("Items", []))
            return [self._from_item(it) for it in items]
        except Exception as e:
            raise _handle_dynamo_error(e) from e

    # -------------------------------------------------------------------------
    # Abstract Storage Methods
    # -------------------------------------------------------------------------

    def add_record(self, record_data: Dict[str, Any]) -> Dict[str, Any]:
        """Atomically generate an auto-increment integer ID and insert the record."""
        try:
            # Atomic counter increment
            counter_resp = self._table.update_item(
                Key={"pk": "USER#default", "sk": "COUNTER"},
                UpdateExpression="ADD last_id :inc",
                ExpressionAttributeValues={":inc": 1},
                ReturnValues="UPDATED_NEW",
            )
            next_id = int(counter_resp["Attributes"]["last_id"])

            item = self._to_item(next_id, record_data)
            self._table.put_item(Item=item)
            return self._from_item(item)
        except Exception as e:
            raise _handle_dynamo_error(e) from e

    def get_record(self, record_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve a single record by primary integer ID."""
        try:
            sk = f"REC#{record_id:010d}"
            response = self._table.get_item(Key={"pk": "USER#default", "sk": sk})
            item = response.get("Item")
            if not item:
                return None
            return self._from_item(item)
        except Exception as e:
            raise _handle_dynamo_error(e) from e

    def search_records(self, query: str) -> List[Dict[str, Any]]:
        """Case-insensitive partial matching across name, vendor, and notes."""
        clean_query = query.strip().lower()
        records = self._query_all_records()
        matched = []
        for r in records:
            name_match = clean_query in (r["name"] or "").lower()
            vendor_match = clean_query in (r["vendor"] or "").lower()
            notes_match = clean_query in (r["notes"] or "").lower()
            if name_match or vendor_match or notes_match:
                matched.append(r)

        # Sort order identical to SQLite: expiry_date ASC (None first), name ASC
        matched.sort(key=lambda r: (0 if r["expiry_date"] is None else 1, r["expiry_date"] or "", r["name"] or ""))
        return matched

    def update_record(self, record_id: int, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update specified fields of a record."""
        valid_fields = {
            "type", "name", "vendor", "amount", "currency",
            "purchase_date", "expiry_date", "renewal_cycle",
            "reminder_date", "notes",
        }
        filtered = {k: v for k, v in updates.items() if k in valid_fields}
        existing = self.get_record(record_id)
        if not existing:
            return None
        if not filtered:
            return existing

        existing.update(filtered)
        try:
            item = self._to_item(record_id, existing)
            self._table.put_item(Item=item)
            return self._from_item(item)
        except Exception as e:
            raise _handle_dynamo_error(e) from e

    def delete_record(self, record_id: int) -> bool:
        """Delete a record by ID. Returns True if deleted, False if not found."""
        try:
            sk = f"REC#{record_id:010d}"
            self._table.delete_item(
                Key={"pk": "USER#default", "sk": sk},
                ConditionExpression="attribute_exists(pk) AND attribute_exists(sk)",
            )
            return True
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return False
            raise _handle_dynamo_error(e) from e
        except Exception as e:
            raise _handle_dynamo_error(e) from e

    def list_records(self, type: Optional[str] = None) -> List[Dict[str, Any]]:
        """List records, optionally filtering by record type."""
        records = self._query_all_records()
        if type:
            clean_type = type.strip().lower()
            records = [r for r in records if (r["type"] or "").lower() == clean_type]
        records.sort(key=lambda r: (0 if r["expiry_date"] is None else 1, r["expiry_date"] or "", r["name"] or ""))
        return records

    def list_upcoming(self, days: int) -> List[Dict[str, Any]]:
        """List upcoming deadlines between today and today + days."""
        today_str = date.today().isoformat()
        future_str = (date.today() + timedelta(days=days)).isoformat()
        records = self._query_all_records()
        upcoming = [
            r for r in records
            if r.get("expiry_date") and today_str <= r["expiry_date"] <= future_str
        ]
        upcoming.sort(key=lambda r: (r["expiry_date"], r["name"]))
        return upcoming

    def list_expired(self, days: int) -> List[Dict[str, Any]]:
        """List records that expired between today - days and today."""
        today_str = date.today().isoformat()
        past_str = (date.today() - timedelta(days=days)).isoformat()
        records = self._query_all_records()
        expired = [
            r for r in records
            if r.get("expiry_date") and past_str <= r["expiry_date"] < today_str
        ]
        expired.sort(key=lambda r: (r["expiry_date"], r["name"]), reverse=True)
        return expired

    def list_bills(self, name: Optional[str] = None) -> List[Dict[str, Any]]:
        """List bill records, ordered by purchase date ascending, id ascending."""
        records = self._query_all_records()
        bills = [r for r in records if (r.get("type") or "").lower() == "bill"]
        if name:
            clean = name.strip().lower()
            bills = [
                r for r in bills
                if clean in (r["name"] or "").lower() or clean in (r["vendor"] or "").lower()
            ]
        bills.sort(key=lambda r: (0 if r["purchase_date"] is None else 1, r["purchase_date"] or "", r["id"]))
        return bills

    def spending_by_period(self, start: str, end: str) -> Dict[str, Any]:
        """Aggregate total spending and category breakdown for a date range."""
        records = self._query_all_records()
        valid = [
            r for r in records
            if r.get("amount") is not None
            and r.get("purchase_date") is not None
            and start <= r["purchase_date"] <= end
        ]

        categories: Dict[str, float] = {}
        total = 0.0
        for r in valid:
            c_type = r["type"]
            amt = float(r["amount"])
            categories[c_type] = round(categories.get(c_type, 0.0) + amt, 2)
            total += amt

        sorted_cats = sorted(categories.items(), key=lambda x: x[1], reverse=True)
        top_category = sorted_cats[0][0] if sorted_cats else None
        top_amount = sorted_cats[0][1] if sorted_cats else 0.0

        return {
            "start": start,
            "end": end,
            "total": round(total, 2),
            "categories": dict(sorted_cats),
            "top_category": top_category,
            "top_amount": top_amount,
        }

    # -------------------------------------------------------------------------
    # Maintenance / Seeding Helper (Internal, not exposed as MCP tool)
    # -------------------------------------------------------------------------

    def clear_all(self) -> None:
        """Delete all items under partition key 'USER#default'.

        Internal helper for database re-seeding only. Must never be exposed as an MCP tool.
        """
        try:
            response = self._table.query(
                KeyConditionExpression=Key("pk").eq("USER#default"),
                ProjectionExpression="pk, sk",
            )
            items = response.get("Items", [])
            while "LastEvaluatedKey" in response:
                response = self._table.query(
                    KeyConditionExpression=Key("pk").eq("USER#default"),
                    ProjectionExpression="pk, sk",
                    ExclusiveStartKey=response["LastEvaluatedKey"],
                )
                items.extend(response.get("Items", []))

            if not items:
                return

            with self._table.batch_writer() as batch:
                for it in items:
                    batch.delete_item(Key={"pk": it["pk"], "sk": it["sk"]})
        except Exception as e:
            raise _handle_dynamo_error(e) from e
