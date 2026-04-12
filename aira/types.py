"""Aira SDK type definitions."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Authorization:
    """Response from :meth:`Aira.authorize` — step 1 of the two-step flow.

    Status values:
    - ``"authorized"``: the agent may now execute the action, then call
      :meth:`Aira.notarize` with ``action_id`` to mint the receipt.
    - ``"pending_approval"``: the action is held for human review. The agent
      should not execute yet — wait for an approver to act, then poll
      :meth:`Aira.get_action` or handle the ``action.approved`` webhook.
    """

    action_id: str
    status: str  # "authorized" | "pending_approval"
    created_at: str
    request_id: str
    warnings: list[str] | None = None


@dataclass
class ActionReceipt:
    """Response from :meth:`Aira.notarize` — step 2 of the two-step flow.

    Status values:
    - ``"notarized"``: the action outcome was reported as ``"completed"`` and
      a cryptographic receipt has been minted. ``receipt_id``, ``payload_hash``,
      and ``signature`` are populated.
    - ``"failed"``: the action outcome was reported as ``"failed"``. No
      receipt is minted — signature/payload_hash/receipt_id will be ``None``.
    """

    action_id: str
    status: str  # "notarized" | "failed"
    created_at: str
    request_id: str
    receipt_id: str | None = None
    payload_hash: str | None = None
    signature: str | None = None
    timestamp_token: str | None = None
    warnings: list[str] | None = None


@dataclass
class CosignResult:
    """Response from :meth:`Aira.cosign_action` — human co-signature on an action."""

    action_id: str
    cosigner_email: str
    cosigned_at: str
    cosignature_id: str
    request_id: str | None = None


@dataclass
class AuthorizationSummary:
    id: str
    authorizer_email: str
    authorized_at: str | None


@dataclass
class ReceiptSummary:
    receipt_id: str
    payload_hash: str
    signature: str
    public_key_id: str
    timestamp_token: str | None
    receipt_version: str
    verify_url: str
    created_at: str | None = None


@dataclass
class ActionDetail:
    action_id: str
    org_id: str
    action_type: str
    status: str
    legal_hold: bool
    action_details_hash: str
    created_at: str
    request_id: str
    agent_id: str | None = None
    agent_version: str | None = None
    instruction_hash: str | None = None
    details_storage_key: str | None = None
    model_id: str | None = None
    model_version: str | None = None
    parent_action_id: str | None = None
    receipt: ReceiptSummary | None = None
    system_prompt_hash: str | None = None
    tool_inputs_hash: str | None = None
    model_params: dict | None = None
    execution_env: dict | None = None
    authorizations: list[AuthorizationSummary] = field(default_factory=list)


@dataclass
class AgentVersion:
    id: str
    version: str
    status: str
    created_at: str
    changelog: str | None = None
    model_id: str | None = None
    instruction_hash: str | None = None
    config_hash: str | None = None
    published_at: str | None = None


@dataclass
class AgentDetail:
    id: str
    agent_slug: str
    display_name: str
    status: str
    public: bool
    registered_at: str
    request_id: str
    description: str | None = None
    capabilities: list[str] | None = None
    metadata: dict | None = None
    versions: list[AgentVersion] = field(default_factory=list)


@dataclass
class EvidencePackage:
    id: str
    title: str
    action_ids: list[str]
    package_hash: str
    signature: str
    status: str
    created_at: str
    request_id: str
    description: str | None = None
    agent_slugs: list[str] | None = None


@dataclass
class ComplianceSnapshot:
    id: str
    framework: str
    status: str
    findings: dict
    snapshot_hash: str
    signature: str
    snapshot_at: str
    created_at: str
    request_id: str
    agent_id: str | None = None


@dataclass
class EscrowTransaction:
    id: str
    transaction_type: str
    amount: str
    currency: str
    transaction_hash: str
    signature: str
    status: str
    created_at: str
    description: str | None = None
    reference_action_id: str | None = None


@dataclass
class EscrowAccount:
    id: str
    currency: str
    balance: str
    status: str
    created_at: str
    request_id: str
    agent_id: str | None = None
    counterparty_org_id: str | None = None
    purpose: str | None = None
    transactions: list[EscrowTransaction] = field(default_factory=list)


@dataclass
class VerifyResult:
    """Result of a public action receipt verification.

    The endpoint actually recomputes the SHA-256 hash and verifies the
    Ed25519 signature against the published public key — ``valid`` is the
    result of that real cryptographic check, not just an existence check.

    On a successful (or tamper-detected) verification the result includes
    the full evidence — ``signature``, ``public_key``, ``signed_payload``,
    ``timestamp_token`` — so an external auditor can re-run the same check
    with OpenSSL or any Ed25519 library without trusting Aira's verdict.
    """
    valid: bool
    public_key_id: str
    message: str
    verified_at: str
    request_id: str
    receipt_id: str | None = None
    action_id: str | None = None
    payload_hash: str | None = None
    signature: str | None = None
    public_key: str | None = None
    algorithm: str | None = None
    timestamp_token: str | None = None
    signed_payload: dict | None = None
    policy_evaluator_attestation: dict | None = None


@dataclass
class PaginatedList:
    data: list[dict]
    total: int
    page: int
    per_page: int
    has_more: bool
