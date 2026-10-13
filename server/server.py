"""LifeVault - MCP Server.

Provides voice-first life-admin assistant tools over Streamable HTTP transport.
Exposed to Alexa+ as an MCP server.
"""

import calendar
from datetime import date, datetime, timedelta
import functools
import hmac
import json
import os
from pathlib import Path
import statistics
import sys
from typing import Any, Dict, List, Optional, Tuple

# Ensure local imports work regardless of execution working directory
server_dir = Path(__file__).resolve().parent
if str(server_dir) not in sys.path:
    sys.path.insert(0, str(server_dir))

# In official mcp SDK v2+, FastMCP was renamed to MCPServer
try:
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:
    from mcp.server.fastmcp import FastMCP

from ai import extract_record, AIError
from storage import get_storage, StorageError, VALID_TYPES

# Check API token on startup and print warning if not configured
_api_token = os.getenv("LIFEVAULT_API_TOKEN")
if not _api_token or not _api_token.strip():
    print("WARNING: LIFEVAULT_API_TOKEN is not set. Access protection is disabled.")


def _handle_storage_errors(func):
    """Decorator to catch StorageError and return a friendly spoken message."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except StorageError as e:
            return str(e)
    return wrapper


class ApiTokenAuthMiddleware:
    """ASGI middleware to enforce Bearer token authentication."""

    def __init__(self, app, expected_token: Optional[str] = None):
        self.app = app
        self.expected_token = expected_token.strip() if expected_token and expected_token.strip() else None

    async def __call__(self, scope, receive, send):
        # Allow non-HTTP scopes (lifespan, etc.) to pass directly through
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        # If token is not set, access protection is disabled (local testing)
        if not self.expected_token:
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        # Return 404 for OAuth discovery and endpoint paths so clients do not assume OAuth is supported
        if path.startswith("/.well-known/") or path in ("/register", "/authorize", "/token"):
            body = b'{"error": "Not Found"}'
            await send({
                "type": "http.response.start",
                "status": 404,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            })
            await send({
                "type": "http.response.body",
                "body": body,
                "more_body": False,
            })
            return

        # Only enforce bearer token on the MCP endpoint (/mcp)
        if not (path == "/mcp" or path.startswith("/mcp/")):
            await self.app(scope, receive, send)
            return

        # Extract Authorization header without logging
        auth_header = None
        for key, value in scope.get("headers", []):
            if key.lower() == b"authorization":
                try:
                    auth_header = value.decode("utf-8")
                except UnicodeDecodeError:
                    pass
                break

        authorized = False
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
            if hmac.compare_digest(token, self.expected_token):
                authorized = True

        if not authorized:
            body = b'{"error": "Unauthorized"}'
            await send({
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                    (b"www-authenticate", b"Bearer"),
                ],
            })
            await send({
                "type": "http.response.body",
                "body": body,
                "more_body": False,
            })
            return

        await self.app(scope, receive, send)


# Initialize storage and MCP server
storage = get_storage()
mcp = FastMCP("LifeVault")

# Wrap streamable_http_app to enforce ASGI auth protection
_orig_streamable_http_app = mcp.streamable_http_app


def _protected_streamable_http_app(*args, **kwargs):
    starlette_app = _orig_streamable_http_app(*args, **kwargs)
    token = os.getenv("LIFEVAULT_API_TOKEN")
    return ApiTokenAuthMiddleware(starlette_app, expected_token=token)


mcp.streamable_http_app = _protected_streamable_http_app


def _add_months(source_date: date, months: int) -> date:
    """Accurately add months to a given date, preserving end-of-month bounds."""
    month = source_date.month - 1 + months
    year = source_date.year + month // 12
    month = month % 12 + 1
    max_day = calendar.monthrange(year, month)[1]
    day = min(source_date.day, max_day)
    return date(year, month, day)


def _format_clarification(options: list[str]) -> str:
    """Format multiple matches into a clean speech-friendly clarifying question."""
    if len(options) == 2:
        return f"Did you mean {options[0]} or {options[1]}?"
    return f"Did you mean {', '.join(options[:-1])}, or {options[-1]}?"


def _spoken_date(d: date) -> str:
    """Format a date for natural spoken speech, e.g. 'October 16'."""
    month_name = calendar.month_name[d.month]
    return f"{month_name} {d.day}"


def _format_upcoming_speech(item: Dict[str, Any], today: date) -> str:
    """Format an upcoming record naturally for speech."""
    name = item["name"]
    expiry_str = item.get("expiry_date")
    rec_type = item.get("type", "").lower()

    # Determine action verb based on record type
    if rec_type == "subscription":
        action = "renews"
    elif rec_type == "bill":
        action = "is due"
    else:
        action = "expires"

    if not expiry_str:
        return f"{name} {action} soon"

    try:
        exp_date = date.fromisoformat(expiry_str)
        delta = (exp_date - today).days
        spoken_d = _spoken_date(exp_date)
        if delta == 0:
            return f"{name} {action} today, on {spoken_d}"
        elif delta == 1:
            return f"{name} {action} tomorrow, on {spoken_d}"
        else:
            return f"{name} {action} in {delta} days, on {spoken_d}"
    except ValueError:
        return f"{name} {action} on {expiry_str}"


def _format_expired_speech(item: Dict[str, Any], today: date) -> str:
    """Format an expired record naturally for speech."""
    name = item["name"]
    expiry_str = item.get("expiry_date")

    if not expiry_str:
        return f"{name} expired"

    try:
        exp_date = date.fromisoformat(expiry_str)
        delta = (today - exp_date).days
        spoken_d = _spoken_date(exp_date)
        if delta == 1:
            return f"{name} expired 1 day ago, on {spoken_d}"
        elif delta > 1:
            return f"{name} expired {delta} days ago, on {spoken_d}"
        else:
            return f"{name} expired today, on {spoken_d}"
    except ValueError:
        return f"{name} expired on {expiry_str}"


@mcp.tool()
def ping() -> str:
    """Return health check status for LifeVault."""
    return "LifeVault is alive"


@mcp.tool()
@_handle_storage_errors
def add_record(
    type: str,
    name: str,
    amount: Optional[float] = None,
    purchase_date: Optional[str] = None,
    warranty_months: Optional[int] = None,
    renewal_cycle: Optional[str] = None,
    vendor: Optional[str] = None,
    notes: Optional[str] = None,
) -> str:
    """Add a life-admin record (warranty, subscription, insurance, bill, document).

    Computes expiry date and reminder date when warranty_months is supplied.
    """
    clean_type = type.strip().lower()
    clean_name = name.strip()

    if not clean_name:
        return "Please provide a name for the record."

    if clean_type not in VALID_TYPES:
        return "Please specify a valid record type: warranty, subscription, insurance, bill, or document."

    if amount is not None and amount < 0:
        return "Amount cannot be negative."

    # Validate or default purchase date
    if purchase_date:
        try:
            p_date = date.fromisoformat(purchase_date.strip())
        except ValueError:
            return "Please provide purchase_date in YYYY-MM-DD format."
    else:
        p_date = date.today()

    expiry_date_str = None
    reminder_date_str = None

    if warranty_months is not None:
        if warranty_months < 0:
            return "Warranty months cannot be negative."
        expiry_d = _add_months(p_date, warranty_months)
        reminder_d = expiry_d - timedelta(days=30)
        expiry_date_str = expiry_d.isoformat()
        reminder_date_str = reminder_d.isoformat()

    record_data = {
        "type": clean_type,
        "name": clean_name,
        "vendor": vendor.strip() if vendor else None,
        "amount": round(float(amount), 2) if amount is not None else None,
        "currency": "USD",
        "purchase_date": p_date.isoformat(),
        "expiry_date": expiry_date_str,
        "renewal_cycle": renewal_cycle.strip() if renewal_cycle else None,
        "reminder_date": reminder_date_str,
        "notes": notes.strip() if notes else None,
    }

    created = storage.add_record(record_data)

    if expiry_date_str and reminder_date_str:
        return (
            f"Saved {created['name']}. The warranty expires on {expiry_date_str}, "
            f"and a reminder is set for {reminder_date_str}."
        )

    article = "an" if clean_type.startswith(("a", "e", "i", "o", "u")) else "a"
    return f"Saved {created['name']} as {article} {clean_type}."


@mcp.tool()
def add_record_from_text(text: str) -> str:
    """Extract and save a life-admin record from natural language voice transcript.

    Dispatches to AI provider (Gemini or Bedrock) to extract type, name, vendor,
    amount, purchase date, warranty months, and renewal cycle.
    """
    clean_text = text.strip() if text else ""
    if not clean_text:
        return "Please tell me what record you'd like to save."

    try:
        data = extract_record(clean_text, date.today())
    except AIError as e:
        return str(e)
    except Exception:
        return "I had trouble understanding the details from that. Could you please rephrase?"

    raw_type = data.get("type")
    raw_name = data.get("name")

    extracted_type = raw_type.strip().lower() if isinstance(raw_type, str) and raw_type.strip() else None
    extracted_name = raw_name.strip() if isinstance(raw_name, str) and raw_name.strip() else None

    # Clarifying questions if name or type is missing or not a known type
    if not extracted_name and not extracted_type:
        return "What item or record would you like to save, and what type is it?"
    if not extracted_name:
        return f"What is the name of the {extracted_type} you would like to save?"
    if not extracted_type or extracted_type not in VALID_TYPES:
        return f"What type of record is {extracted_name}? For example: warranty, subscription, insurance, bill, or document."

    # Parse and validate optional fields
    amount = data.get("amount")
    if amount is not None:
        try:
            amount = float(amount)
        except (ValueError, TypeError):
            amount = None

    warranty_months = data.get("warranty_months")
    if warranty_months is not None:
        try:
            warranty_months = int(warranty_months)
        except (ValueError, TypeError):
            warranty_months = None

    purchase_date = data.get("purchase_date")
    if purchase_date and not isinstance(purchase_date, str):
        purchase_date = None

    renewal_cycle = data.get("renewal_cycle")
    if renewal_cycle and not isinstance(renewal_cycle, str):
        renewal_cycle = None

    vendor = data.get("vendor")
    if vendor and not isinstance(vendor, str):
        vendor = None

    notes = data.get("notes")
    if notes and not isinstance(notes, str):
        notes = None

    return add_record(
        type=extracted_type,
        name=extracted_name,
        amount=amount,
        purchase_date=purchase_date,
        warranty_months=warranty_months,
        renewal_cycle=renewal_cycle,
        vendor=vendor,
        notes=notes,
    )


@mcp.tool()
@_handle_storage_errors
def find_record(query: str) -> str:
    """Find records matching a search query by name, vendor, or notes."""
    clean_query = query.strip()
    if not clean_query:
        return "Please specify what record to find."

    matches = storage.search_records(clean_query)
    if not matches:
        return f"I couldn't find any records matching '{clean_query}'."

    if len(matches) == 1:
        match = matches[0]
        details = [f"Found {match['name']}, a {match['type']}"]
        if match.get("vendor"):
            details.append(f"from {match['vendor']}")
        if match.get("expiry_date"):
            details.append(f"expiring on {match['expiry_date']}")
        elif match.get("amount"):
            details.append(f"amounting to ${match['amount']:.2f}")
        return " ".join(details) + "."

    names = [m["name"] for m in matches]
    return _format_clarification(names)


@mcp.tool()
@_handle_storage_errors
def warranty_status(item: str) -> str:
    """Check if an item is under warranty, expiry date, and days remaining or past."""
    clean_item = item.strip()
    if not clean_item:
        return "Please specify an item to check warranty status."

    # Search for matching records, prioritizing warranty types
    all_matches = storage.search_records(clean_item)
    warranty_matches = [m for m in all_matches if m["type"] == "warranty"]

    if not warranty_matches:
        if all_matches:
            return f"I found {all_matches[0]['name']}, but it is not tracked as a warranty."
        return f"I couldn't find any warranty records for '{clean_item}'."

    if len(warranty_matches) > 1:
        names = [m["name"] for m in warranty_matches]
        return _format_clarification(names)

    match = warranty_matches[0]
    expiry_str = match.get("expiry_date")
    if not expiry_str:
        return f"Your {match['name']} is on file, but has no expiry date recorded."

    expiry_date = date.fromisoformat(expiry_str)
    today = date.today()
    delta_days = (expiry_date - today).days

    if delta_days >= 0:
        return f"Your {match['name']} is under warranty until {expiry_str}, with {delta_days} days remaining."

    days_ago = abs(delta_days)
    return f"The warranty for your {match['name']} expired on {expiry_str}, {days_ago} days ago."


@mcp.tool()
@_handle_storage_errors
def upcoming_deadlines(days: int = 30) -> str:
    """List warranties, renewals, bills, and document expiries due in the next N days."""
    if days <= 0:
        return "Please specify a positive number of days."

    upcoming = storage.list_upcoming(days)
    if not upcoming:
        return f"You have no upcoming deadlines in the next {days} days."

    total = len(upcoming)
    display_items = upcoming[:5]
    spoken_list = [f"{item['name']} on {item['expiry_date']}" for item in display_items]

    if total <= 5:
        return f"You have {total} upcoming deadline{'s' if total != 1 else ''}: {', '.join(spoken_list)}."

    remaining = total - 5
    return f"You have {total} upcoming deadlines: {', '.join(spoken_list)}, and {remaining} more."


@mcp.tool()
@_handle_storage_errors
def spending_summary(period: str) -> str:
    """Summarize spending total and top category for 'this month', 'last month', or 'this year'."""
    clean_period = period.strip().lower()
    today = date.today()

    if clean_period == "this month":
        start_date = date(today.year, today.month, 1)
        end_date = today
    elif clean_period == "last month":
        if today.month == 1:
            lm_year = today.year - 1
            lm_month = 12
        else:
            lm_year = today.year
            lm_month = today.month - 1
        _, last_day = calendar.monthrange(lm_year, lm_month)
        start_date = date(lm_year, lm_month, 1)
        end_date = date(lm_year, lm_month, last_day)
    elif clean_period == "this year":
        start_date = date(today.year, 1, 1)
        end_date = today
    else:
        return "Please specify 'this month', 'last month', or 'this year' for spending summary."

    summary = storage.spending_by_period(start_date.isoformat(), end_date.isoformat())

    if summary["total"] <= 0:
        return f"You have no recorded spending for {clean_period}."

    top_cat = summary["top_category"] or "general"
    top_amt = summary["top_amount"]
    return (
        f"You spent ${summary['total']:.2f} {clean_period}, with {top_cat} "
        f"being your highest category at ${top_amt:.2f}."
    )


@mcp.tool()
@_handle_storage_errors
def delete_record(name: str, confirm: bool = False) -> str:
    """Delete a record by name. Requires confirm=True to permanently delete."""
    clean_name = name.strip()
    if not clean_name:
        return "Please specify the name of the record to delete."

    matches = storage.search_records(clean_name)
    if not matches:
        return f"I couldn't find any record matching '{clean_name}'."

    # Check for exact case-insensitive match first to narrow options
    exact_matches = [m for m in matches if m["name"].lower() == clean_name.lower()]
    if len(exact_matches) == 1:
        target = exact_matches[0]
    elif len(matches) > 1:
        names = [m["name"] for m in matches]
        return _format_clarification(names)
    else:
        target = matches[0]

    if not confirm:
        return f"Are you sure you want to delete the record for {target['name']}? Please confirm to proceed."

    storage.delete_record(target["id"])
    return f"The record for {target['name']} has been deleted."


def _detect_bill_anomalies(name: Optional[str] = None) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Detect bill anomalies where the latest bill is > 25% above earlier median.

    Requires at least 3 earlier bills plus the latest (at least 4 bills total).
    Returns (anomalies_list, message_override).
    """
    try:
        bills = storage.list_bills(name)
    except StorageError as e:
        return [], str(e)

    if not bills:
        if name:
            return [], f"I couldn't find any bill records matching '{name.strip()}'."
        return [], "No bill records found."

    groups: Dict[str, List[Dict[str, Any]]] = {}
    for bill in bills:
        if bill.get("amount") is None:
            continue
        key = bill["name"].strip().lower()
        groups.setdefault(key, []).append(bill)

    if not groups:
        if name:
            return [], f"There is not enough billing history to detect anomalies for {name.strip()}."
        return [], "No unusual bill amounts detected."

    if name and len(groups) == 1:
        series = list(groups.values())[0]
        series.sort(key=lambda b: (b.get("purchase_date") or "", b.get("id") or 0))
        if len(series) < 4:
            return [], f"There is not enough billing history to detect anomalies for {name.strip()}."

        earlier = series[:-1]
        latest = series[-1]
        earlier_amounts = [b["amount"] for b in earlier]
        med = statistics.median(earlier_amounts)

        if med > 0 and latest["amount"] > 1.25 * med:
            pct = round(((latest["amount"] - med) / med) * 100)
            latest_val = int(latest["amount"]) if float(latest["amount"]).is_integer() else f"{latest['amount']:.2f}"
            med_val = int(round(med))
            raw_name = latest["name"].strip()
            if "bill" in raw_name.lower():
                bill_name = raw_name
            else:
                bill_name = f"{raw_name} bill"
            msg = f"Your {bill_name} is {pct} percent higher than usual: {latest_val} dollars against about {med_val}."
            return [{
                "name": latest["name"],
                "pct": pct,
                "latest": latest["amount"],
                "median": med,
                "message": msg,
            }], None
        return [], f"No unusual bill amounts detected for {name.strip()}."

    anomalies: List[Dict[str, Any]] = []
    for key, series in groups.items():
        series.sort(key=lambda b: (b.get("purchase_date") or "", b.get("id") or 0))
        if len(series) < 4:
            continue
        earlier = series[:-1]
        latest = series[-1]
        earlier_amounts = [b["amount"] for b in earlier]
        med = statistics.median(earlier_amounts)

        if med > 0 and latest["amount"] > 1.25 * med:
            pct = round(((latest["amount"] - med) / med) * 100)
            latest_val = int(latest["amount"]) if float(latest["amount"]).is_integer() else f"{latest['amount']:.2f}"
            med_val = int(round(med))
            raw_name = latest["name"].strip()
            if "bill" in raw_name.lower():
                bill_name = raw_name
            else:
                bill_name = f"{raw_name} bill"
            msg = f"Your {bill_name} is {pct} percent higher than usual: {latest_val} dollars against about {med_val}."
            anomalies.append({
                "name": latest["name"],
                "pct": pct,
                "latest": latest["amount"],
                "median": med,
                "message": msg,
            })

    return anomalies, None


@mcp.tool()
@_handle_storage_errors
def renew_record(
    name: str,
    extend_months: Optional[int] = None,
    new_expiry_date: Optional[str] = None,
    amount: Optional[float] = None,
) -> str:
    """Renew a life-admin record, updating expiry and reminder dates."""
    clean_name = name.strip() if name else ""
    if not clean_name:
        return "Please specify the name of the record to renew."

    matches = storage.search_records(clean_name)
    if not matches:
        return f"I couldn't find any records matching '{clean_name}'."

    if len(matches) > 1:
        names = [m["name"] for m in matches]
        return _format_clarification(names)

    record = matches[0]
    today = date.today()

    # Determine new expiry date
    if new_expiry_date is not None and str(new_expiry_date).strip():
        try:
            target_expiry = date.fromisoformat(str(new_expiry_date).strip())
        except ValueError:
            return "Please provide new_expiry_date in YYYY-MM-DD format."
        if target_expiry <= today:
            return "The new expiry date must be after today."
    elif extend_months is not None:
        try:
            months = int(extend_months)
            if months <= 0:
                return "Please specify a positive number of months to extend."
        except (ValueError, TypeError):
            return "Please specify a valid number of months."

        curr_expiry_str = record.get("expiry_date")
        if curr_expiry_str:
            try:
                curr_expiry = date.fromisoformat(curr_expiry_str)
                base_date = curr_expiry if curr_expiry >= today else today
            except ValueError:
                base_date = today
        else:
            base_date = today
        target_expiry = _add_months(base_date, months)
    elif record.get("renewal_cycle"):
        cycle = record["renewal_cycle"].strip().lower()
        cycle_map = {
            "monthly": 1,
            "quarterly": 3,
            "yearly": 12,
            "annual": 12,
            "6-month": 6,
            "semi-annual": 6,
        }
        if cycle in cycle_map:
            months = cycle_map[cycle]
            curr_expiry_str = record.get("expiry_date")
            if curr_expiry_str:
                try:
                    curr_expiry = date.fromisoformat(curr_expiry_str)
                    base_date = curr_expiry if curr_expiry >= today else today
                except ValueError:
                    base_date = today
            else:
                base_date = today
            target_expiry = _add_months(base_date, months)
        else:
            return f"How long would you like to renew {record['name']} for?"
    else:
        return f"How long would you like to renew {record['name']} for?"

    target_reminder = target_expiry - timedelta(days=30)
    new_expiry_str = target_expiry.isoformat()
    new_reminder_str = target_reminder.isoformat()

    updates: Dict[str, Any] = {
        "expiry_date": new_expiry_str,
        "reminder_date": new_reminder_str,
    }

    if amount is not None:
        try:
            amt = float(amount)
            if amt < 0:
                return "Amount cannot be negative."
            updates["amount"] = round(amt, 2)
        except (ValueError, TypeError):
            return "Please provide a valid amount."

    storage.update_record(record["id"], updates)
    return f"Renewed {record['name']}: new expiry is {new_expiry_str} and reminder is set for {new_reminder_str}."


@mcp.tool()
@_handle_storage_errors
def morning_brief() -> str:
    """Provide a short spoken morning summary of upcoming deadlines, recent expirations, and bill anomalies."""
    upcoming = storage.list_upcoming(7)
    expired = storage.list_expired(14)
    anomalies, _ = _detect_bill_anomalies()

    today = date.today()
    items: List[str] = []

    for item in upcoming:
        items.append(_format_upcoming_speech(item, today))

    for item in expired:
        items.append(_format_expired_speech(item, today))

    for a in anomalies:
        items.append(a["message"])

    total = len(items)
    if total == 0:
        return "Good morning! You have no upcoming deadlines, recent expirations, or bill anomalies."

    if total <= 5:
        # Each item is a natural sentence/clause; join them cleanly
        formatted_items = []
        for it in items:
            it = it.strip().rstrip(".")
            formatted_items.append(it)
        return ". ".join(formatted_items) + "."

    shown = [it.strip().rstrip(".") for it in items[:5]]
    remaining = total - 5
    return ". ".join(shown) + f", and {remaining} more."


@mcp.tool()
@_handle_storage_errors
def draft_warranty_claim(item: str) -> str:
    """Draft a ready-to-send warranty claim email using stored record details."""
    clean_item = item.strip() if item else ""
    if not clean_item:
        return "Please specify an item to draft a warranty claim for."

    matches = storage.search_records(clean_item)
    warranty_matches = [m for m in matches if m.get("type") == "warranty"]

    if not warranty_matches:
        if matches:
            return f"I found {matches[0]['name']}, but it is not recorded as a warranty."
        return f"I couldn't find any warranty records for '{clean_item}'."

    if len(warranty_matches) > 1:
        names = [m["name"] for m in warranty_matches]
        return _format_clarification(names)

    record = warranty_matches[0]
    today = date.today()

    expired_prefix = ""
    expiry_str = record.get("expiry_date")
    if expiry_str:
        try:
            exp_date = date.fromisoformat(expiry_str)
            if exp_date < today:
                expired_prefix = f"Notice: The warranty for {record['name']} expired on {expiry_str}.\n\n"
        except ValueError:
            pass

    item_name = record.get("name") or "[item name]"
    vendor = record.get("vendor") or "[vendor/manufacturer]"
    purchase_date = record.get("purchase_date") or "[purchase date]"
    if record.get("amount") is not None:
        amount_val = record["amount"]
        price = f"${int(amount_val)}" if isinstance(amount_val, (int, float)) and float(amount_val).is_integer() else f"${amount_val:.2f}"
    else:
        price = "[purchase price]"
    warranty_expiry = expiry_str or "[warranty expiration date]"

    return (
        f"{expired_prefix}"
        f"Subject: Warranty Claim - {item_name}\n\n"
        f"Dear {vendor} Support Team,\n\n"
        f"I am writing to file a warranty claim for my {item_name}, purchased on {purchase_date} "
        f"for {price}. The recorded warranty expiration date is {warranty_expiry}.\n\n"
        f"Issue Description:\n"
        f"[describe the problem]\n\n"
        f"Please let me know the required next steps to process this claim, repair, or replacement.\n\n"
        f"Thank you,\n"
        f"[your name]\n"
        f"[your contact information]\n\n"
        f"Note: This is a draft and not legal advice."
    )


@mcp.tool()
@_handle_storage_errors
def bill_anomalies(name: Optional[str] = None) -> str:
    """Check for bill anomalies where the latest amount exceeds the earlier median by > 25%."""
    clean_name = name.strip() if name and name.strip() else None
    anomalies, override = _detect_bill_anomalies(clean_name)
    if override:
        return override
    if not anomalies:
        if clean_name:
            return f"No unusual bill amounts detected for {clean_name}."
        return "No unusual bill amounts detected."
    return " ".join(a["message"] for a in anomalies)


if __name__ == "__main__":
    # Start server using Streamable HTTP transport on http://localhost:8000/mcp
    mcp.run(
        transport="streamable-http",
        host="127.0.0.1",
        port=8000,
        streamable_http_path="/mcp",
    )
