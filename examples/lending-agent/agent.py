"""
Aira Lending Agent — Complete SDK example (two-step authorize + notarize flow).

Covers every feature of aira-sdk: authorization gating, notarization,
agents, cases, evidence, estate, escrow, chat, verification, async support.

Usage:
    pip install aira-sdk anthropic
    export AIRA_API_KEY="aira_live_xxx"
    export ANTHROPIC_API_KEY="sk-ant-..."
    python agent.py
"""

import hashlib
import json
import os
import sys

import anthropic
from aira import Aira, AiraError

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

AIRA_API_KEY = os.environ.get("AIRA_API_KEY")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
AIRA_BASE_URL = os.environ.get("AIRA_BASE_URL", "https://api.airaproof.com")

AGENT_SLUG = "lending-agent"
AGENT_VERSION = "1.0.0"
MODEL_ID = "claude-sonnet-4-6"

if not AIRA_API_KEY:
    print("Error: Set AIRA_API_KEY environment variable")
    print("  Get your key at https://app.airaproof.com/dashboard/api-keys")
    sys.exit(1)

if not ANTHROPIC_API_KEY:
    print("Error: Set ANTHROPIC_API_KEY environment variable")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Sample loan application
# ---------------------------------------------------------------------------

APPLICATION = {
    "applicant": "Maria Schmidt",
    "email": "maria.schmidt@example.de",
    "credit_score": 742,
    "annual_income_eur": 45_000,
    "employment_years": 3,
    "loan_amount_eur": 15_000,
    "loan_purpose": "Home renovation",
    "existing_debt_eur": 2_000,
}

SYSTEM_PROMPT = """You are a loan evaluation AI. Analyze the application and return a JSON decision.

Return ONLY valid JSON:
{
  "decision": "APPROVED" or "DENIED",
  "confidence": 0.0-1.0,
  "reasoning": "Brief explanation",
  "risk_factors": ["factor1", "factor2"],
  "recommended_rate": 3.5 (annual %, only if approved)
}

Evaluate based on: credit score (>700 good), debt-to-income ratio (<40% good),
employment stability (>2 years good), loan-to-income ratio (<50% good)."""


def evaluate_loan(application: dict) -> dict:
    """Call Claude to evaluate the loan application."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"Evaluate:\n{json.dumps(application, indent=2)}"}],
    )
    text = response.content[0].text
    return json.loads(text[text.find("{"):text.rfind("}") + 1])


def send_loan_email(applicant: str, decision: str) -> str:
    """Stub: pretend to send an email. Returns a fake provider ref."""
    return f"ses-msg-{hashlib.sha1(f'{applicant}:{decision}'.encode()).hexdigest()[:12]}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("\n" + "=" * 60)
    print("  Aira Lending Agent — Complete SDK Demo")
    print("=" * 60 + "\n")

    aira = Aira(api_key=AIRA_API_KEY, base_url=AIRA_BASE_URL)
    instruction_hash = f"sha256:{hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()}"

    # ══════════════════════════════════════════════════════════
    # 1. AGENT REGISTRY — register, version, update, list
    # ══════════════════════════════════════════════════════════

    print("1. Agent Registry")
    print("-" * 40)
    try:
        agent = aira.register_agent(
            agent_slug=AGENT_SLUG,
            display_name="Loan Decision Engine",
            description="AI-powered loan evaluation with multi-factor risk assessment",
            capabilities=["credit_scoring", "risk_assessment", "loan_evaluation"],
            public=True,
        )
        print(f"   - Registered: {agent.agent_slug}")

        version = aira.publish_version(
            slug=AGENT_SLUG,
            version=AGENT_VERSION,
            model_id=MODEL_ID,
            instruction_hash=instruction_hash,
            changelog="Initial release - single-model evaluation",
        )
        print(f"   - Version: {version.version}")
    except AiraError as e:
        if "EXISTS" in (e.code or ""):
            print(f"   - Already registered (skipped)")
        else:
            raise

    try:
        aira.update_agent(AGENT_SLUG, description="AI-powered loan evaluation v1.0")
        print(f"   - Updated description")
    except AiraError:
        pass

    agents = aira.list_agents(page=1)
    print(f"   - {agents.total} agent(s) in registry")
    detail = aira.get_agent(AGENT_SLUG)
    print(f"   - Status: {detail.status}")
    versions = aira.list_versions(AGENT_SLUG)
    print(f"   - {len(versions)} version(s)")
    print()

    # ══════════════════════════════════════════════════════════
    # 2. GATED ACTION — authorize BEFORE executing, notarize AFTER
    # ══════════════════════════════════════════════════════════

    print("2. Loan Decision (gated by Aira)")
    print("-" * 40)

    # Step 1: ASK for permission to evaluate this loan.
    auth = aira.authorize(
        action_type="loan_decision",
        details=json.dumps({
            "applicant": APPLICATION["applicant"],
            "amount": APPLICATION["loan_amount_eur"],
        }),
        agent_id=AGENT_SLUG,
        model_id=MODEL_ID,
        instruction_hash=instruction_hash,
        idempotency_key=f"loan-{APPLICATION['applicant'].replace(' ', '-').lower()}",
    )
    print(f"   - authorize() -> status={auth.status} action_id={auth.action_id[:16]}...")

    if auth.status == "pending_approval":
        print("   - Held for human review. Exiting — no decision made.")
        aira.close()
        return

    # Step 2: now that we're authorized, actually run the evaluation.
    evaluation = evaluate_loan(APPLICATION)
    decision = evaluation["decision"]
    confidence = evaluation["confidence"]
    print(f"   - AI decision: {decision} (confidence: {confidence})")

    # Step 3: report the outcome — this mints the cryptographic receipt.
    receipt = aira.notarize(
        action_id=auth.action_id,
        outcome="completed",
        outcome_details=json.dumps({"decision": decision, "confidence": confidence}),
    )
    print(f"   - notarize() -> status={receipt.status}")
    print(f"   - Signature: {receipt.signature[:30] if receipt.signature else 'none'}...")
    action_ids = [receipt.action_id]

    # Chain of custody — email as child action (also gated).
    email_auth = aira.authorize(
        action_type="email_sent",
        details=json.dumps({"to": APPLICATION["email"], "subject": f"Loan {decision}"}),
        agent_id=AGENT_SLUG,
        model_id=MODEL_ID,
        parent_action_id=receipt.action_id,
    )
    if email_auth.status == "authorized":
        ref = send_loan_email(APPLICATION["applicant"], decision)
        aira.notarize(
            action_id=email_auth.action_id,
            outcome="completed",
            outcome_details=f"sent via SES, ref={ref}",
        )
        print(f"   - Chained email: {email_auth.action_id[:16]}... (ref={ref})")
        action_ids.append(email_auth.action_id)

    # Listing / chain / filter
    action = aira.get_action(receipt.action_id)
    print(f"   - Action type: {action.action_type}")
    chain = aira.get_action_chain(receipt.action_id)
    print(f"   - Chain: {len(chain)} action(s)")
    actions_list = aira.list_actions(page=1, action_type="loan_decision")
    print(f"   - Loan decisions: {actions_list.total}")
    print()

    # ══════════════════════════════════════════════════════════
    # 3. CASES — multi-model consensus
    # ══════════════════════════════════════════════════════════

    print("3. Multi-Model Consensus")
    print("-" * 40)
    try:
        case = aira.run_case(
            details=f"Should we approve a EUR {APPLICATION['loan_amount_eur']:,} loan? Credit: {APPLICATION['credit_score']}, income: EUR {APPLICATION['annual_income_eur']:,}",
            models=[MODEL_ID, "gpt-5.2"],
        )
        consensus = case.get("consensus", {})
        print(f"   - Decision: {consensus.get('decision', 'N/A')}")
        print(f"   - Confidence: {consensus.get('confidence_score', 'N/A')}")
        print(f"   - Human review: {'yes' if consensus.get('requires_human_review') else 'no'}")

        cases_list = aira.list_cases(page=1)
        print(f"   - Total cases: {cases_list.total}")
    except AiraError as e:
        print(f"   - Skipped: {e.message}")
    print()

    # ══════════════════════════════════════════════════════════
    # 4. EVIDENCE — packages, time-travel
    # ══════════════════════════════════════════════════════════

    print("4. Evidence & Discovery")
    print("-" * 40)
    package = aira.create_evidence_package(
        title=f"Loan Decision - {APPLICATION['applicant']}",
        action_ids=action_ids,
        description=f"Audit trail for EUR {APPLICATION['loan_amount_eur']:,} loan. Decision: {decision}.",
    )
    print(f"   - Sealed: \"{package.title}\"")
    print(f"   - Hash: {package.package_hash[:30]}...")

    packages_list = aira.list_evidence_packages(page=1)
    print(f"   - Total packages: {packages_list.total}")

    pkg = aira.get_evidence_package(str(package.id))
    print(f"   - Retrieved: {pkg.title}")

    try:
        aira.time_travel(agent_slug=AGENT_SLUG, point_in_time="2030-01-01T00:00:00Z")
        print(f"   - Time-travel: queried")
    except AiraError:
        print(f"   - Time-travel: endpoint available")
    print()

    # ══════════════════════════════════════════════════════════
    # 5. ESTATE — will, compliance
    # ══════════════════════════════════════════════════════════

    print("5. Agent Estate & Compliance")
    print("-" * 40)
    try:
        aira.set_agent_will(
            slug=AGENT_SLUG,
            successor_slug=AGENT_SLUG,
            succession_policy="transfer_to_successor",
            data_retention_days=2555,
            notify_emails=["compliance@example.com"],
        )
        print(f"   - Will set: 2555-day retention")
    except AiraError:
        print(f"   - Will exists")

    will = aira.get_agent_will(AGENT_SLUG)
    if will:
        print(f"   - Policy: {will.get('succession_policy', 'N/A')}")

    snapshot = aira.create_compliance_snapshot(
        framework="eu-ai-act",
        agent_slug=AGENT_SLUG,
        findings={"art_12_logging": "pass", "art_13_transparency": "pass", "art_14_oversight": "pass"},
    )
    print(f"   - EU AI Act: {snapshot.status}")

    snapshots_list = aira.list_compliance_snapshots(page=1, framework="eu-ai-act")
    print(f"   - Snapshots: {snapshots_list.total}")
    print()

    # ══════════════════════════════════════════════════════════
    # 6. ESCROW
    # ══════════════════════════════════════════════════════════

    print("6. Escrow & Liability")
    print("-" * 40)
    try:
        account = aira.create_escrow_account(purpose=f"Loan liability - {APPLICATION['applicant']}")
        print(f"   - Account: {account.id[:16]}...")

        aira.escrow_deposit(account.id, amount=1500.00, description="10% liability deposit")
        print(f"   - Deposited: EUR 1,500")

        aira.escrow_release(account.id, amount=1500.00, description="Loan disbursed")
        print(f"   - Released: EUR 1,500")

        accounts_list = aira.list_escrow_accounts(page=1)
        print(f"   - Accounts: {accounts_list.total}")
    except AiraError as e:
        print(f"   - Skipped: {e.message}")
    print()

    # ══════════════════════════════════════════════════════════
    # 7. CHAT
    # ══════════════════════════════════════════════════════════

    print("7. Ask Aira")
    print("-" * 40)
    try:
        resp = aira.ask("How many loan decisions were notarized today?")
        print(f"   - {resp.get('content', '')[:80]}...")
    except AiraError as e:
        print(f"   - Skipped: {e.message}")
    print()

    # ══════════════════════════════════════════════════════════
    # 8. VERIFICATION — public, no auth
    # ══════════════════════════════════════════════════════════

    print("8. Public Verification")
    print("-" * 40)
    result = aira.verify_action(receipt.action_id)
    print(f"   - Valid: {result.valid}")
    print(f"   - Key: {result.public_key_id}")
    print(f"   - {result.message[:60]}...")
    print()

    # ══════════════════════════════════════════════════════════
    # 9. ERROR HANDLING — POLICY_DENIED example
    # ══════════════════════════════════════════════════════════

    print("9. Error Handling")
    print("-" * 40)
    try:
        aira.verify_action("00000000-0000-0000-0000-000000000000")
    except AiraError as e:
        print(f"   - Caught: [{e.code}] {e.message}")
    # POLICY_DENIED example — the details dict carries action_id + policy_id
    try:
        aira.authorize(
            action_type="wire_transfer",
            details="Attempt a wire — may be blocked by policy",
            agent_id=AGENT_SLUG,
        )
    except AiraError as e:
        if e.code == "POLICY_DENIED":
            print(
                f"   - Caught POLICY_DENIED: action_id={e.details.get('action_id')} "
                f"policy_id={e.details.get('policy_id')}"
            )
        else:
            print(f"   - Caught: [{e.code}] {e.message}")
    print()

    # ══════════════════════════════════════════════════════════

    print("=" * 60)
    print("  All 9 feature areas demonstrated.")
    print(f"  Dashboard: https://app.airaproof.com")
    print(f"  Docs:      https://docs.airaproof.com")
    print(f"  SDK:       pip install aira-sdk")
    print("=" * 60 + "\n")

    aira.close()


if __name__ == "__main__":
    main()
