"""End-to-end governance lifecycle demo.

Runs every governance primitive Aira ships in one script:

    authorize → notarize → baseline → drift check → bundle → settlement

Re-runnable: every creation step passes an idempotency_key so replays
return the original resource without double-billing.
"""
from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timedelta, timezone

from aira import Aira


AGENT_ID = "payments-agent-demo"


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def main() -> None:
    api_key = os.environ.get("AIRA_API_KEY")
    if not api_key:
        raise SystemExit("Set AIRA_API_KEY in your environment first.")

    aira = Aira(api_key=api_key)
    run_tag = uuid.uuid4().hex[:8]
    print(f"Governance lifecycle demo · run_tag={run_tag}\n")

    # ── 1. Authorize a wire transfer ─────────────────────────────────
    print("1. authorize(wire_transfer, €75,000)")
    auth = aira.authorize(
        action_type="wire_transfer",
        details="Transfer €75,000 to vendor-x for invoice #2026-1142",
        agent_id=AGENT_ID,
        context={"amount_eur": 75_000, "vendor": "vendor-x"},
    )
    print(f"   action_id={auth.action_id}  status={auth.status}")
    if auth.status != "authorized":
        print("   policy held the action — exiting demo.")
        return

    # ── 2. Notarize the outcome ──────────────────────────────────────
    print("\n2. notarize(completed)")
    receipt = aira.notarize(
        action_id=auth.action_id,
        outcome="completed",
        outcome_details="Transferred via Stripe Treasury #ts_01HX...",
    )
    print(f"   receipt_id={receipt.id}")
    print(f"   signature={receipt.signature[:32]}...")
    print(f"   signing_key={receipt.signing_key_id}")

    # ── 3. Seed a drift baseline ─────────────────────────────────────
    print("\n3. seed_synthetic_baseline(payments-agent-demo)")
    baseline = aira.seed_synthetic_baseline(
        agent_id=AGENT_ID,
        expected_distribution={"wire_transfer": 0.7, "ach_transfer": 0.25, "refund": 0.05},
        expected_actions_per_day=120,
    )
    print(f"   baseline_id={baseline['id']}  active={baseline['is_active']}")

    # ── 4. Drift check ───────────────────────────────────────────────
    print("\n4. run_drift_check(lookback_hours=1)")
    alert = aira.run_drift_check(AGENT_ID, lookback_hours=1)
    if alert is None:
        print("   no drift detected (expected for a single notarized action)")
    else:
        print(
            f"   drift alert {alert['id']} · kl={alert['kl_divergence']} "
            f"· severity={alert['severity']}"
        )

    # ── 5. Seal a compliance bundle ──────────────────────────────────
    print("\n5. create_compliance_bundle(iso_42001, last hour)")
    bundle_key = f"demo-bundle-{run_tag}"
    now = datetime.now(timezone.utc)
    bundle = aira.create_compliance_bundle(
        framework="iso_42001",
        period_start=_iso(now - timedelta(hours=1)),
        period_end=_iso(now + timedelta(minutes=1)),
        title=f"ISO 42001 evidence · {run_tag}",
        idempotency_key=bundle_key,
    )
    print(f"   bundle_id={bundle['id']}")
    print(f"   merkle_root={bundle['merkle_root']}")
    print(f"   receipt_count={bundle['receipt_count']}")
    print(f"   (retrying with idempotency_key={bundle_key!r} returns the same bundle)")

    # Retry — demonstrates idempotent replay
    replay = aira.create_compliance_bundle(
        framework="iso_42001",
        period_start=_iso(now - timedelta(hours=1)),
        period_end=_iso(now + timedelta(minutes=1)),
        title=f"ISO 42001 evidence · {run_tag}",
        idempotency_key=bundle_key,
    )
    assert replay["id"] == bundle["id"], "replay produced a different bundle!"
    print("   replay check: same bundle_id ✓")

    # ── 6. (Admin) seal a settlement ─────────────────────────────────
    print("\n6. create_settlement()  (admin-only)")
    try:
        settlement = aira.create_settlement()
        if settlement is None:
            print("   no unsettled receipts (already sealed by a scheduled run)")
        else:
            print(f"   settlement_id={settlement['id']}")
            print(f"   merkle_root={settlement['merkle_root']}")
            print(f"   receipt_count={settlement['receipt_count']}")
    except Exception as exc:
        print(f"   skipped (admin token required): {exc}")

    print("\nDone. Check /dashboard for the UI view of every object above.")


if __name__ == "__main__":
    main()
