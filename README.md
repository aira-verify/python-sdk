# Aira Python SDK — The authorization and audit layer for AI agents.

[![PyPI version](https://img.shields.io/pypi/v/aira-sdk.svg)](https://pypi.org/project/aira-sdk/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

Drop Aira into your agent stack in one line. Define policies without changing code. Get cryptographic proof of every decision — for your auditors, your board, or a court. Not because regulation requires it. Because your agents are acting in production right now.

```bash
pip install aira-sdk
```

With extras for framework integrations:

```bash
pip install aira-sdk[langchain]  # or crewai, openai-agents, google-adk, bedrock, mcp, cli
```

---

## Quick Start

Aira uses a two-step flow: **authorize** before the agent executes, **notarize** after. This means Aira can actually gate the action — denied calls never run.

```python
from aira import Aira, AiraError

aira = Aira(api_key="aira_live_xxx")

# Step 1: ask Aira for permission BEFORE executing.
# Aira gates this action — policies run here and can deny it.
try:
    auth = aira.authorize(
        action_type="wire_transfer",
        details="Send EUR 75,000 to vendor-x",
        agent_id="payments-agent",
        model_id="claude-sonnet-4-6",
        instruction_hash="sha256:a1b2c3...",
    )
except AiraError as e:
    if e.code == "POLICY_DENIED":
        print(f"Denied by policy {e.details['policy_id']} — action {e.details['action_id']}")
        raise

if auth.status == "authorized":
    # Step 2: execute the action, then report the outcome.
    # This mints the Ed25519-signed, RFC 3161 timestamped receipt.
    ref = send_wire(75000, to="vendor-x")
    receipt = aira.notarize(
        action_id=auth.action_id,
        outcome="completed",
        outcome_details=f"Wire sent, ref={ref}",
    )
    print(receipt.payload_hash)   # sha256:e5f6a7b8...
    print(receipt.signature)      # ed25519:base64url...
    print(receipt.action_id)      # uuid — publicly verifiable

elif auth.status == "pending_approval":
    # A policy held this for human review. The agent must NOT execute.
    queue.enqueue(auth.action_id)  # wait for action.approved webhook
```

**What just happened:** Aira gated this action before you executed it. If a policy would have denied the wire transfer, `authorize()` raises `AiraError("POLICY_DENIED")` and your code never calls `send_wire()`. If a policy held the action for human review, `auth.status` is `"pending_approval"` and you queue it. Only authorized actions are ever executed, and every executed action is followed by a `notarize()` call that mints the cryptographic receipt. Failed executions are still recorded via `notarize(outcome="failed")` — no receipt is minted but the action transitions correctly.

---

## Core SDK Methods

Every method on `Aira` (sync) is mirrored on `AsyncAira` (async).

| Category | Method | Description |
|---|---|---|
| **Actions** | `authorize()` | **Step 1**: ask Aira for permission. Returns `Authorization` with status `authorized` or `pending_approval`. Raises `AiraError("POLICY_DENIED")` if denied. |
| | `notarize()` | **Step 2**: report outcome (`completed` or `failed`). Mints the Ed25519 receipt when completed. |
| | `get_action()` | Retrieve action details + receipt |
| | `list_actions()` | List actions with filters (type, agent, status) |
| | `cosign_action()` | Human co-signature on an authorized or notarized action |
| | `set_legal_hold()` | Prevent deletion -- litigation hold |
| | `release_legal_hold()` | Release litigation hold |
| | `get_action_chain()` | Chain of custody for an action |
| | `verify_action()` | Public verification -- no auth required |
| **Agents** | `register_agent()` | Register verifiable agent identity |
| | `get_agent()` | Retrieve agent profile |
| | `list_agents()` | List registered agents |
| | `update_agent()` | Update agent metadata |
| | `publish_version()` | Publish versioned agent config |
| | `list_versions()` | List agent versions |
| | `decommission_agent()` | Decommission agent |
| | `transfer_agent()` | Transfer ownership to another org |
| | `get_agent_actions()` | List actions by agent |
| **Trust Layer** | `get_agent_did()` | Retrieve agent's W3C DID (`did:web`) |
| | `rotate_agent_keys()` | Rotate agent's Ed25519 signing keys |
| | `get_agent_credential()` | Get agent's W3C Verifiable Credential |
| | `verify_credential()` | Verify a Verifiable Credential |
| | `revoke_credential()` | Revoke agent's Verifiable Credential |
| | `request_mutual_sign()` | Initiate mutual notarization with counterparty |
| | `complete_mutual_sign()` | Complete mutual notarization (counterparty signs) |
| | `get_reputation()` | Get agent reputation score and tier |
| | `list_reputation_history()` | List reputation score history |
| | `resolve_did()` | Resolve any DID to its DID Document |
| **Cases** | `run_case()` | Multi-model consensus adjudication |
| | `get_case()` | Retrieve case result |
| | `list_cases()` | List cases |
| **Receipts** | `get_receipt()` | Retrieve cryptographic receipt |
| | `export_receipt()` | Export receipt as JSON or PDF |
| **Evidence** | `create_evidence_package()` | Sealed, tamper-proof evidence bundle |
| | `list_evidence_packages()` | List evidence packages |
| | `get_evidence_package()` | Retrieve evidence package |
| | `time_travel()` | Query actions at a point in time |
| | `liability_chain()` | Walk full liability chain |
| **Estate** | `set_agent_will()` | Define succession plan |
| | `get_agent_will()` | Retrieve agent will |
| | `issue_death_certificate()` | Decommission with succession trigger |
| | `get_death_certificate()` | Retrieve death certificate |
| | `create_compliance_snapshot()` | Compliance snapshot (EU AI Act, SR 11-7, GDPR) |
| | `list_compliance_snapshots()` | List snapshots by framework |
| **Escrow** | `create_escrow_account()` | Create liability commitment ledger |
| | `list_escrow_accounts()` | List escrow accounts |
| | `get_escrow_account()` | Retrieve escrow account |
| | `escrow_deposit()` | Record liability commitment |
| | `escrow_release()` | Release commitment after completion |
| | `escrow_dispute()` | Dispute -- flag liability issue |
| **Chat** | `ask()` | Query your notarized data via AI |
| **Offline** | `sync()` | Flush offline queue to API |
| **Session** | `session()` | Scoped session with pre-filled defaults |

---

## Trust Layer

Standards-based identity and trust for agents: W3C DIDs, Verifiable Credentials, mutual notarization, and reputation scoring. Every agent gets a cryptographically verifiable identity that other agents (and humans) can check before interacting.

### DID Identity

Every registered agent gets a W3C-compliant DID (`did:web`):

```python
# Retrieve the agent's DID
did = aira.get_agent_did("my-agent")
print(did)  # "did:web:airaproof.com:agents:my-agent"

# Rotate signing keys (old keys are revoked, new keys are published)
aira.rotate_agent_keys("my-agent")
```

### Verifiable Credentials

```python
# Get the agent's W3C Verifiable Credential
vc = aira.get_agent_credential("my-agent")

# Verify any VC (returns validity, issuer, expiry)
result = aira.verify_credential(vc)
print(result["valid"])  # True

# Revoke a credential
aira.revoke_credential("my-agent", reason="Agent deprecated")
```

### Mutual Notarization

For high-stakes actions, both parties co-sign:

```python
# Agent A initiates — sends a signing request to the counterparty
request = aira.request_mutual_sign(
    action_id="act-uuid",
    counterparty_did="did:web:partner.com:agents:their-agent",
)

# Agent B completes — signs the same payload
receipt = aira.complete_mutual_sign(
    action_id="act-uuid",
    did="did:web:partner.com:agents:their-agent",
    signature="z...",
    signed_payload_hash="sha256:...",
)
```

### Reputation

```python
rep = aira.get_reputation("my-agent")
print(rep["score"])  # 84
print(rep["tier"])   # "Verified"
```

### Endpoint Verification

Control which external APIs your agents can call. Pass `endpoint_url` to `authorize()` and Aira checks it against your org's whitelist before letting the agent execute. Unrecognized endpoints are denied.

```python
from aira import Aira, AiraError

try:
    auth = aira.authorize(
        action_type="api_call",
        details="Charged customer $49.99 for subscription renewal",
        agent_id="billing-agent",
        model_id="claude-sonnet-4-6",
        endpoint_url="https://api.stripe.com/v1/charges",
    )
except AiraError as e:
    if e.code == "ENDPOINT_NOT_WHITELISTED":
        print(f"Blocked: {e.message}")
        print(f"Details: {e.details}")
    elif e.code == "ENDPOINT_TLS_MISMATCH":
        print(f"TLS fingerprint mismatch: {e.message}")
    else:
        raise
```

---

## Session Context Manager

Pre-fill defaults for a block of related `authorize()` calls. Every call within the session inherits the agent identity and model.

```python
with aira.session(agent_id="onboarding-agent", model_id="claude-sonnet-4-6") as sess:
    auth = sess.authorize(action_type="identity_verified", details="Verified customer ID #4521")
    if auth.status == "authorized":
        # ... do the thing ...
        sess.notarize(action_id=auth.action_id, outcome="completed")

    auth = sess.authorize(action_type="account_created", details="Created account for customer #4521")
    if auth.status == "authorized":
        sess.notarize(action_id=auth.action_id, outcome="completed")
```

---

## Offline Mode

Queue authorize calls locally when connectivity is unavailable. When you call `sync()`, the queued authorizes are flushed to the backend in FIFO order and you get the real action IDs back.

```python
aira = Aira(api_key="aira_live_xxx", offline=True)

# Queue locally — no network calls yet, no action_ids yet.
aira.authorize(action_type="scan_completed", details="Scanned document batch #77")
aira.authorize(action_type="classification_done", details="Classified 142 documents")

print(aira.pending_count)  # 2

# Flush when back online — backend creates the actions.
results = aira.sync()
```

GET requests (reading action status) are not available in offline mode, and you cannot `notarize()` a queued action until after `sync()` has returned the real `action_id`.

---

## Human Approval

Hold high-stakes actions for human review at `authorize()` time. The agent never executes — the action sits in `pending_approval` state until a human clicks Approve or Deny in the dashboard.

```python
auth = aira.authorize(
    action_type="loan_decision",
    details="Approve EUR 15,000 loan for Maria Schmidt",
    agent_id="lending-agent",
    require_approval=True,
    approvers=["compliance@acme.com", "risk@acme.com"],
)

if auth.status == "pending_approval":
    # Don't execute yet — wait for action.approved webhook,
    # then call notarize(action_id=auth.action_id, outcome="completed")
    queue.enqueue(auth.action_id)
```

When the approver clicks "Approve" the action transitions to `approved` and `action.approved` webhook fires. Your worker then executes the action and calls `notarize(action_id, outcome="completed")` — which mints the Ed25519 + RFC 3161 receipt. If denied, `action.denied` fires and no receipt is ever minted.

Configure default approvers at [Settings → Approvers](https://app.airaproof.com/dashboard/settings/approvers).

### Automatic Policy Evaluation

Org admins configure policies in the dashboard — your code doesn't change. Every `authorize()` call is automatically evaluated against active policies before the agent is allowed to execute.

Three evaluation modes:

- **Rules**: Deterministic conditions — instant, no LLM call
- **AI**: Single LLM evaluates action against a natural language policy (1-5s)
- **Consensus**: Multiple LLMs evaluate independently — disagreement triggers human review (3-10s)

```python
# Your code stays the same — policies evaluate automatically at authorize() time.
from aira import AiraError

try:
    auth = aira.authorize(
        action_type="data_deletion",
        details="Delete customer records",
        agent_id="billing-agent",
    )
except AiraError as e:
    if e.code == "POLICY_DENIED":
        print(f"Policy {e.details['policy_id']} denied action {e.details['action_id']}")

# If a policy returns "require_approval", auth.status is "pending_approval"
# and the agent must not execute — wait for the approval webhook.
```

Configure policies at [Settings → Policies](https://app.airaproof.com/dashboard/policies).

---

## Async Support

`AsyncAira` mirrors every method on `Aira`. The only difference is `await`.

```python
from aira import AsyncAira

async with AsyncAira(api_key="aira_live_xxx") as aira:
    auth = await aira.authorize(
        action_type="contract_signed",
        details="Agent signed vendor agreement #1234",
        agent_id="procurement-agent",
    )
    if auth.status == "authorized":
        ref = await sign_contract(1234)
        await aira.notarize(
            action_id=auth.action_id,
            outcome="completed",
            outcome_details=f"signed, ref={ref}",
        )
```

---

## Framework Integrations

Drop Aira into your existing agent framework with one line. Each integration either **gates** actions (authorize before execution, abort on deny) or **audits** them (record post-hoc). Whether gating is possible depends on whether the framework exposes a pre-execution hook that can abort.

| Framework | Install | Integration Class | Mode |
|---|---|---|---|
| **LangChain** | `pip install aira-sdk[langchain]` | `AiraCallbackHandler` | **Gate** (tools) / Audit (chain, LLM) |
| **OpenAI Agents** | `pip install aira-sdk[openai-agents]` | `AiraGuardrail` | **Gate** |
| **Google ADK** | `pip install aira-sdk[google-adk]` | `AiraPlugin` | **Gate** |
| **AWS Bedrock** | `pip install aira-sdk[bedrock]` | `AiraBedrockHandler` | **Gate** |
| **CrewAI** | `pip install aira-sdk[crewai]` | `AiraCrewHook` | Audit-only |
| **MCP** | `pip install aira-sdk[mcp]` | MCP Server | N/A (exposes Aira as a tool) |
| **CLI** | `pip install aira-sdk[cli]` | `aira` command | N/A |

### LangChain (gate on tools, audit on chain/LLM)

`AiraCallbackHandler` uses `on_tool_start` to authorize each tool call before it runs. If Aira denies the call, the callback raises `AiraToolDenied` and LangChain treats it as a tool error — the tool never runs. `on_tool_end` / `on_tool_error` notarize the completion. Chain and LLM completions are audit-only because LangChain does not provide a reliable pre-execution hook that can abort them.

```python
from aira import Aira
from aira.extras.langchain import AiraCallbackHandler, AiraToolDenied

aira = Aira(api_key="aira_live_xxx")
handler = AiraCallbackHandler(client=aira, agent_id="research-agent", model_id="gpt-5.2")

# Tool calls are gated: POLICY_DENIED → AiraToolDenied → tool is skipped.
result = chain.invoke({"input": "Analyze Q1 revenue"}, config={"callbacks": [handler]})
```

### OpenAI Agents SDK (full gate)

`AiraGuardrail.wrap_tool()` wraps any tool function so every call authorizes first, runs second, then notarizes with `outcome="completed"` (or `"failed"` on exception). Denied calls raise `AiraToolDenied` before the tool runs.

```python
from aira import Aira
from aira.extras.openai_agents import AiraGuardrail, AiraToolDenied

aira = Aira(api_key="aira_live_xxx")
guardrail = AiraGuardrail(client=aira, agent_id="assistant-agent")

search = guardrail.wrap_tool(search_tool, tool_name="web_search")
execute = guardrail.wrap_tool(code_executor, tool_name="code_exec")

try:
    result = execute(code="rm -rf /")
except AiraToolDenied as e:
    print(f"Aira blocked: [{e.code}] {e.message}")
```

### Google ADK (full gate)

`AiraPlugin.before_tool_call()` authorizes before the tool runs; if Aira denies or holds the action it raises `AiraToolDenied`. `after_tool_call()` notarizes success, `on_tool_error()` notarizes failure.

```python
from aira import Aira
from aira.extras.google_adk import AiraPlugin, AiraToolDenied

aira = Aira(api_key="aira_live_xxx")
plugin = AiraPlugin(client=aira, agent_id="adk-agent", model_id="gemini-2.0-flash")

try:
    plugin.before_tool_call("search_documents", args={"query": "contract terms"})
    result = search_documents(query="contract terms")
    plugin.after_tool_call("search_documents", result=result)
except AiraToolDenied as e:
    print(f"Denied: [{e.code}] {e.message}")
```

### AWS Bedrock (full gate)

`AiraBedrockHandler.wrap_invoke_model()` wraps your Bedrock client so every model call is authorized first and only delegates to the real Bedrock API if Aira allows it.

```python
import boto3
from aira import Aira
from aira.extras.bedrock import AiraBedrockHandler, AiraInvocationDenied

aira = Aira(api_key="aira_live_xxx")
handler = AiraBedrockHandler(client=aira, agent_id="bedrock-agent")

bedrock = boto3.client("bedrock-runtime")
bedrock.invoke_model = handler.wrap_invoke_model(bedrock)

try:
    response = bedrock.invoke_model(modelId="anthropic.claude-v2", body=payload)
except AiraInvocationDenied as e:
    print(f"Bedrock call blocked: [{e.code}] {e.message}")
```

### CrewAI (audit-only)

`AiraCrewHook.for_crew()` returns callback dicts that plug into CrewAI's `Crew()` constructor. **CrewAI does not expose a pre-execution hook that can abort a step or task**, so this integration is audit-only — it records what happened but cannot gate it. For true gating, call `aira.authorize()` directly inside your CrewAI tool functions before performing the side-effect.

```python
from aira import Aira
from aira.extras.crewai import AiraCrewHook

aira = Aira(api_key="aira_live_xxx")
callbacks = AiraCrewHook.for_crew(client=aira, agent_id="research-crew")

crew = Crew(
    agents=[researcher, writer],
    tasks=[research_task, write_task],
    **callbacks,  # task_callback + step_callback — audit-only
)
crew.kickoff()
```

---

## MCP Server

Expose Aira as an MCP tool server. Any MCP-compatible AI agent can notarize actions and verify receipts without SDK integration.

```bash
# Set your API key
export AIRA_API_KEY="aira_live_xxx"

# Run the MCP server (stdio transport)
aira-mcp
```

The server exposes the two-step flow as tools (`authorize_action`, `notarize_action`) plus `verify_action`, `get_receipt`, `resolve_did`, `verify_credential`, and `get_reputation`.

Add to your MCP client config:

```json
{
  "mcpServers": {
    "aira": {
      "command": "aira-mcp",
      "env": { "AIRA_API_KEY": "aira_live_xxx" }
    }
  }
}
```

---

## CLI

Command-line access to Aira's governance infrastructure. Every command interacts with the same cryptographic backend.

```bash
pip install aira-sdk[cli]
```

```bash
# Show SDK version
aira version

# Verify a notarized action's cryptographic receipt
aira verify <action-uuid>

# List notarized actions (with optional agent filter)
aira actions list --agent lending-agent --limit 20

# List registered agents
aira agents list

# Register a new agent identity
aira agents create my-agent --name "My Agent"

# Create a compliance snapshot (EU AI Act, SR 11-7, GDPR Art. 22)
aira snapshot create eu-ai-act lending-agent

# Create a sealed, tamper-proof evidence package
aira package create --title "Q1 Audit Trail" --actions "uuid-1,uuid-2,uuid-3"
```

All commands accept `--api-key` / `-k` and `--base-url` flags, or read from `AIRA_API_KEY`.

---

## Webhook Verification

Verify that incoming webhooks are authentic Aira events, not forged requests. HMAC-SHA256 signature verification ensures tamper-proof delivery.

```python
from aira.extras.webhooks import verify_signature, parse_event

# Verify the webhook signature (HMAC-SHA256)
is_valid = verify_signature(
    payload=request.body,
    signature=request.headers["X-Aira-Signature"],
    secret="whsec_xxx",
)

if is_valid:
    event = parse_event(request.body)
    print(event.event_type)   # "action.notarized"
    print(event.data)         # Action data with cryptographic receipt
    print(event.delivery_id)  # Unique delivery ID
```

Supported event types: `action.notarized`, `action.authorized`, `agent.registered`, `agent.decommissioned`, `evidence.sealed`, `escrow.deposited`, `escrow.released`, `escrow.disputed`, `compliance.snapshot_created`, `case.complete`, `case.requires_human_review`.

---

## Error Handling

```python
from aira import Aira, AiraError

try:
    auth = aira.authorize(action_type="email_sent", details="test", agent_id="support-agent")
except AiraError as e:
    print(e.status)   # HTTP status code
    print(e.code)     # e.g. "POLICY_DENIED", "ENDPOINT_NOT_WHITELISTED", "DUPLICATE_REQUEST"
    print(e.message)  # Human-readable error
    print(e.details)  # dict with context, e.g. {"action_id": "...", "policy_id": "..."}
```

The gating integrations (LangChain tool calls, OpenAI Agents, Google ADK, Bedrock) raise `AiraToolDenied` / `AiraInvocationDenied` when Aira denies an action — the wrapped call never runs. Notarize failures after a successful execution are always logged and non-blocking, so a transient Aira outage never prevents an already-executed action from returning its result.

---

## Configuration

```python
aira = Aira(
    api_key="aira_live_xxx",                      # Required — aira_live_ or aira_test_ prefix
    base_url="https://your-self-hosted.com",      # Self-hosted deployment
    timeout=60.0,                                  # Request timeout in seconds
    offline=True,                                  # Queue locally, sync later
)
```

| Env Variable | Description |
|---|---|
| `AIRA_API_KEY` | API key (used by CLI and MCP server) |

---

## Links

- [Website](https://airaproof.com)
- [Documentation](https://docs.airaproof.com)
- [API Reference](https://docs.airaproof.com/docs/api-reference)
- [Interactive Demo](https://app.airaproof.com/demo) -- try Aira in your browser, no code needed
- [Dashboard](https://app.airaproof.com)
- [PyPI Package](https://pypi.org/project/aira-sdk/)
- [TypeScript SDK (npm)](https://www.npmjs.com/package/aira-sdk)
- [GitHub](https://github.com/aira-proof/python-sdk)
