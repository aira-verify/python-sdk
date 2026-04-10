"""Aira SDK client — sync and async with full API coverage."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from aira._offline import OfflineQueue
from aira.types import (
    ActionDetail,
    ActionReceipt,
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

logger = logging.getLogger("aira")

DEFAULT_BASE_URL = "https://api.airaproof.com"
DEFAULT_TIMEOUT = 30.0
MAX_DETAILS_LENGTH = 50_000


class AiraError(Exception):
    """Aira API error.

    Attributes:
        status: HTTP status code.
        code: Error code string (e.g. ``"POLICY_DENIED"``, ``"NOT_FOUND"``).
        message: Human-readable error message.
        details: Optional dict with additional context from the backend.
            For ``POLICY_DENIED`` errors this includes ``action_id`` and
            ``policy_id`` of the policy that denied the action.
    """

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        details: dict | None = None,
    ) -> None:
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(f"[{code}] {message}")


def _handle_response(resp: httpx.Response) -> dict:
    if resp.status_code >= 400:
        try:
            body = resp.json()
        except Exception:
            body = {"error": resp.text, "code": "UNKNOWN"}
        raise AiraError(
            resp.status_code,
            body.get("code", "UNKNOWN"),
            body.get("error", resp.text),
            details=body.get("details"),
        )
    if resp.status_code == 204:
        return {}
    return resp.json()


def _to_dataclass(cls: type, data: dict) -> Any:
    """Convert dict to dataclass, ignoring extra fields."""
    valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
    filtered = {k: v for k, v in data.items() if k in valid_fields}
    return cls(**filtered)


def _paginated(data: dict) -> PaginatedList:
    return PaginatedList(
        data=data["data"], total=data["pagination"]["total"],
        page=data["pagination"]["page"], per_page=data["pagination"]["per_page"],
        has_more=data["pagination"]["has_more"],
    )


def _validate_api_key(api_key: str) -> None:
    if not api_key:
        raise ValueError("api_key is required")
    if not api_key.startswith(("aira_live_", "aira_test_")):
        logger.warning("API key does not start with 'aira_live_' or 'aira_test_' — is this correct?")


def _truncate_details(text: str) -> str:
    """Truncate details to max length."""
    if len(text) > MAX_DETAILS_LENGTH:
        text = text[:MAX_DETAILS_LENGTH] + "...[truncated]"
    return text


def _build_body(**kwargs: Any) -> dict:
    """Build request body, filtering out None values."""
    return {k: v for k, v in kwargs.items() if v is not None}


class Aira:
    """Synchronous Aira client.

    Usage:
        aira = Aira(api_key="aira_live_xxx")

        # Step 1: ask Aira for permission
        auth = aira.authorize(
            action_type="wire_transfer",
            details="Send €75K to vendor X",
            agent_id="payments-agent",
        )

        if auth.status == "authorized":
            # Step 2: execute, then report outcome
            result = send_wire(75000)
            aira.notarize(
                action_id=auth.action_id,
                outcome="completed",
                outcome_details=f"Sent. ref={result.id}",
            )
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        offline: bool = False,
    ) -> None:
        _validate_api_key(api_key)
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = httpx.Client(
            base_url=f"{self.base_url}/api/v1",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=timeout,
        )
        # Separate unauthenticated client for public endpoints
        self._public_client = httpx.Client(
            base_url=f"{self.base_url}/api/v1",
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )
        self._queue: OfflineQueue | None = OfflineQueue() if offline else None

    def close(self) -> None:
        self._client.close()
        self._public_client.close()

    def __enter__(self) -> Aira:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

    def _post(self, path: str, body: dict) -> dict:
        if self._queue is not None:
            qid = self._queue.enqueue("POST", path, body)
            return {"_offline": True, "_queue_id": qid}
        return _handle_response(self._client.post(path, json=body))

    def _get(self, path: str, params: dict | None = None) -> dict:
        if self._queue is not None:
            raise AiraError(0, "OFFLINE", "GET requests not available in offline mode")
        return _handle_response(self._client.get(path, params=params))

    def _put(self, path: str, body: dict) -> dict:
        if self._queue is not None:
            qid = self._queue.enqueue("PUT", path, body)
            return {"_offline": True, "_queue_id": qid}
        return _handle_response(self._client.put(path, json=body))

    def _delete(self, path: str) -> dict:
        if self._queue is not None:
            qid = self._queue.enqueue("DELETE", path, {})
            return {"_offline": True, "_queue_id": qid}
        return _handle_response(self._client.delete(path))

    # ==================== Actions ====================

    def authorize(
        self,
        action_type: str,
        details: str,
        agent_id: str | None = None,
        agent_version: str | None = None,
        instruction_hash: str | None = None,
        model_id: str | None = None,
        model_version: str | None = None,
        parent_action_id: str | None = None,
        endpoint_url: str | None = None,
        store_details: bool = False,
        idempotency_key: str | None = None,
        require_approval: bool = False,
        approvers: list[str] | None = None,
    ) -> Authorization:
        """Step 1 of 2: ask Aira for permission to perform an action.

        This creates an action record and runs it through your org's policy
        engine before the agent executes anything. The returned
        :class:`Authorization` has a status that tells the agent what to do:

        - ``"authorized"``: agent may now execute, then call :meth:`notarize`
          with the returned ``action_id`` to mint the receipt.
        - ``"pending_approval"``: held for human review. The agent should not
          execute — wait for an approver to act on it, then handle the
          ``action.approved`` webhook or poll :meth:`get_action`.

        Raises:
            AiraError: with ``code="POLICY_DENIED"`` if a policy denied the
                action. ``error.details`` contains ``action_id`` and
                ``policy_id``. Other codes include ``ENDPOINT_TLS_MISMATCH``,
                ``ENDPOINT_NOT_WHITELISTED``, ``DUPLICATE_REQUEST``.
        """
        body = _build_body(
            action_type=action_type,
            details=_truncate_details(details),
            agent_id=agent_id,
            agent_version=agent_version,
            instruction_hash=instruction_hash,
            model_id=model_id,
            model_version=model_version,
            parent_action_id=parent_action_id,
            endpoint_url=endpoint_url,
            idempotency_key=idempotency_key,
            require_approval=require_approval or None,
            approvers=approvers,
        )
        if store_details:
            body["store_details"] = True
        return _to_dataclass(Authorization, self._post("/actions", body))

    def notarize(
        self,
        action_id: str,
        outcome: str = "completed",
        outcome_details: str | None = None,
    ) -> ActionReceipt:
        """Step 2 of 2: report what actually happened for an authorized action.

        Call this after the agent has executed the action that was previously
        approved by :meth:`authorize`. Mints the cryptographic receipt if the
        outcome is ``"completed"``. If the outcome is ``"failed"`` no receipt
        is minted — the action record just transitions to the failed state.

        Args:
            action_id: The ``action_id`` returned by :meth:`authorize`.
            outcome: ``"completed"`` or ``"failed"``.
            outcome_details: Optional free-form text describing the outcome
                (e.g. ``"Wire sent, ref TX12345"`` or ``"Rejected by upstream API"``).

        Raises:
            AiraError: with ``code="INVALID_STATE"`` if the action is not in
                ``authorized`` or ``approved`` state (e.g. already notarized,
                pending approval, or denied).
        """
        body = _build_body(outcome=outcome, outcome_details=outcome_details)
        return _to_dataclass(
            ActionReceipt, self._post(f"/actions/{action_id}/notarize", body)
        )

    def get_action(self, action_id: str) -> ActionDetail:
        """Get full action details including receipt and authorizations."""
        return _to_dataclass(ActionDetail, self._get(f"/actions/{action_id}"))

    def list_actions(
        self, page: int = 1, per_page: int = 20,
        action_type: str | None = None, agent_id: str | None = None, status: str | None = None,
    ) -> PaginatedList:
        """List actions with filters."""
        params = _build_body(page=page, per_page=per_page, action_type=action_type, agent_id=agent_id, status=status)
        return _paginated(self._get("/actions", params))

    def cosign_action(self, action_id: str) -> CosignResult:
        """Human co-signature on an authorized or notarized action.

        Used for high-stakes actions where a human signs alongside the agent.
        Requires JWT auth (dashboard user, not an API key).
        """
        return _to_dataclass(
            CosignResult, self._post(f"/actions/{action_id}/cosign", {})
        )

    def set_legal_hold(self, action_id: str) -> dict:
        """Set legal hold — prevents deletion."""
        return self._post(f"/actions/{action_id}/hold", {})

    def release_legal_hold(self, action_id: str) -> dict:
        """Release legal hold."""
        return self._delete(f"/actions/{action_id}/hold")

    def get_action_chain(self, action_id: str) -> list[dict]:
        """Get chain of custody."""
        return self._get(f"/actions/{action_id}/chain").get("chain", [])

    def verify_action(self, action_id: str) -> VerifyResult:
        """Public verification — no auth needed."""
        data = _handle_response(self._public_client.get(f"/verify/action/{action_id}"))
        return _to_dataclass(VerifyResult, data)

    # ==================== Agents ====================

    def register_agent(
        self,
        agent_slug: str,
        display_name: str,
        description: str | None = None,
        capabilities: list[str] | None = None,
        public: bool = False,
    ) -> AgentDetail:
        """Register a new agent identity."""
        body = _build_body(
            agent_slug=agent_slug, display_name=display_name,
            description=description, capabilities=capabilities, public=public,
        )
        return _to_dataclass(AgentDetail, self._post("/agents", body))

    def get_agent(self, slug: str) -> AgentDetail:
        return _to_dataclass(AgentDetail, self._get(f"/agents/{slug}"))

    def list_agents(self, page: int = 1, status: str | None = None) -> PaginatedList:
        return _paginated(self._get("/agents", _build_body(page=page, status=status)))

    def update_agent(self, slug: str, **fields: Any) -> AgentDetail:
        """Update agent metadata (display_name, description, capabilities, public)."""
        return _to_dataclass(AgentDetail, self._put(f"/agents/{slug}", _build_body(**fields)))

    def publish_version(
        self, slug: str, version: str, changelog: str | None = None,
        model_id: str | None = None, instruction_hash: str | None = None, config_hash: str | None = None,
    ) -> AgentVersion:
        body = _build_body(version=version, changelog=changelog, model_id=model_id, instruction_hash=instruction_hash, config_hash=config_hash)
        return _to_dataclass(AgentVersion, self._post(f"/agents/{slug}/versions", body))

    def list_versions(self, slug: str) -> list[AgentVersion]:
        data = self._get(f"/agents/{slug}/versions")
        return [_to_dataclass(AgentVersion, v) for v in data] if isinstance(data, list) else []

    def decommission_agent(self, slug: str) -> AgentDetail:
        return _to_dataclass(AgentDetail, self._post(f"/agents/{slug}/decommission", {}))

    def transfer_agent(self, slug: str, to_org_id: str, reason: str | None = None) -> dict:
        """Transfer agent ownership to another organization."""
        return self._post(f"/agents/{slug}/transfer", _build_body(to_org_id=to_org_id, reason=reason))

    def get_agent_actions(self, slug: str, page: int = 1) -> PaginatedList:
        """List actions performed by this agent."""
        return _paginated(self._get(f"/agents/{slug}/actions", {"page": page}))

    # ==================== Cases ====================

    def run_case(self, details: str, models: list[str], **options: Any) -> dict:
        body: dict[str, Any] = {"details": details, "models": models}
        if options:
            body["options"] = options
        return self._post("/cases", body)

    def get_case(self, case_id: str) -> dict:
        return self._get(f"/cases/{case_id}")

    def list_cases(self, page: int = 1) -> PaginatedList:
        return _paginated(self._get("/cases", {"page": page}))

    # ==================== Receipts ====================

    def get_receipt(self, receipt_id: str) -> dict:
        return self._get(f"/receipts/{receipt_id}")

    def export_receipt(self, receipt_id: str, format: str = "json") -> dict:
        """Export receipt. format: 'json' or 'pdf'."""
        return self._get(f"/receipts/{receipt_id}/export", {"format": format})

    # ==================== Evidence ====================

    def create_evidence_package(
        self, title: str, action_ids: list[str], description: str | None = None,
        agent_slugs: list[str] | None = None,
    ) -> EvidencePackage:
        body = _build_body(title=title, action_ids=action_ids, description=description, agent_slugs=agent_slugs)
        return _to_dataclass(EvidencePackage, self._post("/evidence/packages", body))

    def list_evidence_packages(self, page: int = 1) -> PaginatedList:
        return _paginated(self._get("/evidence/packages", {"page": page}))

    def get_evidence_package(self, package_id: str) -> EvidencePackage:
        return _to_dataclass(EvidencePackage, self._get(f"/evidence/packages/{package_id}"))

    def time_travel(self, point_in_time: str, agent_slug: str | None = None, action_type: str | None = None) -> dict:
        """Query actions as they existed at a point in time."""
        return self._post("/evidence/time-travel", _build_body(point_in_time=point_in_time, agent_slug=agent_slug, action_type=action_type))

    def liability_chain(self, action_id: str, max_depth: int = 10) -> list[dict]:
        """Walk the full liability chain for an action."""
        data = self._get(f"/evidence/liability-chain/{action_id}", {"max_depth": max_depth})
        return data.get("chain", [])

    # ==================== Estate ====================

    def set_agent_will(
        self, slug: str, successor_slug: str | None = None,
        succession_policy: str = "transfer_to_successor",
        data_retention_days: int | None = None,
        notify_emails: list[str] | None = None,
        instructions: str | None = None,
    ) -> dict:
        body = _build_body(
            successor_slug=successor_slug, succession_policy=succession_policy,
            data_retention_days=data_retention_days, notify_emails=notify_emails, instructions=instructions,
        )
        return self._put(f"/estate/agents/{slug}/will", body)

    def get_agent_will(self, slug: str) -> dict:
        return self._get(f"/estate/agents/{slug}/will")

    def issue_death_certificate(self, slug: str, reason: str = "Decommissioned by organization") -> dict:
        return self._post(f"/estate/agents/{slug}/death-certificate", {"reason": reason})

    def get_death_certificate(self, slug: str) -> dict:
        return self._get(f"/estate/agents/{slug}/death-certificate")

    def create_compliance_snapshot(
        self, framework: str, agent_slug: str | None = None, findings: dict | None = None,
    ) -> ComplianceSnapshot:
        body = _build_body(framework=framework, agent_slug=agent_slug, findings=findings)
        return _to_dataclass(ComplianceSnapshot, self._post("/estate/compliance", body))

    def list_compliance_snapshots(self, page: int = 1, framework: str | None = None) -> PaginatedList:
        return _paginated(self._get("/estate/compliance", _build_body(page=page, framework=framework)))

    # ==================== Escrow ====================

    def create_escrow_account(
        self, purpose: str | None = None, currency: str = "EUR",
        agent_id: str | None = None, counterparty_org_id: str | None = None,
    ) -> EscrowAccount:
        body = _build_body(purpose=purpose, currency=currency, agent_id=agent_id, counterparty_org_id=counterparty_org_id)
        return _to_dataclass(EscrowAccount, self._post("/escrow/accounts", body))

    def list_escrow_accounts(self, page: int = 1) -> PaginatedList:
        return _paginated(self._get("/escrow/accounts", {"page": page}))

    def get_escrow_account(self, account_id: str) -> EscrowAccount:
        return _to_dataclass(EscrowAccount, self._get(f"/escrow/accounts/{account_id}"))

    def escrow_deposit(self, account_id: str, amount: float, description: str | None = None, reference_action_id: str | None = None) -> EscrowTransaction:
        body = _build_body(amount=amount, description=description, reference_action_id=reference_action_id)
        return _to_dataclass(EscrowTransaction, self._post(f"/escrow/accounts/{account_id}/deposit", body))

    def escrow_release(self, account_id: str, amount: float, description: str | None = None, reference_action_id: str | None = None) -> EscrowTransaction:
        body = _build_body(amount=amount, description=description, reference_action_id=reference_action_id)
        return _to_dataclass(EscrowTransaction, self._post(f"/escrow/accounts/{account_id}/release", body))

    def escrow_dispute(self, account_id: str, amount: float, description: str, reference_action_id: str | None = None) -> EscrowTransaction:
        body = _build_body(amount=amount, description=description, reference_action_id=reference_action_id)
        return _to_dataclass(EscrowTransaction, self._post(f"/escrow/accounts/{account_id}/dispute", body))

    # ==================== Chat ====================

    def ask(self, message: str, history: list[dict] | None = None, model: str | None = None) -> dict:
        """Ask Aira a question about your data."""
        return self._post("/chat", _build_body(message=message, history=history, model_id=model))

    # ==================== DID ====================

    def get_agent_did(self, slug: str) -> dict:
        """Get full DID info for an agent."""
        return self._get(f"/agents/{slug}/did")

    def rotate_agent_keys(self, slug: str) -> dict:
        """Rotate an agent's DID keypair."""
        return self._post(f"/agents/{slug}/did/rotate", {})

    def resolve_did(self, did: str) -> dict:
        """Resolve any did:web DID to its DID document."""
        return self._post("/dids/resolve", {"did": did})

    # ==================== Verifiable Credentials ====================

    def get_agent_credential(self, slug: str) -> dict:
        """Get the current valid VC for an agent."""
        return self._get(f"/agents/{slug}/credential")

    def get_agent_credentials(self, slug: str) -> dict:
        """Get full credential history for an agent."""
        return self._get(f"/agents/{slug}/credentials")

    def revoke_credential(self, slug: str, reason: str = "") -> dict:
        """Revoke the current credential for an agent."""
        return self._post(f"/agents/{slug}/credentials/revoke", {"reason": reason})

    def verify_credential(self, credential: dict) -> dict:
        """Verify a Verifiable Credential — checks signature, expiry, revocation."""
        return self._post("/credentials/verify", {"credential": credential})

    # ==================== Mutual Notarization ====================

    def request_mutual_sign(self, action_id: str, counterparty_did: str) -> dict:
        """Initiate a mutual signing request for an action."""
        return self._post(f"/actions/{action_id}/mutual-sign/request", {"counterparty_did": counterparty_did})

    def get_pending_mutual_sign(self, action_id: str) -> dict:
        """Get the action payload awaiting counterparty signature."""
        return self._get(f"/actions/{action_id}/mutual-sign/pending")

    def complete_mutual_sign(self, action_id: str, did: str, signature: str, signed_payload_hash: str) -> dict:
        """Submit counterparty signature to complete mutual signing."""
        return self._post(f"/actions/{action_id}/mutual-sign/complete", {"did": did, "signature": signature, "signed_payload_hash": signed_payload_hash})

    def get_mutual_sign_receipt(self, action_id: str) -> dict:
        """Get the co-signed receipt for a mutually signed action."""
        return self._get(f"/actions/{action_id}/mutual-sign/receipt")

    def reject_mutual_sign(self, action_id: str, reason: str = "") -> dict:
        """Reject a mutual signing request."""
        return self._post(f"/actions/{action_id}/mutual-sign/reject", {"reason": reason})

    # ==================== Reputation ====================

    def get_reputation(self, slug: str) -> dict:
        """Get current reputation score for an agent."""
        return self._get(f"/agents/{slug}/reputation")

    def get_reputation_history(self, slug: str) -> dict:
        """Get full reputation history for an agent."""
        return self._get(f"/agents/{slug}/reputation/history")

    def attest_reputation(self, slug: str, counterparty_did: str, action_id: str, attestation: str, signature: str) -> dict:
        """Submit a signed attestation of a successful interaction."""
        return self._post(f"/agents/{slug}/reputation/attest", {"counterparty_did": counterparty_did, "action_id": action_id, "attestation": attestation, "signature": signature})

    def verify_reputation(self, slug: str) -> dict:
        """Verify a reputation score by returning inputs and score_hash."""
        return self._get(f"/agents/{slug}/reputation/verify")

    # ==================== Offline sync ====================

    @property
    def pending_count(self) -> int:
        """Number of requests queued for sync. Returns 0 if not in offline mode."""
        return self._queue.pending_count if self._queue else 0

    def sync(self) -> list:
        """Flush offline queue to API. Returns list of API responses."""
        if self._queue is None:
            raise ValueError("sync() is only available in offline mode")
        items = self._queue.drain()
        results = []
        for item in items:
            resp = self._client.request(item.method, item.path, json=item.body)
            if resp.status_code >= 400:
                # Continue flushing but track failures
                results.append({"_error": True, "_status": resp.status_code, "_queue_id": item.id})
            else:
                results.append(resp.json())
        return results

    # ==================== Session ====================

    def session(self, agent_id: str, **defaults: Any) -> AiraSession:
        """Create a scoped session with pre-filled defaults for authorize()."""
        return AiraSession(self, agent_id=agent_id, **defaults)


class AiraSession:
    """Scoped session with pre-filled defaults for :meth:`Aira.authorize`.

    Every ``authorize()`` call on the session inherits the defaults
    (``agent_id``, ``model_id``, etc.) so you don't have to repeat them.
    ``notarize()`` passes through to the underlying client unchanged since
    it only takes an ``action_id``.
    """

    def __init__(self, client: Aira, agent_id: str, **defaults: Any) -> None:
        self._client = client
        self._defaults = {"agent_id": agent_id, **defaults}

    def authorize(self, action_type: str, details: str, **kwargs: Any) -> Authorization:
        merged = {**self._defaults, **kwargs}
        return self._client.authorize(action_type=action_type, details=details, **merged)

    def notarize(
        self,
        action_id: str,
        outcome: str = "completed",
        outcome_details: str | None = None,
    ) -> ActionReceipt:
        return self._client.notarize(
            action_id=action_id, outcome=outcome, outcome_details=outcome_details
        )

    def __enter__(self) -> AiraSession:
        return self

    def __exit__(self, *args: Any) -> None:
        pass


class AsyncAira:
    """Asynchronous Aira client — mirrors Aira sync client exactly."""

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        offline: bool = False,
    ) -> None:
        _validate_api_key(api_key)
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            base_url=f"{self.base_url}/api/v1",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=timeout,
        )
        self._public_client = httpx.AsyncClient(
            base_url=f"{self.base_url}/api/v1",
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )
        self._queue: OfflineQueue | None = OfflineQueue() if offline else None

    async def close(self) -> None:
        await self._client.aclose()
        await self._public_client.aclose()

    async def __aenter__(self) -> AsyncAira:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

    async def _post(self, path: str, body: dict) -> dict:
        if self._queue is not None:
            qid = self._queue.enqueue("POST", path, body)
            return {"_offline": True, "_queue_id": qid}
        return _handle_response(await self._client.post(path, json=body))

    async def _get(self, path: str, params: dict | None = None) -> dict:
        if self._queue is not None:
            raise AiraError(0, "OFFLINE", "GET requests not available in offline mode")
        return _handle_response(await self._client.get(path, params=params))

    async def _put(self, path: str, body: dict) -> dict:
        if self._queue is not None:
            qid = self._queue.enqueue("PUT", path, body)
            return {"_offline": True, "_queue_id": qid}
        return _handle_response(await self._client.put(path, json=body))

    async def _delete(self, path: str) -> dict:
        if self._queue is not None:
            qid = self._queue.enqueue("DELETE", path, {})
            return {"_offline": True, "_queue_id": qid}
        return _handle_response(await self._client.delete(path))

    # ==================== Actions ====================

    async def authorize(
        self,
        action_type: str,
        details: str,
        agent_id: str | None = None,
        agent_version: str | None = None,
        instruction_hash: str | None = None,
        model_id: str | None = None,
        model_version: str | None = None,
        parent_action_id: str | None = None,
        endpoint_url: str | None = None,
        store_details: bool = False,
        idempotency_key: str | None = None,
        require_approval: bool = False,
        approvers: list[str] | None = None,
    ) -> Authorization:
        """Step 1 of 2: ask Aira for permission to perform an action.

        See :meth:`Aira.authorize` for the full contract.
        """
        body = _build_body(
            action_type=action_type,
            details=_truncate_details(details),
            agent_id=agent_id,
            agent_version=agent_version,
            instruction_hash=instruction_hash,
            model_id=model_id,
            model_version=model_version,
            parent_action_id=parent_action_id,
            endpoint_url=endpoint_url,
            idempotency_key=idempotency_key,
            require_approval=require_approval or None,
            approvers=approvers,
        )
        if store_details:
            body["store_details"] = True
        return _to_dataclass(Authorization, await self._post("/actions", body))

    async def notarize(
        self,
        action_id: str,
        outcome: str = "completed",
        outcome_details: str | None = None,
    ) -> ActionReceipt:
        """Step 2 of 2: report what actually happened for an authorized action.

        See :meth:`Aira.notarize` for the full contract.
        """
        body = _build_body(outcome=outcome, outcome_details=outcome_details)
        return _to_dataclass(
            ActionReceipt, await self._post(f"/actions/{action_id}/notarize", body)
        )

    async def get_action(self, action_id: str) -> ActionDetail:
        return _to_dataclass(ActionDetail, await self._get(f"/actions/{action_id}"))

    async def list_actions(
        self, page: int = 1, per_page: int = 20,
        action_type: str | None = None, agent_id: str | None = None, status: str | None = None,
    ) -> PaginatedList:
        """List actions with filters."""
        params = _build_body(page=page, per_page=per_page, action_type=action_type, agent_id=agent_id, status=status)
        return _paginated(await self._get("/actions", params))

    async def cosign_action(self, action_id: str) -> CosignResult:
        """Human co-signature on an authorized or notarized action."""
        return _to_dataclass(
            CosignResult, await self._post(f"/actions/{action_id}/cosign", {})
        )

    async def set_legal_hold(self, action_id: str) -> dict:
        return await self._post(f"/actions/{action_id}/hold", {})

    async def release_legal_hold(self, action_id: str) -> dict:
        return await self._delete(f"/actions/{action_id}/hold")

    async def get_action_chain(self, action_id: str) -> list[dict]:
        return (await self._get(f"/actions/{action_id}/chain")).get("chain", [])

    async def verify_action(self, action_id: str) -> VerifyResult:
        data = _handle_response(await self._public_client.get(f"/verify/action/{action_id}"))
        return _to_dataclass(VerifyResult, data)

    # ==================== Agents ====================

    async def register_agent(
        self,
        agent_slug: str,
        display_name: str,
        description: str | None = None,
        capabilities: list[str] | None = None,
        public: bool = False,
    ) -> AgentDetail:
        """Register a new agent identity."""
        body = _build_body(
            agent_slug=agent_slug, display_name=display_name,
            description=description, capabilities=capabilities, public=public,
        )
        return _to_dataclass(AgentDetail, await self._post("/agents", body))

    async def get_agent(self, slug: str) -> AgentDetail:
        return _to_dataclass(AgentDetail, await self._get(f"/agents/{slug}"))

    async def list_agents(self, page: int = 1, status: str | None = None) -> PaginatedList:
        return _paginated(await self._get("/agents", _build_body(page=page, status=status)))

    async def update_agent(self, slug: str, **fields: Any) -> AgentDetail:
        return _to_dataclass(AgentDetail, await self._put(f"/agents/{slug}", _build_body(**fields)))

    async def publish_version(
        self, slug: str, version: str, changelog: str | None = None,
        model_id: str | None = None, instruction_hash: str | None = None, config_hash: str | None = None,
    ) -> AgentVersion:
        body = _build_body(version=version, changelog=changelog, model_id=model_id, instruction_hash=instruction_hash, config_hash=config_hash)
        return _to_dataclass(AgentVersion, await self._post(f"/agents/{slug}/versions", body))

    async def list_versions(self, slug: str) -> list[AgentVersion]:
        data = await self._get(f"/agents/{slug}/versions")
        return [_to_dataclass(AgentVersion, v) for v in data] if isinstance(data, list) else []

    async def decommission_agent(self, slug: str) -> AgentDetail:
        return _to_dataclass(AgentDetail, await self._post(f"/agents/{slug}/decommission", {}))

    async def transfer_agent(self, slug: str, to_org_id: str, reason: str | None = None) -> dict:
        return await self._post(f"/agents/{slug}/transfer", _build_body(to_org_id=to_org_id, reason=reason))

    async def get_agent_actions(self, slug: str, page: int = 1) -> PaginatedList:
        return _paginated(await self._get(f"/agents/{slug}/actions", {"page": page}))

    # ==================== Cases ====================

    async def run_case(self, details: str, models: list[str], **options: Any) -> dict:
        body: dict[str, Any] = {"details": details, "models": models}
        if options:
            body["options"] = options
        return await self._post("/cases", body)

    async def get_case(self, case_id: str) -> dict:
        return await self._get(f"/cases/{case_id}")

    async def list_cases(self, page: int = 1) -> PaginatedList:
        return _paginated(await self._get("/cases", {"page": page}))

    # ==================== Receipts ====================

    async def get_receipt(self, receipt_id: str) -> dict:
        return await self._get(f"/receipts/{receipt_id}")

    async def export_receipt(self, receipt_id: str, format: str = "json") -> dict:
        return await self._get(f"/receipts/{receipt_id}/export", {"format": format})

    # ==================== Evidence ====================

    async def create_evidence_package(
        self, title: str, action_ids: list[str], description: str | None = None,
        agent_slugs: list[str] | None = None,
    ) -> EvidencePackage:
        body = _build_body(title=title, action_ids=action_ids, description=description, agent_slugs=agent_slugs)
        return _to_dataclass(EvidencePackage, await self._post("/evidence/packages", body))

    async def list_evidence_packages(self, page: int = 1) -> PaginatedList:
        return _paginated(await self._get("/evidence/packages", {"page": page}))

    async def get_evidence_package(self, package_id: str) -> EvidencePackage:
        return _to_dataclass(EvidencePackage, await self._get(f"/evidence/packages/{package_id}"))

    async def time_travel(self, point_in_time: str, agent_slug: str | None = None, action_type: str | None = None) -> dict:
        """Query actions as they existed at a point in time."""
        return await self._post("/evidence/time-travel", _build_body(point_in_time=point_in_time, agent_slug=agent_slug, action_type=action_type))

    async def liability_chain(self, action_id: str, max_depth: int = 10) -> list[dict]:
        data = await self._get(f"/evidence/liability-chain/{action_id}", {"max_depth": max_depth})
        return data.get("chain", [])

    # ==================== Estate ====================

    async def set_agent_will(
        self, slug: str, successor_slug: str | None = None,
        succession_policy: str = "transfer_to_successor",
        data_retention_days: int | None = None,
        notify_emails: list[str] | None = None,
        instructions: str | None = None,
    ) -> dict:
        body = _build_body(
            successor_slug=successor_slug, succession_policy=succession_policy,
            data_retention_days=data_retention_days, notify_emails=notify_emails, instructions=instructions,
        )
        return await self._put(f"/estate/agents/{slug}/will", body)

    async def get_agent_will(self, slug: str) -> dict:
        return await self._get(f"/estate/agents/{slug}/will")

    async def issue_death_certificate(self, slug: str, reason: str = "Decommissioned by organization") -> dict:
        return await self._post(f"/estate/agents/{slug}/death-certificate", {"reason": reason})

    async def get_death_certificate(self, slug: str) -> dict:
        return await self._get(f"/estate/agents/{slug}/death-certificate")

    async def create_compliance_snapshot(
        self, framework: str, agent_slug: str | None = None, findings: dict | None = None,
    ) -> ComplianceSnapshot:
        body = _build_body(framework=framework, agent_slug=agent_slug, findings=findings)
        return _to_dataclass(ComplianceSnapshot, await self._post("/estate/compliance", body))

    async def list_compliance_snapshots(self, page: int = 1, framework: str | None = None) -> PaginatedList:
        return _paginated(await self._get("/estate/compliance", _build_body(page=page, framework=framework)))

    # ==================== Escrow ====================

    async def create_escrow_account(
        self, purpose: str | None = None, currency: str = "EUR",
        agent_id: str | None = None, counterparty_org_id: str | None = None,
    ) -> EscrowAccount:
        body = _build_body(purpose=purpose, currency=currency, agent_id=agent_id, counterparty_org_id=counterparty_org_id)
        return _to_dataclass(EscrowAccount, await self._post("/escrow/accounts", body))

    async def list_escrow_accounts(self, page: int = 1) -> PaginatedList:
        return _paginated(await self._get("/escrow/accounts", {"page": page}))

    async def get_escrow_account(self, account_id: str) -> EscrowAccount:
        return _to_dataclass(EscrowAccount, await self._get(f"/escrow/accounts/{account_id}"))

    async def escrow_deposit(self, account_id: str, amount: float, description: str | None = None, reference_action_id: str | None = None) -> EscrowTransaction:
        body = _build_body(amount=amount, description=description, reference_action_id=reference_action_id)
        return _to_dataclass(EscrowTransaction, await self._post(f"/escrow/accounts/{account_id}/deposit", body))

    async def escrow_release(self, account_id: str, amount: float, description: str | None = None, reference_action_id: str | None = None) -> EscrowTransaction:
        body = _build_body(amount=amount, description=description, reference_action_id=reference_action_id)
        return _to_dataclass(EscrowTransaction, await self._post(f"/escrow/accounts/{account_id}/release", body))

    async def escrow_dispute(self, account_id: str, amount: float, description: str, reference_action_id: str | None = None) -> EscrowTransaction:
        body = _build_body(amount=amount, description=description, reference_action_id=reference_action_id)
        return _to_dataclass(EscrowTransaction, await self._post(f"/escrow/accounts/{account_id}/dispute", body))

    # ==================== Chat ====================

    async def ask(self, message: str, history: list[dict] | None = None, model: str | None = None) -> dict:
        return await self._post("/chat", _build_body(message=message, history=history, model_id=model))

    # ==================== DID ====================

    async def get_agent_did(self, slug: str) -> dict:
        """Get full DID info for an agent."""
        return await self._get(f"/agents/{slug}/did")

    async def rotate_agent_keys(self, slug: str) -> dict:
        """Rotate an agent's DID keypair."""
        return await self._post(f"/agents/{slug}/did/rotate", {})

    async def resolve_did(self, did: str) -> dict:
        """Resolve any did:web DID to its DID document."""
        return await self._post("/dids/resolve", {"did": did})

    # ==================== Verifiable Credentials ====================

    async def get_agent_credential(self, slug: str) -> dict:
        """Get the current valid VC for an agent."""
        return await self._get(f"/agents/{slug}/credential")

    async def get_agent_credentials(self, slug: str) -> dict:
        """Get full credential history for an agent."""
        return await self._get(f"/agents/{slug}/credentials")

    async def revoke_credential(self, slug: str, reason: str = "") -> dict:
        """Revoke the current credential for an agent."""
        return await self._post(f"/agents/{slug}/credentials/revoke", {"reason": reason})

    async def verify_credential(self, credential: dict) -> dict:
        """Verify a Verifiable Credential — checks signature, expiry, revocation."""
        return await self._post("/credentials/verify", {"credential": credential})

    # ==================== Mutual Notarization ====================

    async def request_mutual_sign(self, action_id: str, counterparty_did: str) -> dict:
        """Initiate a mutual signing request for an action."""
        return await self._post(f"/actions/{action_id}/mutual-sign/request", {"counterparty_did": counterparty_did})

    async def get_pending_mutual_sign(self, action_id: str) -> dict:
        """Get the action payload awaiting counterparty signature."""
        return await self._get(f"/actions/{action_id}/mutual-sign/pending")

    async def complete_mutual_sign(self, action_id: str, did: str, signature: str, signed_payload_hash: str) -> dict:
        """Submit counterparty signature to complete mutual signing."""
        return await self._post(f"/actions/{action_id}/mutual-sign/complete", {"did": did, "signature": signature, "signed_payload_hash": signed_payload_hash})

    async def get_mutual_sign_receipt(self, action_id: str) -> dict:
        """Get the co-signed receipt for a mutually signed action."""
        return await self._get(f"/actions/{action_id}/mutual-sign/receipt")

    async def reject_mutual_sign(self, action_id: str, reason: str = "") -> dict:
        """Reject a mutual signing request."""
        return await self._post(f"/actions/{action_id}/mutual-sign/reject", {"reason": reason})

    # ==================== Reputation ====================

    async def get_reputation(self, slug: str) -> dict:
        """Get current reputation score for an agent."""
        return await self._get(f"/agents/{slug}/reputation")

    async def get_reputation_history(self, slug: str) -> dict:
        """Get full reputation history for an agent."""
        return await self._get(f"/agents/{slug}/reputation/history")

    async def attest_reputation(self, slug: str, counterparty_did: str, action_id: str, attestation: str, signature: str) -> dict:
        """Submit a signed attestation of a successful interaction."""
        return await self._post(f"/agents/{slug}/reputation/attest", {"counterparty_did": counterparty_did, "action_id": action_id, "attestation": attestation, "signature": signature})

    async def verify_reputation(self, slug: str) -> dict:
        """Verify a reputation score by returning inputs and score_hash."""
        return await self._get(f"/agents/{slug}/reputation/verify")

    # ==================== Offline sync ====================

    @property
    def pending_count(self) -> int:
        """Number of requests queued for sync. Returns 0 if not in offline mode."""
        return self._queue.pending_count if self._queue else 0

    async def sync(self) -> list:
        """Flush offline queue to API. Returns list of API responses."""
        if self._queue is None:
            raise ValueError("sync() is only available in offline mode")
        items = self._queue.drain()
        results = []
        for item in items:
            resp = await self._client.request(item.method, item.path, json=item.body)
            if resp.status_code >= 400:
                results.append({"_error": True, "_status": resp.status_code, "_queue_id": item.id})
            else:
                results.append(resp.json())
        return results

    # ==================== Session ====================

    def session(self, agent_id: str, **defaults: Any) -> AsyncAiraSession:
        """Create a scoped async session with pre-filled defaults for authorize()."""
        return AsyncAiraSession(self, agent_id=agent_id, **defaults)


class AsyncAiraSession:
    """Scoped async session with pre-filled defaults for :meth:`AsyncAira.authorize`."""

    def __init__(self, client: AsyncAira, agent_id: str, **defaults: Any) -> None:
        self._client = client
        self._defaults = {"agent_id": agent_id, **defaults}

    async def authorize(self, action_type: str, details: str, **kwargs: Any) -> Authorization:
        merged = {**self._defaults, **kwargs}
        return await self._client.authorize(
            action_type=action_type, details=details, **merged
        )

    async def notarize(
        self,
        action_id: str,
        outcome: str = "completed",
        outcome_details: str | None = None,
    ) -> ActionReceipt:
        return await self._client.notarize(
            action_id=action_id, outcome=outcome, outcome_details=outcome_details
        )

    async def __aenter__(self) -> AsyncAiraSession:
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass
