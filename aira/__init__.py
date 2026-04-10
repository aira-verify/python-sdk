"""Aira SDK — AI governance infrastructure.

Two-step flow:

    from aira import Aira

    aira = Aira(api_key="aira_live_xxx")

    # Step 1: ask Aira for permission
    auth = aira.authorize(
        action_type="wire_transfer",
        details="Send €75K to vendor X",
        agent_id="payments-agent",
    )

    if auth.status == "authorized":
        # Step 2: execute, then report outcome
        result = send_wire(75000, to="vendor-x")
        aira.notarize(
            action_id=auth.action_id,
            outcome="completed",
            outcome_details=f"Sent. ref={result.id}",
        )
    elif auth.status == "pending_approval":
        queue.enqueue(auth.action_id)  # wait for approver
    # POLICY_DENIED is raised as AiraError
"""

from aira.client import Aira, AsyncAira, AiraError, AiraSession, AsyncAiraSession
from aira.types import (
    ActionReceipt,
    ActionDetail,
    AgentDetail,
    AgentVersion,
    Authorization,
    ComplianceSnapshot,
    CosignResult,
    EscrowAccount,
    EscrowTransaction,
    EvidencePackage,
    PaginatedList,
    VerifyResult,
)

__version__ = "2.0.0"

__all__ = [
    "Aira",
    "AsyncAira",
    "AiraError",
    "AiraSession",
    "AsyncAiraSession",
    "ActionReceipt",
    "ActionDetail",
    "AgentDetail",
    "AgentVersion",
    "Authorization",
    "ComplianceSnapshot",
    "CosignResult",
    "EscrowAccount",
    "EscrowTransaction",
    "EvidencePackage",
    "PaginatedList",
    "VerifyResult",
]
