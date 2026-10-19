# Developer Experience (DX) & Friction Log

This log documents real developer friction encountered while building, testing, and packaging **LifeVault** (Streamable HTTP MCP Server + Alexa+ Simulator + AWS DynamoDB/Lambda integrations) during the hackathon window. Each entry includes the task attempted, steps taken, expected vs. actual behavior, severity rating, workaround applied, and an actionable suggestion for the ecosystem teams.

---

## 1. MCP Inspector: OAuth / Dynamic Client Registration Failure on Bearer-Token Server
- **Task Attempted:** Testing our Streamable HTTP MCP server (`http://localhost:8000/mcp`) protected by simple Bearer token authentication (`ApiTokenAuthMiddleware`) using the official MCP Inspector.
- **Steps Taken:** Launched the LifeVault MCP server with `LIFEVAULT_API_TOKEN` enabled, opened MCP Inspector, configured the Streamable HTTP endpoint URL, and entered our custom `Authorization: Bearer <token>` header.
- **Expected vs. Actual:**
  - *Expected:* MCP Inspector should send the configured `Authorization: Bearer <token>` header directly to `/mcp` and list/invoke the 14 registered tools.
  - *Actual:* When the server returned an initial `401 Unauthorized` or lacked OAuth discovery metadata, MCP Inspector immediately attempted OAuth / Dynamic Client Registration (DCR) discovery endpoints (`/.well-known/oauth-authorization-server`), threw OAuth/DCR errors, and never retried requests using the explicitly supplied static `Authorization` header[cite: 6].
- **Severity:** **High**[cite: 6]
- **Workaround Used:** Bypassed MCP Inspector for authenticated testing by verifying endpoints via `curl` commands and building our own standalone **Alexa+ Web Simulator** (`lifevault-alexa-simulator`) with native static Bearer token support[cite: 6].
- **Actionable Suggestion:** Add an explicit `"Auth Mode: Static Bearer Token (Disable OAuth Discovery)"` toggle in MCP Inspector so developers testing simple pre-shared API token middleware aren't blocked by automatic OAuth/DCR handshakes[cite: 6].

---

## 2. AWS Free Plan Region Restriction (`ap-southeast-2`) vs. Documentation Defaults (`us-east-1`)
- **Task Attempted:** Provisioning our Amazon DynamoDB single-table backend (`lifevault-records`) and testing cloud integrations on a newly created AWS Free Plan account[cite: 6].
- **Steps Taken:** Followed standard AWS starter documentation and SDK examples that default to `us-east-1` (N. Virginia)[cite: 6].
- **Expected vs. Actual:**
  - *Expected:* Either `us-east-1` works out of the box, or the account onboarding clearly warns that resources must be provisioned in a specific home region[cite: 6].
  - *Actual:* Requests in `us-east-1` failed with authorization/region restriction errors because the AWS Free Plan account was locked to `ap-southeast-2` (Sydney), while documentation and sample snippets assumed `us-east-1`[cite: 6].
- **Severity:** **Medium**[cite: 6]
- **Workaround Used:** Parameterized `AWS_REGION` across `server/storage_dynamodb.py` and `server/create_table.py`, defaulting our DynamoDB configuration to `ap-southeast-2`[cite: 6].
- **Actionable Suggestion:** Display a prominent banner during AWS Free Plan sign-up and in the AWS Console header indicating the account's locked region, and update hackathon starter templates to read `AWS_REGION` dynamically rather than hardcoding `us-east-1`[cite: 6].

---

## 3. `aws configure` Prompt Ordering & Unexpected AWS MCP CLI Prompt
- **Task Attempted:** Configuring local AWS CLI credentials to connect `boto3` with DynamoDB and Lambda[cite: 6].
- **Steps Taken:** Ran `aws configure` in the terminal and began pasting credentials[cite: 6].
- **Expected vs. Actual:**
  - *Expected:* Clear validation on each prompt step so Access Key ID, Secret Access Key, region, and output format cannot be accidentally swapped, matching classic `aws configure` documentation[cite: 6].
  - *Actual:* The interactive prompts are easy to mix up if pasting quickly (no format validation warning if a region or key is pasted into the wrong prompt), and newer AWS CLI versions introduce an extra, unexpected AWS MCP configuration question at the end that isn't covered in standard setup guides[cite: 6].
- **Severity:** **Low**[cite: 6]
- **Workaround Used:** Re-ran `aws configure` carefully and manually verified `~/.aws/credentials` and `~/.aws/config`.
- **Actionable Suggestion:** Add basic regex validation to `aws configure` interactive inputs (e.g., warning if an Access Key ID doesn't start with `AKIA`/`ASIA`) and document the new CLI MCP prompt in onboarding guides[cite: 6].

---

## 4. Background Agent Process Holding Port 8000 (Socket Bind Conflicts)
- **Task Attempted:** Restarting the local FastMCP Streamable HTTP server (`python server/server.py`) on port `8000` during iterative development[cite: 6].
- **Steps Taken:** Used an AI coding agent during prototyping (as encouraged by the hackathon guidelines) which spawned a background server verification process, then attempted to start the server manually in a separate terminal[cite: 6].
- **Expected vs. Actual:**
  - *Expected:* Clean termination of background test servers after health checks complete, or a clear diagnostic message indicating which PID owns port `8000`.
  - *Actual:* The AI agent's background process continued holding port `8000` silently, causing subsequent runs to fail with `Errno 10048` / address-already-in-use bind errors[cite: 6].
- **Severity:** **Medium**[cite: 6]
- **Workaround Used:** Located and killed the orphaned Python process via PowerShell (`Get-NetTCPConnection -LocalPort 8000` / `Stop-Process`) before restarting.
- **Actionable Suggestion:** Agentic IDEs and MCP server runners should automatically release background ports after verification or include a `--kill-existing` / auto-port-fallback flag in FastMCP dev mode[cite: 6].

---

## 5. Mismatched MCP Inspector Port & `npx` Instructions in Agent Guidance
- **Task Attempted:** Connecting local diagnostic tools to the running MCP server following AI assistant instructions[cite: 6].
- **Steps Taken:** Followed generated troubleshooting steps that assumed a fresh `npx @modelcontextprotocol/inspector` instance listening on port `5173`[cite: 6].
- **Expected vs. Actual:**
  - *Expected:* Tooling instructions should reflect the actual active ports and running simulator/inspector processes in the workspace[cite: 6].
  - *Actual:* The instructions referenced port `5173` and a fresh `npx` command that did not match our active local setup (`localhost:8000` for MCP and `localhost:8080` for the FastAPI simulator)[cite: 6].
- **Severity:** **Low**[cite: 6]
- **Workaround Used:** Documented the exact port architecture (`8000` for `/mcp`, `8080` for simulator UI) explicitly in `README.md` and `simulator/README.md`.
- **Actionable Suggestion:** Standardize port conventions across MCP starter kits and provide a unified `docker-compose` or single-command dev runner.

---

## 6. Stale Running MCP Server vs. Passing Unit Tests (No Default Hot-Reload)
- **Task Attempted:** Verifying newly added MCP tools (`morning_brief`, `bill_anomalies`, privacy filters) against live HTTP requests after unit tests passed[cite: 6].
- **Steps Taken:** Ran `pytest` (all tests passed), then immediately tested the live `/mcp` endpoint from the simulator client[cite: 6].
- **Expected vs. Actual:**
  - *Expected:* The running local development server should auto-reload when `server/server.py` changes, matching standard FastAPI (`uvicorn --reload`) behavior[cite: 6].
  - *Actual:* `pytest` imported the latest code directly and passed, while the background `python server/server.py` process was still serving stale code in memory without auto-reloading, causing live client calls to fail until a manual restart[cite: 6].
- **Severity:** **Medium**[cite: 6]
- **Workaround Used:** Manually restarted `python server/server.py` after every tool update.
- **Actionable Suggestion:** Enable file-watching / hot-reload by default when running FastMCP servers in local development mode[cite: 6].

---

## 7. Accidental Secret Insertion in `.env.example` & GitHub Push Protection (Positive DX Highlight)
- **Task Attempted:** Generating `.env.example` templates and committing repository updates via an AI coding agent[cite: 7].
- **Steps Taken:** Allowed the agent to update configuration templates and run git commands in the terminal[cite: 7].
- **Expected vs. Actual:**
  - *Expected:* `.env.example` should only ever contain placeholder strings, and malformed terminal commands shouldn't create stray untracked files[cite: 7].
  - *Actual:* The agent accidentally copied a real API key into `.env.example` and created stray files from truncated shell commands (`tatus`, `h -u origin main`)[cite: 7]. However, **GitHub Push Protection** immediately intercepted and blocked the push before the key could leak publicly (a massive positive security win)[cite: 7].
- **Severity:** **High** *(with a strong positive note for GitHub Push Protection)*[cite: 7]
- **Workaround Used:** Removed the stray files, scrubbed the secret from commit history, rotated the exposed API key, hardened `.gitignore` (`.env*`, `.aws/`), and verified zero secrets exist in git history[cite: 7].
- **Actionable Suggestion:** AI coding assistants should enforce a pre-write secret scanner on tracked files (especially `.env.example`), while hackathon starter repos should ship with pre-commit secret-detection hooks enabled by default[cite: 7].

---

## 8. AWS Lambda Console Defaults: ARM64, Python 3.14 vs. 3.13 Mismatch, and IAM Role UX
- **Task Attempted:** Packaging and configuring our ASGI Lambda deployment (`deploy/lambda_handler.py` & `deploy/package.zip`) in the AWS Lambda Console[cite: 7].
- **Steps Taken:** Built `deploy/package.zip` targeting `python3.13` (`manylinux2014_x86_64`) via `deploy/build.ps1` and navigated to the AWS Lambda Console to configure the function[cite: 7].
- **Expected vs. Actual:**
  - *Expected:* Clear alignment between default console architecture/runtime selections and common Python binary wheels, plus intuitive IAM execution role selection for DynamoDB access[cite: 7].
  - *Actual:* Ran into three console friction points simultaneously: (1) an ARM64 toggle/promotion that conflicts with `x86_64` native wheels if overlooked, (2) Python 3.14 appearing as the default runtime while our compiled dependencies targeted Python 3.13, and (3) an unclear custom IAM role selection card when trying to attach DynamoDB permissions[cite: 7].
- **Severity:** **Medium**[cite: 7]
- **Workaround Used:** Explicitly pinned `--platform manylinux2014_x86_64 --python-version 3.13` in `deploy/build.ps1`, documented the exact runtime/architecture requirements in `deploy/README.md`, and verified the handler locally via `tests/test_lambda_handler.py`[cite: 7].
- **Actionable Suggestion:** When a user uploads a `.zip` containing native binary wheels (e.g., `.so` files with `cpython-313-x86_64` tags), the Lambda Console could inspect the archive filenames and warn if the selected Runtime (3.14) or Architecture (ARM64) mismatches the package[cite: 7].

---

## 9. Initial AWS Lambda Deployment Attempt Delayed by AWS Service Issue
- **Task Attempted:** Deploying and testing the packaged Lambda function during our cloud integration window[cite: 7].
- **Steps Taken:** Uploaded the package and attempted to provision/invoke the Lambda resource in the console[cite: 7].
- **Expected vs. Actual:**
  - *Expected:* Immediate function creation and invocation feedback.
  - *Actual:* Our first Lambda deployment attempt was delayed by a transient AWS service outage/degradation, making it difficult to tell initially whether the failure was caused by our Mangum ASGI zip package or AWS infrastructure[cite: 7].
- **Severity:** **Medium**[cite: 7]
- **Workaround Used:** Built a local unit test suite (`tests/test_lambda_handler.py` with 7 Function URL & auth tests) and used `moto.mock_aws` (`tests/test_storage_contract.py`) so we could deterministically verify Lambda and DynamoDB behavior offline without being blocked by cloud availability.
- **Actionable Suggestion:** Surface real-time regional AWS Health status alerts directly inside the Lambda function creation banner when elevated error rates are occurring.

---

## 10. Generic "Key Missing" Error on Empty Simulator `.env` After Key Rotation
- **Task Attempted:** Running the Alexa+ Web Simulator (`simulator/app.py`) after rotating our API key (following item #7)[cite: 7].
- **Steps Taken:** Updated the root `.env` file with the new API key and started the simulator[cite: 7].
- **Expected vs. Actual:**
  - *Expected:* If `simulator/.env` is empty or missing a key, the error message should specify the exact file path (`simulator/.env` vs. root `.env`) and environment variable name that failed to load[cite: 7].
  - *Actual:* An empty `simulator/.env` file after key rotation produced a generic `"key missing"` error, causing confusion over why the updated root `.env` key wasn't being picked up[cite: 7].
- **Severity:** **Low**[cite: 7]
- **Workaround Used:** Populated `simulator/.env` alongside `simulator/.env.example` and documented the dual `.env` setup clearly in the Quick Start guide[cite: 7].
- **Actionable Suggestion:** Have multi-component starter templates fall back to the repository root `.env` automatically (via `find_dotenv()`) and include the resolved `.env` file path in missing-key error messages.
