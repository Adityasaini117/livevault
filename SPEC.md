\# StockPilot AI

Voice-first operations assistant for small repair workshops, exposed to Alexa+ as an MCP server.



\## Tech

\- Python, official MCP Python SDK (FastMCP), Streamable HTTP transport, spec 2025-11-25 or later

\- Storage: SQLite behind a storage interface (swap to DynamoDB later)

\- AWS: DynamoDB, Bedrock, SNS/SES, hosted on AWS



\## Tools

\- log\_usage(part, qty, job\_id): deduct stock, attach to job, check threshold, forecast run-out, suggest reorder

\- check\_stock(part)

\- job\_status(job\_id)

\- find\_shortages()

\- forecast\_runout(part)

\- draft\_reorder(): draft only, never send without confirmation

\- add\_stock(part, qty)



\## Hero moment

"Used two brake pads and one oil filter on job 51" triggers:

deduct stock, attach to job 51, flag low stock, forecast run-out date, offer a reorder draft.



\## Rules

\- Confirm before risky actions

\- Ask when a part name is ambiguous

\- Short answers suitable for speech

\- Seed data: 30 parts, 10 jobs, 90 days of usage history



