# Aira Python SDK

**The authorization and audit layer for AI agents.**

[![PyPI version](https://img.shields.io/pypi/v/aira-sdk.svg)](https://pypi.org/project/aira-sdk/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

Aira sits between your agents and the actions they take. Every action is intercepted, evaluated against your policies, and either authorized, held for human approval, or denied. Authorized actions get a cryptographic receipt that anyone can verify.

You get three things in one drop-in SDK:

1. **Policy engine** with three modes (Rules, AI, Consensus) so you decide how strictly each action is checked.
2. **Multi-model consensus** where several models evaluate the same action and disagreement automatically routes to a human.
3. **Cryptographic receipts** signed with Ed25519 and timestamped via RFC 3161, so every authorized action carries portable proof.

## Install

```bash
pip install aira-sdk
```

With extras for framework integrations:

```bash
pip install aira-sdk[langchain]  # or crewai, openai-agents, google-adk, bedrock, mcp, cli
```

---

## Quick Start

Wrap any agent action in `notarize()`. Aira evaluates your active policies, holds the action if a human needs to approve it, and only mints a receipt once the action is authorized.

```python
from aira import Aira

aira = Aira(api_key="aira_live_xxx")

receipt = aira.notarize(
    action_type="email_sent",
    details="Sent onboarding email to customer@example.com",
    agent_id="support-agent",
    model_id="claude-sonnet-4-6",
    instruction_hash="sha256:a1b2c3...",
)

# If policies allow the action, you get a verifiable receipt back.
print(receipt.status)         # "authorized"
print(receipt.payload_hash)   # sha256:e5f6a7b8...
print(receipt.signature)      # ed25519:base64url...
print(receipt.action_id)      # uuid, publicly verifiable
```

What just happened:

1. The call hit Aira before the action was considered final.
2. Active policies were evaluated against the action metadata.
3. Because no policy required approval or denied the action, Aira signed a receipt with Ed25519 and timestamped it via RFC 3161.
4. The receipt is now public proof that the action was authorized at that exact moment.

If a policy decides the action needs a human, the receipt comes back with `status="pending_approval"` and no signature is issued until an approver acts. If a policy denies the action, an `AiraError` with code `POLICY_DENIED` is raised so your agent never proceeds.

---

## Policy Engine

Org admins configure policies in the dashboard. Your code does not change. Every `notarize()` call is automatically evaluated against active policies before a receipt is issued, and the policy evaluation itself produces a cryptographic receipt so you can prove the check happened.

Three evaluation modes let you trade speed for rigor:

- **Rules.** Deterministic conditions (action type, amount thresholds, regex on details, agent identity). Instant, no LLM call.
- **AI.** A single LLM evaluates the action against a natural language policy. Typically 1 to 5 seconds.
- **Consensus.** Multiple LLMs evaluate the same action independently. If they disagree, the action is automatically routed to a human reviewer. Typically 3 to 10 seconds.

### Rules mode

```python
# Policy in dashboard: "Wire transfers over $10,000 require approval"
# Your code stays the same.
receipt = aira.notarize(
    action_type="wire_transfer",
    details="Transfer $50,000 to vendor account",
    agent_id="billing-agent",
)

print(receipt.status)             # "pending_approval"
print(receipt.policy_evaluation)  # {"policy_name": "Large wires need approval", "decision": "require_approval", ...}
```

### AI mode

```python
# Policy in dashboard (AI mode): "Block any customer email that promises a refund without confirmation."
from aira import AiraError

try:
    aira.notarize(
        action_type="email_sent",
        details="We will issue a full refund within 24 hours.",
        agent_id="support-agent",
    )
except AiraError as e:
    if e.code == "POLICY_DENIED":
        print(e.message)  # "Action denied by policy 'No unilateral refund promises'"
```

### Consensus mode

```python
# Policy in dashboard (Consensus mode): three models evaluate the action.
# If they disagree, the action is held for human review automatically.
receipt = aira.notarize(
    action_type="loan_decision",
    details="Approved EUR 15,000 loan for Maria Schmidt",
    agent_id="lending-agent",
)

if receipt.status == "pending_approval":
    print("Models disagreed, human review required")
    print(receipt.policy_evaluation["models"])  # per-model votes and reasoning
```

The SDK override `require_approval=True` still works and skips policy evaluation, going straight to human approval. Configure policies at [Settings, Policies](https://app.airaproof.com/dashboard/policies).

---

## Human Approval

Hold high-stakes actions for human review before the cryptographic receipt is issued. Approvers receive an email with Approve and Deny buttons. The receipt is only minted after approval.

```python
# Explicit approvers
receipt = aira.notarize(
    action_type="loan_decision",
    details="Approved EUR 15,000 loan for Maria Schmidt",
    agent_id="lending-agent",
    require_approval=True,
    approvers=["compliance@acme.com", "risk@acme.com"],
)
print(receipt.status)      # "pending_approval"
print(receipt.receipt_id)  # None until approved

# Falls back to org default approvers (Settings, Approvers)
receipt = aira.notarize(
    action_type="wire_transfer",
    details="Transfer $50,000 to vendor account",
    agent_id="payments-agent",
    require_approval=True,
)

# Decorator form, approval gate on every call
@aira.trace(agent_id="billing-agent", require_approval=True, approvers=["finance@acme.com"])
def charge_customer(amount):
    stripe.charge(amount)
```

When the approver clicks Approve, the receipt is minted with an Ed25519 signature plus an RFC 3161 timestamp, and the `action.approved` webhook fires. If denied, no receipt is created and the `action.denied` webhook fires.

Configure default approvers in the [dashboard](https://app.airaproof.com/dashboard/settings/approvers) or via the `/approvers` API.

---

## Verification

Receipts are designed to be verified by anyone, including parties who do not have an Aira account. Verification confirms the signature, the timestamp, and the chain of custody.

```python
# Anyone can verify a receipt by action_id, no API key required.
result = aira.verify_action("act-uuid")
print(result.valid)         # True
print(result.signature)     # ed25519:base64url...
print(result.timestamp)     # RFC 3161 timestamp
print(result.public_key)    # Ed25519 public key used to sign
```

From the CLI:

```bash
aira verify <action-uuid>
```

Receipts can also be exported as JSON or PDF, sealed into evidence packages, and walked back through their full chain of custody.

```python
aira.export_receipt("act-uuid", format="pdf")
aira.create_evidence_package(title="Q1 audit trail", action_ids=["uuid-1", "uuid-2"])
aira.get_action_chain("act-uuid")
```

---

## Decorator (`@aira.trace`)

Auto-notarize any function call. The decorator is non-blocking, so if Aira is unreachable your function still returns normally. Arguments and return values are never sent to the API, only a metadata hash is recorded.

```python
@aira.trace(agent_id="lending-agent", action_type="loan_decision")
def approve_loan(application):
    decision = model.predict(application)
    return decision

# Every call is policy-checked and produces a verifiable receipt on success.
result = approve_loan({"credit_score": 742, "income": 45000})
```

Set `include_result=True` only if the return value contains no sensitive data:

```python
@aira.trace(agent_id="pricing-agent", action_type="price_calculated", include_result=True)
def calculate_price(product_id):
    return lookup_price(product_id)
```

---

## Session Context Manager

Pre-fill defaults for a block of related actions. Every `notarize()` call within the session inherits the agent identity and model, producing receipts that share a common provenance chain.

```python
with aira.session(agent_id="onboarding-agent", model_id="claude-sonnet-4-6") as sess:
    sess.notarize(action_type="identity_verified", details="Verified customer ID #4521")
    sess.notarize(action_type="account_created", details="Created account for customer #4521")
    sess.notarize(action_type="welcome_sent", details="Sent welcome email to customer #4521")

    @sess.trace(action_type="document_generated")
    def generate_contract(customer_id):
        return build_contract(customer_id)
```

---

## Trust Layer

Standards-based identity for agents: W3C DIDs, Verifiable Credentials, mutual notarization, and reputation scoring. Use it to authorize cross-organization agent interactions, not just internal actions.

### DID Identity

Every registered agent gets a W3C-compliant DID (`did:web`):

```python
did = aira.get_agent_did("my-agent")
print(did)  # "did:web:airaproof.com:agents:my-agent"

# Rotate signing keys (old keys are revoked, new keys are published)
aira.rotate_agent_keys("my-agent")
```

### Verifiable Credentials

```python
vc = aira.get_agent_credential("my-agent")

result = aira.verify_credential(vc)
print(result["valid"])  # True

aira.revoke_credential("my-agent", reason="Agent deprecated")
```

### Mutual Notarization

For high-stakes cross-org actions, both parties co-sign:

```python
# Agent A initiates, sending a signing request to the counterparty
request = aira.request_mutual_sign(
    action_id="act-uuid",
    counterparty_did="did:web:partner.com:agents:their-agent",
)

# Agent B completes by signing the same payload
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

Control which external APIs your agents can call. When `endpoint_url` is passed to `notarize()`, Aira checks it against your org's whitelist. Unrecognized endpoints are blocked in strict mode.

```python
receipt = aira.notarize(
    action_type="api_call",
    details="Charged customer $49.99 for subscription renewal",
    agent_id="billing-agent",
    model_id="claude-sonnet-4-6",
    endpoint_url="https://api.stripe.com/v1/charges",
)
```

Handle `ENDPOINT_NOT_WHITELISTED`:

```python
from aira import Aira, AiraError

try:
    receipt = aira.notarize(
        action_type="api_call",
        details="Send SMS via new provider",
        agent_id="notifications-agent",
        endpoint_url="https://api.newprovider.com/v1/sms",
    )
except AiraError as e:
    if e.code == "ENDPOINT_NOT_WHITELISTED":
        print(f"Blocked: {e.message}")
        print(f"Approval request: {e.details['approval_id']}")
        print(f"Suggested pattern: {e.details['url_pattern_suggested']}")
    else:
        raise
```

### Trust Policy in Integrations

Pass a `trust_policy` to any framework integration to run automated trust checks before agent interactions:

```python
from aira.extras.langchain import AiraCallbackHandler

handler = AiraCallbackHandler(
    client=aira,
    agent_id="research-agent",
    model_id="gpt-5.2",
    trust_policy={
        "verify_counterparty": True,   # resolve counterparty DID
        "min_reputation": 60,          # warn if reputation score below 60
        "require_valid_vc": True,      # check Verifiable Credential validity
        "block_revoked_vc": True,      # block if counterparty VC is revoked
        "block_unregistered": False,   # do not block agents without Aira DIDs
    },
)
```

---

## Framework Integrations

Drop Aira into your existing agent framework with one line. Every integration runs the same policy engine and produces the same verifiable receipts.

| Framework | Install | Integration Class |
|---|---|---|
| **LangChain** | `pip install aira-sdk[langchain]` | `AiraCallbackHandler` |
| **CrewAI** | `pip install aira-sdk[crewai]` | `AiraCrewHook` |
| **OpenAI Agents** | `pip install aira-sdk[openai-agents]` | `AiraGuardrail` |
| **Google ADK** | `pip install aira-sdk[google-adk]` | `AiraPlugin` |
| **AWS Bedrock** | `pip install aira-sdk[bedrock]` | `AiraBedrockHandler` |
| **MCP** | `pip install aira-sdk[mcp]` | MCP Server |
| **CLI** | `pip install aira-sdk[cli]` | `aira` command |

### LangChain

`AiraCallbackHandler` sends every tool call, chain completion, and LLM invocation through the policy engine. Authorized actions get a signed receipt. No changes to your chain logic.

```python
from aira import Aira
from aira.extras.langchain import AiraCallbackHandler

aira = Aira(api_key="aira_live_xxx")
handler = AiraCallbackHandler(client=aira, agent_id="research-agent", model_id="gpt-5.2")

result = chain.invoke({"input": "Analyze Q1 revenue"}, config={"callbacks": [handler]})
```

### CrewAI

`AiraCrewHook.for_crew()` returns callback dicts that plug directly into CrewAI's `Crew()` constructor. Every task and step is policy-checked and produces a court-admissible receipt.

```python
from aira import Aira
from aira.extras.crewai import AiraCrewHook

aira = Aira(api_key="aira_live_xxx")
callbacks = AiraCrewHook.for_crew(client=aira, agent_id="research-crew")

crew = Crew(
    agents=[researcher, writer],
    tasks=[research_task, write_task],
    **callbacks,  # task_callback + step_callback, each policy-checked and notarized
)
crew.kickoff()
```

### OpenAI Agents SDK

`AiraGuardrail.wrap_tool()` wraps any tool function so both invocation and result are run through the policy engine before execution proceeds.

```python
from aira import Aira
from aira.extras.openai_agents import AiraGuardrail

aira = Aira(api_key="aira_live_xxx")
guardrail = AiraGuardrail(client=aira, agent_id="assistant-agent")

search = guardrail.wrap_tool(search_tool, tool_name="web_search")
execute = guardrail.wrap_tool(code_executor, tool_name="code_exec")
```

### Google ADK

`AiraPlugin` provides `before_tool_call` and `after_tool_call` hooks. The before hook is where policies run, so a denied action never executes.

```python
from aira import Aira
from aira.extras.google_adk import AiraPlugin

aira = Aira(api_key="aira_live_xxx")
plugin = AiraPlugin(client=aira, agent_id="adk-agent", model_id="gemini-2.0-flash")

plugin.before_tool_call("search_documents", args={"query": "contract terms"})
result = search_documents(query="contract terms")
plugin.after_tool_call("search_documents", result=result)
```

### AWS Bedrock

`AiraBedrockHandler.wrap_invoke_model()` wraps your Bedrock client so every model invocation is policy-checked and notarized.

```python
import boto3
from aira import Aira
from aira.extras.bedrock import AiraBedrockHandler

aira = Aira(api_key="aira_live_xxx")
handler = AiraBedrockHandler(client=aira, agent_id="bedrock-agent")

bedrock = boto3.client("bedrock-runtime")
bedrock.invoke_model = handler.wrap_invoke_model(bedrock)

response = bedrock.invoke_model(modelId="anthropic.claude-v2", body=payload)
```

### MCP Server

Expose Aira as an MCP tool server. Any MCP-compatible AI agent can run actions through the policy engine and verify receipts without SDK integration.

```bash
export AIRA_API_KEY="aira_live_xxx"
aira-mcp
```

The server exposes three tools: `notarize_action`, `verify_action`, and `get_receipt`. Each goes through the same policy engine.

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

Command-line access to Aira. Every command hits the same authorization and audit backend as the SDK.

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

## Async Support

`AsyncAira` mirrors every method on `Aira`. Policies run the same way, receipts are identical, the only difference is `await`.

```python
from aira import AsyncAira

async with AsyncAira(api_key="aira_live_xxx") as aira:
    receipt = await aira.notarize(
        action_type="contract_signed",
        details="Agent signed vendor agreement #1234",
        agent_id="procurement-agent",
    )

    @aira.trace(agent_id="fulfillment-agent")
    async def process_order(order):
        return await execute(order)
```

---

## Offline Mode

Queue actions locally when connectivity is unavailable. Policies are evaluated and receipts are minted server-side when you sync, so nothing is lost.

```python
aira = Aira(api_key="aira_live_xxx", offline=True)

# These queue locally, no network calls
aira.notarize(action_type="scan_completed", details="Scanned document batch #77")
aira.notarize(action_type="classification_done", details="Classified 142 documents")

print(aira.pending_count)  # 2

# Flush to API when back online, policies run and receipts are issued for each action
results = aira.sync()
```

---

## Webhook Verification

Verify that incoming webhooks are authentic Aira events, not forged requests. HMAC-SHA256 signature verification ensures tamper-proof delivery.

```python
from aira.extras.webhooks import verify_signature, parse_event

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

Supported event types: `action.notarized`, `action.authorized`, `action.approved`, `action.denied`, `agent.registered`, `agent.decommissioned`, `evidence.sealed`, `escrow.deposited`, `escrow.released`, `escrow.disputed`, `compliance.snapshot_created`, `case.complete`, `case.requires_human_review`.

---

## Error Handling

```python
from aira import Aira, AiraError

try:
    receipt = aira.notarize(action_type="email_sent", details="test")
except AiraError as e:
    print(e.status)   # 429
    print(e.code)     # PLAN_LIMIT_EXCEEDED
    print(e.message)  # Monthly operation limit reached
```

Common error codes:

- `POLICY_DENIED`. A policy blocked the action. Check `e.message` for the policy name.
- `ENDPOINT_NOT_WHITELISTED`. The endpoint URL is not in the org whitelist.
- `PLAN_LIMIT_EXCEEDED`. Monthly operation limit reached.

All framework integrations (LangChain, CrewAI, OpenAI Agents, Google ADK, Bedrock) are non-blocking by default. Notarization failures are logged, never raised, so your agent keeps running.

---

## Configuration

```python
aira = Aira(
    api_key="aira_live_xxx",                      # Required, aira_live_ or aira_test_ prefix
    base_url="https://your-self-hosted.com",      # Self-hosted deployment
    timeout=60.0,                                  # Request timeout in seconds
    offline=True,                                  # Queue locally, sync later
)
```

| Env Variable | Description |
|---|---|
| `AIRA_API_KEY` | API key (used by CLI and MCP server) |

### Self-Hosting

Aira can run inside your own VPC. Point the SDK at your deployment with `base_url` and the same policy engine, approval flow, and receipts work end to end. Get in touch via the website for self-hosting access.

---

## Core SDK Methods

All methods on `Aira` (sync) and `AsyncAira` (async). Every write operation goes through the policy engine and, when authorized, produces a cryptographic receipt.

| Category | Method | Description |
|---|---|---|
| **Actions** | `notarize()` | Run an action through the policy engine, return an Ed25519-signed receipt when authorized (supports `require_approval`) |
| | `get_action()` | Retrieve action details and receipt |
| | `list_actions()` | List actions with filters (type, agent, status) |
| | `authorize_action()` | Human co-signature on a high-stakes action |
| | `set_legal_hold()` | Prevent deletion, litigation hold |
| | `release_legal_hold()` | Release litigation hold |
| | `get_action_chain()` | Chain of custody for an action |
| | `verify_action()` | Public verification, no auth required |
| **Agents** | `register_agent()` | Register a verifiable agent identity |
| | `get_agent()` | Retrieve agent profile |
| | `list_agents()` | List registered agents |
| | `update_agent()` | Update agent metadata |
| | `publish_version()` | Publish a versioned agent config |
| | `list_versions()` | List agent versions |
| | `decommission_agent()` | Decommission an agent |
| | `transfer_agent()` | Transfer ownership to another org |
| | `get_agent_actions()` | List actions by agent |
| **Trust Layer** | `get_agent_did()` | Retrieve an agent's W3C DID (`did:web`) |
| | `rotate_agent_keys()` | Rotate an agent's Ed25519 signing keys |
| | `get_agent_credential()` | Get an agent's W3C Verifiable Credential |
| | `verify_credential()` | Verify a Verifiable Credential |
| | `revoke_credential()` | Revoke an agent's Verifiable Credential |
| | `request_mutual_sign()` | Initiate mutual notarization with a counterparty |
| | `complete_mutual_sign()` | Complete mutual notarization (counterparty signs) |
| | `get_reputation()` | Get an agent reputation score and tier |
| | `list_reputation_history()` | List reputation score history |
| | `resolve_did()` | Resolve any DID to its DID Document |
| **Cases** | `run_case()` | Multi-model consensus adjudication |
| | `get_case()` | Retrieve a case result |
| | `list_cases()` | List cases |
| **Receipts** | `get_receipt()` | Retrieve a cryptographic receipt |
| | `export_receipt()` | Export a receipt as JSON or PDF |
| **Evidence** | `create_evidence_package()` | Sealed, tamper-proof evidence bundle |
| | `list_evidence_packages()` | List evidence packages |
| | `get_evidence_package()` | Retrieve an evidence package |
| | `time_travel()` | Query actions at a point in time |
| | `liability_chain()` | Walk the full liability chain |
| **Estate** | `set_agent_will()` | Define a succession plan |
| | `get_agent_will()` | Retrieve an agent will |
| | `issue_death_certificate()` | Decommission with succession trigger |
| | `get_death_certificate()` | Retrieve a death certificate |
| | `create_compliance_snapshot()` | Compliance snapshot (EU AI Act, SR 11-7, GDPR) |
| | `list_compliance_snapshots()` | List snapshots by framework |
| **Escrow** | `create_escrow_account()` | Create a liability commitment ledger |
| | `list_escrow_accounts()` | List escrow accounts |
| | `get_escrow_account()` | Retrieve an escrow account |
| | `escrow_deposit()` | Record a liability commitment |
| | `escrow_release()` | Release a commitment after completion |
| | `escrow_dispute()` | Dispute, flag a liability issue |
| **Chat** | `ask()` | Query your notarized data via AI |
| **Offline** | `sync()` | Flush the offline queue to the API |
| **Session** | `session()` | Scoped session with pre-filled defaults |

---

## Links

- [Website](https://airaproof.com)
- [Documentation](https://docs.airaproof.com)
- [API Reference](https://docs.airaproof.com/docs/api-reference)
- [Interactive Demo](https://app.airaproof.com/demo), try Aira in your browser, no code needed
- [Dashboard](https://app.airaproof.com)
- [PyPI Package](https://pypi.org/project/aira-sdk/)
- [TypeScript SDK (npm)](https://www.npmjs.com/package/aira-sdk)
- [GitHub](https://github.com/aira-proof/python-sdk)
