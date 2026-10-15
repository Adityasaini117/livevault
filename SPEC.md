# LifeVault

Voice-first life-admin assistant exposed to Alexa+ as an Model Context Protocol (MCP) server.

**Tagline**: *"Never miss a warranty, renewal, or deadline again."*

LifeVault securely stores a person's private life-admin records (warranties, subscriptions, insurance, bills, documents) and answers questions about them. Alexa+ cannot do this alone because it has no access to the user's structured private records or deadlines.

---

## Tech Stack

- **Language & Runtime**: Python 3.10+
- **Protocol**: MCP Python SDK (FastMCP), Streamable HTTP transport (spec 2025-11-25 or later) hosted at `http://localhost:8000/mcp`
- **Storage Layer**: Pluggable storage behind the abstract `Storage` interface supporting SQLite (`lifevault.db`) for local development and Amazon DynamoDB for cloud deployment, selectable via `STORAGE_BACKEND`.
- **AWS Services**: Amazon DynamoDB (single-table records storage), Amazon Bedrock (Converse API AI extraction), AWS Lambda (Function URL deployment with Mangum ASGI adapter)

---

## AI Provider

LifeVault includes a pluggable AI extraction interface in `/server/ai.py` that parses unstructured natural-language requests into structured life-admin records:
- **Google Gemini**: The default free provider using the official `google-genai` SDK and current Flash models (e.g. `gemini-2.5-flash`), configured via `GEMINI_API_KEY` and `GEMINI_MODEL`.
- **AWS Bedrock**: The enterprise AWS provider option behind the exact same interface using `boto3` Bedrock-Runtime Converse API, configured via `BEDROCK_MODEL_ID` and `AWS_REGION`.

---

## Tools

- `ping()`: Health check confirming the LifeVault MCP server is online.
- `add_record(type, name, amount, purchase_date, warranty_months, renewal_cycle, vendor, notes)`: Saves a record, computes expiry date and 30-day reminder date, and returns a spoken confirmation.
- `add_record_from_text(text)`: Natural-language extractor that parses free-form voice input, computes deadlines, and saves the record. Asks clarifying questions if the name or type is unclear.
- `find_record(query)`: Searches records by name, vendor, or notes. Asks clarifying questions if multiple matches exist.
- `warranty_status(item)`: Reports whether an item is under warranty, expiry date, and days remaining or days since expired.
- `upcoming_deadlines(days=30)`: Lists upcoming warranties, renewals, bills, and document expiries due in that window (soonest first, max 5 spoken items).
- `spending_summary(period)`: Summarizes total spend and top spending category for "this month", "last month", or "this year".
- `delete_record(name, confirm=False)`: Asks for explicit confirmation before permanently deleting any record.
- `renew_record(name, extend_months=None, new_expiry_date=None, amount=None)`: Renews an existing record, recalculates the expiry and 30-day reminder date, optionally updates the amount, and returns a spoken confirmation.
- `morning_brief()`: Delivers a short spoken daily summary covering deadlines due in the next 7 days, items expired in the last 14 days, and detected bill anomalies.
- `draft_warranty_claim(item)`: Generates a ready-to-send warranty claim email draft using strictly stored details, with placeholders for unknown fields and expiration notices.
- `bill_anomalies(name=None)`: Detects recurring bill spikes by comparing the latest bill against the median of at least 3 earlier bills (> 25% threshold).
- `export_my_data()`: Exports all stored life-admin records for the current user as concise JSON, capped at 100 records to prevent blowing conversational context.
- `delete_all_data(confirm=False)`: Permanently deletes all records belonging to the default user after explicit user confirmation without dropping or altering database tables.

---

## Privacy Guardrails

LifeVault implements strict privacy filters to prevent storing or sending sensitive financial and identity credentials:
- **Sensitive-Data Filter**: Rejects card-number-like digit runs (Luhn-valid 13–19 digits), CVV/PIN/password/OTP phrasing, bank account/IBAN patterns, and SSN/Aadhaar/passport IDs.
- **Friendly Voice Rejection**: Returns `"I can't store card numbers, passwords or ID numbers. Tell me just the item and dates."` whenever sensitive data is intercepted.
- **Strict Redaction**: Matched values are never echoed, logged, or stored, and are excluded from exception messages.
- **Pre-Execution Boundary**: Sensitive-data checks execute prior to making any external AI provider API calls or database writes.
- **Non-Destructive Table Deletions**: `delete_all_data(confirm=True)` deletes only items under partition key `USER#default` (or executes `DELETE FROM records` in SQLite) and never drops the database table.
- **Filter Limitations**: The privacy guardrail filter is pattern- and heuristic-based (regex and checksum algorithms) and is not guaranteed to catch every conceivable format, obfuscation, or novel identifier. Users should never speak or submit passwords, financial account credentials, or government ID numbers.

---

## Access Protection

LifeVault includes an ASGI middleware layer for the Streamable HTTP transport:
- **Authentication**: When `LIFEVAULT_API_TOKEN` is set, all incoming HTTP requests must include `Authorization: Bearer <token>`.
- **Constant-Time Verification**: Tokens are compared using `hmac.compare_digest` to prevent timing attacks.
- **Fail-Secure**: Returns HTTP 401 with JSON `{"error": "Unauthorized"}` if missing or incorrect. Never logs tokens or authorization headers.
- **Development Fallback**: If `LIFEVAULT_API_TOKEN` is unset or blank, requests are permitted with a visible startup console warning.

---

## AWS Usage

LifeVault supports Amazon DynamoDB as an enterprise, cloud-native storage backend selectable via `STORAGE_BACKEND=dynamodb`.

### Table Architecture
- **Single-Table Design**: A single table (`DYNAMODB_TABLE`, default `lifevault-records`) stores all records and metadata.
- **Partition Key (`pk`)**: String attribute fixed to `USER#default` for single-user administration.
- **Sort Key (`sk`)**: String attribute formatted as `REC#` plus a zero-padded 10-digit ID (e.g. `REC#0000000001`).
- **Atomic ID Generation**: An item with `pk="USER#default"` and `sk="COUNTER"` uses DynamoDB's atomic `ADD last_id :inc` expression to assign monotonically increasing integer IDs.
- **Data Integrity**: Monetary amounts are stored as DynamoDB `Decimal` types and automatically converted to `float` on read. Attributes with `None` values are omitted on write and restored on read.
- **Queries**: Records are fetched using a Partition Query (`pk="USER#default"` and `sk begins_with "REC#"`), with in-code filtering for dates, categories, and full-text searches.

### Why DynamoDB Was Chosen
1. **Serverless & Zero Idle Cost**: With `PAY_PER_REQUEST` (on-demand) billing, there are no hourly server fees or minimum provisioned capacity. Storage and requests scale to zero when idle.
2. **Predictable Single-Digit Millisecond Latency**: Delivers low-latency reads and writes critical for fast Alexa+ voice interactions.
3. **Pluggable Architecture**: Implements the identical abstract `Storage` interface as `SqliteStorage`, allowing seamless local testing and deployment with zero changes to tool logic.
4. **Resilience & Maintenance**: Managed high availability across Availability Zones with automated backups and atomic updates.

---

## Hero Moment

The user says: *"I bought a laptop for 900 dollars, two year warranty."*  
The server creates a record, calculates the warranty end date, and sets a reminder date 30 days before expiry. Later the user asks: *"Is my laptop still under warranty?"* and gets an exact spoken answer with days remaining.

---

## Voice Interaction Rules

- **Short speech-friendly answers**: Keep responses concise and natural for Alexa+ voice output.
- **Clarify ambiguities**: When a query or name matches multiple records, ask a clarifying question listing the options.
- **Confirm risky actions**: Always require explicit user confirmation before deleting any record.
- **Never invent records**: Strictly answer from verified stored records.
- **Clear not-found messages**: Clearly state when no matching record or deadline is found.
- **Record-keeping disclaimer**: LifeVault is a personal record-keeping tool, not legal or financial advice.
