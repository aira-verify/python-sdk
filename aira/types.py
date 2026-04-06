"""Aira SDK type definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ActionReceipt:
    action_id: str
    created_at: str
    request_id: str
    receipt_id: str | None = None
    payload_hash: str | None = None
    signature: str | None = None
    timestamp_token: str | None = None
    status: str = "notarized"
    warnings: list[str] | None = None
    policy_evaluation: dict | None = None  # {policy_id, policy_name, decision, reasoning, confidence}


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
    valid: bool
    public_key_id: str
    message: str
    verified_at: str
    request_id: str
    receipt_id: str | None = None
    action_id: str | None = None


@dataclass
class PaginatedList:
    data: list[dict]
    total: int
    page: int
    per_page: int
    has_more: bool
