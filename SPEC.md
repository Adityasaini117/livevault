# LifeVault

Voice-first life-admin assistant exposed to Alexa+ as an Model Context Protocol (MCP) server.

**Tagline**: *"Never miss a warranty, renewal, or deadline again."*

LifeVault securely stores a person's private life-admin records (warranties, subscriptions, insurance, bills, documents) and answers questions about them. Alexa+ cannot do this alone because it has no access to the user's structured private records or deadlines.

---

## Tech Stack

- **Language & Runtime**: Python 3.10+
- **Protocol**: MCP Python SDK (FastMCP), Streamable HTTP transport (spec 2025-11-25 or later) hosted at `http://localhost:8000/mcp`
- **Storage Layer**: SQLite (`lifevault.db`) behind an abstract `Storage` interface (designed to be swapped for DynamoDB later)
- **Planned AWS Services**: Amazon DynamoDB, Amazon Bedrock, Amazon S3, Amazon Textract, Amazon SNS

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
