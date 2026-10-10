"""LifeVault - MCP Server.

Provides voice-first life-admin assistant tools over Streamable HTTP transport.
Exposed to Alexa+ as an MCP server.
"""

import calendar
from datetime import date, datetime, timedelta
from pathlib import Path
import sys
from typing import Optional

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
from storage import SqliteStorage, VALID_TYPES

# Initialize storage and MCP server
storage = SqliteStorage()
mcp = FastMCP("LifeVault")


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


@mcp.tool()
def ping() -> str:
    """Return health check status for LifeVault."""
    return "LifeVault is alive"


@mcp.tool()
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


if __name__ == "__main__":
    # Start server using Streamable HTTP transport on http://localhost:8000/mcp
    mcp.run(
        transport="streamable-http",
        host="127.0.0.1",
        port=8000,
        streamable_http_path="/mcp",
    )
