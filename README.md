# Aira Python SDK

Legal infrastructure for AI agents. Notarize actions, register agents, build evidence packages, manage lifecycle, escrow liability.

[![PyPI version](https://img.shields.io/pypi/v/aira-sdk.svg)](https://pypi.org/project/aira-sdk/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

```bash
pip install aira-sdk
```

## Quick Start

```python
from aira import Aira

aira = Aira(api_key="aira_live_xxx")

# Notarize an agent action
receipt = aira.notarize(
    action_type="email_sent",
    details="Sent onboarding email to customer@example.com",
    agent_id="support-agent",
    model_id="claude-sonnet-4-6",
    instruction_hash="sha256:a1b2c3...",
)

print(receipt.payload_hash)   # sha256:e5f6a7b8...
print(receipt.signature)       # ed25519:base64url...
print(receipt.action_id)       # uuid
```

## Decorator -- Auto-Notarize Functions

```python
@aira.trace(agent_id="lending-agent", action_type="loan_decision")
def approve_loan(application):
    decision = model.predict(application)
    return decision

# Every call to approve_loan() is automatically notarized
result = approve_loan({"credit_score": 742, "income": 45000})
```

The decorator is non-blocking -- if notarization fails, your function still returns normally. Arguments and return values are never sent to the API; only a metadata hash is recorded.

## Async Support

```python
from aira import AsyncAira

async with AsyncAira(api_key="aira_live_xxx") as aira:
    receipt = await aira.notarize(
        action_type="contract_signed",
        details="Agent signed vendor agreement #1234",
        agent_id="procurement-agent",
    )

    # Async decorator
    @aira.trace(agent_id="my-agent")
    async def process_order(order):
        return await execute(order)
```

## Agent Registry

```python
# Register an agent
agent = aira.register_agent(
    agent_slug="support-agent-v2",
    display_name="Customer Support Agent",
    capabilities=["email", "chat", "tickets"],
    public=True,
)

# Publish a version
version = aira.publish_version(
    slug="support-agent-v2",
    version="1.0.0",
    model_id="claude-sonnet-4-6",
    changelog="Initial release",
)

# List all agents
agents, pagination = aira.list_agents(page=1)

# Decommission
aira.decommission_agent("old-agent")
```

## Action Notarization

```python
# Notarize with full parameters
receipt = aira.notarize(
    action_type="loan_approved",
    details="Approved loan #4521 for $25,000",
    agent_id="lending-agent",
    model_id="claude-sonnet-4-6",
    instruction_hash="sha256:...",
    idempotency_key="loan-4521",  # Prevents duplicate notarizations
)

# Retrieve action details
action = aira.get_action("action-uuid")
print(action.action_type)
print(action.receipt)

# List actions with filters
actions, pagination = aira.list_actions(
    page=1,
    action_type="loan_approved",
    agent_id="lending-agent",
)

# Human co-signature
aira.authorize_action("action-uuid", authorizer_email="compliance@acme.com")

# Legal hold
aira.set_legal_hold("action-uuid")
aira.release_legal_hold("action-uuid")

# Chain of custody
chain = aira.get_action_chain("action-uuid")
```

## Evidence Packages

```python
# Bundle actions into a sealed evidence package
package = aira.create_evidence_package(
    title="Q1 2026 Audit Trail -- Lending Agent",
    action_ids=["act-uuid-1", "act-uuid-2", "act-uuid-3"],
    description="All lending decisions for regulatory review",
)

print(package.package_hash)  # Cryptographically sealed
print(package.signature)     # Ed25519 signed

# List and retrieve
packages, pagination = aira.list_evidence_packages(page=1)
pkg = aira.get_evidence_package("package-uuid")

# Time travel -- query actions at a point in time
result = aira.time_travel(
    agent_id="lending-agent",
    point_in_time="2026-01-15T00:00:00Z",
)
```

## Compliance Snapshots

```python
snapshot = aira.create_compliance_snapshot(
    framework="eu-ai-act",
    agent_slug="lending-agent",
    findings={"art_12_logging": "pass", "art_14_oversight": "pass"},
)

# List by framework
snapshots, pagination = aira.list_compliance_snapshots(
    page=1,
    framework="eu-ai-act",
)
```

## Agent Will & Estate

```python
# Set succession plan
aira.set_agent_will(
    slug="support-agent-v2",
    successor_slug="support-agent-v3",
    succession_policy="transfer_to_successor",
    data_retention_days=2555,
    notify_emails=["compliance@acme.com"],
)

# Retrieve will
will = aira.get_agent_will("support-agent-v2")

# Issue death certificate (triggers succession)
aira.issue_death_certificate("old-agent", reason="Replaced by v3")

# Retrieve death certificate
cert = aira.get_death_certificate("old-agent")
```

## Escrow

```python
# Create escrow account
account = aira.create_escrow_account(purpose="Vendor contract #4521")

# Deposit before agent acts
tx = aira.escrow_deposit(account.id, amount=5000.00, description="10% liability deposit")

# Release after successful completion
aira.escrow_release(account.id, amount=5000.00)

# Dispute if something goes wrong
aira.escrow_dispute(account.id, amount=2000.00, description="Incorrect vendor payment")

# List accounts
accounts, pagination = aira.list_escrow_accounts(page=1)
```

## Cases (Multi-Model Adjudication)

```python
# Run a case across multiple AI models
case = aira.run_case(
    details="Should we approve loan application #4521?",
    models=["claude-sonnet-4-6", "gpt-4o", "gemini-2.0-flash"],
)

print(case["consensus"]["decision"])    # "approve"
print(case["consensus"]["confidence"])  # 0.92

# List cases
cases, pagination = aira.list_cases(page=1)
```

## Ask Aira (Chat)

```python
response = aira.ask("How many email actions were notarized this week?")
print(response["content"])
```

## Public Verification

```python
# Anyone can verify -- no auth needed
result = aira.verify_action("action-uuid")
print(result.valid)     # True
print(result.message)   # "Action receipt exists and signing key is valid."
```

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

## Configuration

```python
aira = Aira(
    api_key="aira_live_xxx",
    base_url="https://your-self-hosted.com",  # Self-hosted
    timeout=60.0,                               # Request timeout
)
```

## Development

```bash
git clone https://github.com/aira-verify/python-sdk.git
cd python-sdk
pip install -e ".[dev]"
pytest
```

## License

MIT

## Links

- [Documentation](https://docs.airaproof.com)
- [API Reference](https://docs.airaproof.com/docs/api-reference)
- [Dashboard](https://app.airaproof.com)
- [GitHub](https://github.com/aira-verify/python-sdk)
