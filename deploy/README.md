# LifeVault AWS Lambda Deployment Guide

This guide details how to deploy the LifeVault MCP server to AWS Lambda in **`ap-southeast-2` (Sydney)** behind a **Lambda Function URL** (Streamable HTTP over HTTPS) backed by **Amazon DynamoDB**.

---

## Architecture Overview

```
                                      AWS Cloud (ap-southeast-2)
                                   +-----------------------------------------------+
+------------------+  HTTPS POST   |  +--------------------+                       |
| Alexa+ / Client  | ------------> |  | Lambda Function URL|                       |
| / Simulator      |  Bearer Auth  |  +---------+----------+                       |
+------------------+               |            |                                  |
                                   |            v                                  |
                                   |  +--------------------+                       |
                                   |  |   Mangum Adapter   | (ASGI Lifespan)       |
                                   |  +---------+----------+                       |
                                   |            |                                  |
                                   |            v                                  |
                                   |  +--------------------+                       |
                                   |  | Token Auth Middlew.| (Fails closed on 401) |
                                   |  +---------+----------+                       |
                                   |            |                                  |
                                   |            v                                  |
                                   |  +--------------------+                       |
                                   |  |  FastMCP Server    | (Stateless JSON Mode) |
                                   |  +---------+----------+                       |
                                   |            |                                  |
                                   |            v                                  |
                                   |  +--------------------+                       |
                                   |  |  DynamoDB Storage  |                       |
                                   |  +---------+----------+                       |
                                   |            |                                  |
                                   |            v                                  |
                                   |  +--------------------+                       |
                                   |  | lifevault-records  | (Single-Table Design) |
                                   |  +--------------------+                       |
                                   +-----------------------------------------------+
```

- **Transport:** Streamable HTTP / JSON-RPC over HTTPS via Lambda Function URL (`/mcp`).
- **Runtime:** Python 3.13 (`python3.13`, `x86_64`).
- **Security:** Function URL Auth is `NONE`; endpoint access is protected by constant-time Bearer token verification in `ApiTokenAuthMiddleware`. In `LAMBDA_MODE=1`, if `LIFEVAULT_API_TOKEN` is unset, the server fails closed (rejects all requests with `401 Unauthorized`).
- **No Additional Services:** Only AWS Lambda and DynamoDB.

---

## 1. Build Deployment Package

Build `deploy/package.zip` on your workstation using PowerShell:

```powershell
.\deploy\build.ps1
```

The build script:
- Resolves and bundles dependencies for `manylinux2014_x86_64` on Python 3.13.
- Excludes AWS-provided libraries (`boto3`, `botocore`, `s3transfer`) and test suites.
- Validates that no `.env*`, `*.db`, `tests`, or credentials are packaged.
- Verifies package size is well below the 50 MB direct upload threshold (~12 MB).

---

## 2. AWS Console Setup Steps (Region: `ap-southeast-2`)

> **IMPORTANT:** Ensure your AWS Management Console region is set to **Asia Pacific (Sydney) `ap-southeast-2`** for all resources.

### Step 2.1: Verify or Create DynamoDB Table
1. Open **Amazon DynamoDB** console in `ap-southeast-2`.
2. Click **Create table**:
   - **Table name:** `lifevault-records`
   - **Partition key (`pk`):** `String`
   - **Sort key (`sk`):** `String`
   - **Table settings:** Select **Customize settings** -> **On-demand** (Pay-per-request).
3. Click **Create table** and wait for table status to become `Active`.
4. Copy the table ARN (e.g. `arn:aws:dynamodb:ap-southeast-2:<ACCOUNT_ID>:table/lifevault-records`).

### Step 2.2: Create IAM Policy & Execution Role
1. Open **IAM** console -> **Policies** -> **Create policy**.
2. Switch to the **JSON** editor and paste the least-privilege policy (replace `<ACCOUNT_ID>` with your AWS Account ID):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DynamoDBTableAccess",
      "Effect": "Allow",
      "Action": [
        "dynamodb:Query",
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:UpdateItem",
        "dynamodb:DeleteItem",
        "dynamodb:BatchWriteItem"
      ],
      "Resource": "arn:aws:dynamodb:ap-southeast-2:<ACCOUNT_ID>:table/lifevault-records"
    },
    {
      "Sid": "CloudWatchLogsAccess",
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "arn:aws:logs:ap-southeast-2:<ACCOUNT_ID>:*"
    }
  ]
}
```

3. Name the policy `LifeVaultLambdaExecutionPolicy` and save.
4. Go to **Roles** -> **Create role**:
   - **Trusted entity type:** AWS service -> **Lambda**.
   - **Permissions policies:** Attach `LifeVaultLambdaExecutionPolicy`.
   - **Role name:** `LifeVaultLambdaExecutionRole`.
5. Create the role.

### Step 2.3: Create Lambda Function
1. Open **AWS Lambda** console in `ap-southeast-2`.
2. Click **Create function**:
   - **Author from scratch**
   - **Function name:** `lifevault-mcp`
   - **Runtime:** `Python 3.13`
   - **Architecture:** `x86_64`
   - **Permissions:** Change default execution role -> **Use an existing role** -> Select `LifeVaultLambdaExecutionRole`.
3. Click **Create function**.

### Step 2.4: Configure General Settings & Handler
1. In the function page, go to the **Configuration** tab -> **General configuration** -> **Edit**:
   - **Memory:** `512 MB`
   - **Timeout:** `0 min 30 sec`
2. Save changes.
3. Under the **Code** tab, scroll to **Runtime settings** -> **Edit**:
   - **Handler:** `lambda_handler.lambda_handler`
4. Save changes.

### Step 2.5: Upload Zip Package
1. In the **Code** tab, click **Upload from** -> **.zip file**.
2. Click **Upload**, select `deploy/package.zip` from your local machine, and click **Save**.

### Step 2.6: Configure Environment Variables
1. Go to **Configuration** tab -> **Environment variables** -> **Edit**.
2. Add the following variables (never commit or hardcode secrets):

| Key | Example Value | Description |
| :--- | :--- | :--- |
| `LAMBDA_MODE` | `1` | Enables stateless mode, JSON responses, Function URL DNS compatibility, and fail-closed auth |
| `STORAGE_BACKEND` | `dynamodb` | Selects the DynamoDB backend |
| `DYNAMODB_TABLE` | `lifevault-records` | Table name in `ap-southeast-2` |
| `LIFEVAULT_API_TOKEN` | `<GENERATE_A_STRONG_RANDOM_SECRET>` | Shared Bearer authentication token |
| `AI_PROVIDER` | `gemini` | `gemini` (default) or `bedrock` |
| `GEMINI_API_KEY` | `<YOUR_GEMINI_API_KEY>` | Required if `AI_PROVIDER=gemini` |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Gemini extraction model |

*(Note: `AWS_REGION` is automatically provided by the Lambda runtime as `ap-southeast-2`.)*
3. Click **Save**.

### Step 2.7: Create Function URL
1. In the function page, go to **Configuration** tab -> **Function URL** -> **Create function URL**.
2. Configure settings:
   - **Auth type:** `NONE` *(Public HTTPS endpoint; protected by Bearer token middleware)*
   - **Configure cross-origin resource sharing (CORS):** Checked (optional, recommended)
     - **Allow origin:** `*`
     - **Allow headers:** `authorization, content-type, accept`
     - **Allow methods:** `POST, GET, OPTIONS`
3. Click **Save**.
4. Copy the **Function URL** (format: `https://<url-id>.lambda-url.ap-southeast-2.on.aws/`).

---

## 3. Verification & Testing

### 3.1 Test with `curl.exe` (PowerShell)

> **SECURITY:** Always assign the secret token and URL to local session variables. Never type tokens inline into command history.

```powershell
# Set test variables in current shell session
$URL = "https://<url-id>.lambda-url.ap-southeast-2.on.aws/mcp"
$TOKEN = "your-configured-lifevault-token"

# 1. Test 401 Unauthorized (Missing token)
curl.exe -i -X POST $URL `
  -H "Content-Type: application/json" `
  -H "Accept: application/json" `
  -d '{"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}'

# Expected: HTTP/1.1 401 Unauthorized with 'WWW-Authenticate: Bearer'

# 2. Test 200 OK (Authorized tools/list)
curl.exe -i -X POST $URL `
  -H "Authorization: Bearer $TOKEN" `
  -H "Content-Type: application/json" `
  -H "Accept: application/json" `
  -d '{"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}'

# Expected: HTTP/1.1 200 OK returning JSON-RPC result with list of LifeVault tools:
# ["ping", "add_record", "add_record_from_text", "find_record", "warranty_status",
#  "upcoming_deadlines", "spending_summary", "delete_record", "renew_record",
#  "morning_brief", "draft_warranty_claim", "bill_anomalies"]
```

### 3.2 Test via LifeVault Simulator

Without modifying `/simulator`, connect the interactive voice simulator to your deployed Lambda Function URL:

```powershell
# In PowerShell:
$env:MCP_SERVER_URL = "https://<url-id>.lambda-url.ap-southeast-2.on.aws/mcp"
$env:LIFEVAULT_API_TOKEN = $TOKEN

# Run the simulator
python simulator\simulator.py
```

### 3.3 Check CloudWatch Logs

1. In the Lambda function page, open the **Monitor** tab and click **View CloudWatch logs**.
2. Select the latest log stream:
   - Verify cold-start initialization messages:
     ```
     StreamableHTTP session manager started
     ```
   - Verify request completion logs (`POST /mcp 200`).
   - Confirm that no Authorization headers, raw tokens, or secrets appear in the logs.

---

## Common Errors & Troubleshooting

| Error | Root Cause | Solution |
| :--- | :--- | :--- |
| **HTTP 421 Misdirected Request** (`Invalid Host header`) | FastMCP's DNS rebinding protection rejected the Function URL host header (`*.lambda-url.ap-southeast-2.on.aws`). | Ensure `LAMBDA_MODE=1` is set in Lambda environment variables. `lambda_handler.py` automatically disables DNS rebinding checks when `LAMBDA_MODE=1` (Bearer auth is the security boundary). |
| **HTTP 401 Unauthorized** | The `Authorization` header is missing, malformed, contains an incorrect token, or `LIFEVAULT_API_TOKEN` is unset in Lambda environment variables. | Verify that `LIFEVAULT_API_TOKEN` in Lambda matches `$TOKEN` exactly, and that the header is formatted as `Bearer <token>`. When `LAMBDA_MODE=1` and token is unset, the server fails closed. |
| **HTTP 502 Bad Gateway** (`Process exited before completing request` or `Runtime.ImportModuleError`) | Missing wheel, binary incompatibility, or wrong handler path. | Ensure `deploy/package.zip` was built using `.\deploy\build.ps1` with Python 3.13 and `--platform manylinux2014_x86_64`. Confirm Runtime settings handler is `lambda_handler.lambda_handler`. Check CloudWatch logs for the exact Python stack trace. |
| **HTTP 500 / `LifespanFailure`** (`StreamableHTTPSessionManager.run() can only be called once`) | A single-use FastMCP session manager was reused across multiple warm Lambda invocations. | Resolved by `deploy/lambda_handler.py`, which generates a fresh ASGI app per invocation so warm invocations always succeed. |
| **Lambda Timeout (30s)** | Lambda cannot reach DynamoDB or is waiting on network connection due to incorrect region or IAM permissions. | Verify the DynamoDB table ARN uses `ap-southeast-2` and matches your AWS Account ID. Verify the IAM execution role has `dynamodb:Query`, `dynamodb:GetItem`, `dynamodb:PutItem`, etc. |
