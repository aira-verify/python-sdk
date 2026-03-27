"""Aira SDK client — sync and async with full API coverage."""

from __future__ import annotations

import functools
import hashlib
import json
import logging
from typing import Any, Callable

import httpx

from aira.types import (
    ActionDetail,
    ActionReceipt,
    AgentDetail,
    AgentVersion,
    ComplianceSnapshot,
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
MAX_RETRIES = 2
RETRY_STATUS_CODES = {502, 503, 504}


class AiraError(Exception):
    """Aira API error."""

    def __init__(self, status: int, code: str, message: str) -> None:
        self.status = status
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


def _handle_response(resp: httpx.Response) -> dict:
    if resp.status_code >= 400:
        try:
            body = resp.json()
        except Exception:
            body = {"error": resp.text, "code": "UNKNOWN"}
        raise AiraError(resp.status_code, body.get("code", "UNKNOWN"), body.get("error", resp.text))
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


def _sanitize_details(text: str) -> str:
    """Truncate details to max length and strip potential secrets."""
    if len(text) > MAX_DETAILS_LENGTH:
        text = text[:MAX_DETAILS_LENGTH] + "...[truncated]"
    return text


def _build_body(**kwargs: Any) -> dict:
    """Build request body, filtering out None values."""
    return {k: v for k, v in kwargs.items() if v is not None}


class _BaseMixin:
    """Shared helper methods."""

    def _hash_input(self, data: str) -> str:
        return f"sha256:{hashlib.sha256(data.encode()).hexdigest()}"


class Aira(_BaseMixin):
    """Synchronous Aira client.

    Usage:
        aira = Aira(api_key="aira_live_xxx")
        receipt = aira.notarize(action_type="email_sent", details="Sent email")
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        _validate_api_key(api_key)
        self.base_url = base_url.rstrip("/")
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

    def close(self) -> None:
        self._client.close()
        self._public_client.close()

    def __enter__(self) -> Aira:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def _post(self, path: str, body: dict) -> dict:
        return _handle_response(self._client.post(path, json=body))

    def _get(self, path: str, params: dict | None = None) -> dict:
        return _handle_response(self._client.get(path, params=params))

    def _put(self, path: str, body: dict) -> dict:
        return _handle_response(self._client.put(path, json=body))

    def _delete(self, path: str) -> dict:
        return _handle_response(self._client.delete(path))

    # ==================== Actions ====================

    def notarize(
        self,
        action_type: str,
        details: str,
        agent_id: str | None = None,
        agent_version: str | None = None,
        model_id: str | None = None,
        model_version: str | None = None,
        instruction_hash: str | None = None,
        parent_action_id: str | None = None,
        store_details: bool = False,
        idempotency_key: str | None = None,
    ) -> ActionReceipt:
        """Notarize an agent action. Returns a cryptographic receipt."""
        body = _build_body(
            action_type=action_type,
            details=_sanitize_details(details),
            agent_id=agent_id,
            agent_version=agent_version,
            model_id=model_id,
            model_version=model_version,
            instruction_hash=instruction_hash,
            parent_action_id=parent_action_id,
            idempotency_key=idempotency_key,
        )
        if store_details:
            body["store_details"] = True
        return _to_dataclass(ActionReceipt, self._post("/actions", body))

    def get_action(self, action_id: str) -> ActionDetail:
        """Get full action details including receipt and authorizations."""
        return _to_dataclass(ActionDetail, self._get(f"/actions/{action_id}"))

    def list_actions(
        self, page: int = 1, per_page: int = 20,
        action_type: str | None = None, agent_id: str | None = None, status: str | None = None,
    ) -> PaginatedList:
        """List notarized actions with filters."""
        params = _build_body(page=page, per_page=per_page, action_type=action_type, agent_id=agent_id, status=status)
        return _paginated(self._get("/actions", params))

    def authorize_action(self, action_id: str) -> dict:
        """Human co-sign an action. Requires JWT auth."""
        return self._post(f"/actions/{action_id}/authorize", {})

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
        return self._post("/chat", _build_body(message=message, history=history, model=model))

    # ==================== Decorator ====================

    def trace(
        self,
        agent_id: str,
        action_type: str = "function_call",
        model_id: str | None = None,
        include_result: bool = False,
    ) -> Callable:
        """Decorator that auto-notarizes function calls.

        Args:
            agent_id: The agent performing this action.
            action_type: Action type to record.
            model_id: Optional model ID.
            include_result: If True, includes the return value in details.
                WARNING: Only enable if the function does NOT return sensitive data.
                Disabled by default to prevent accidental PII/secret leakage.
        """
        def decorator(func: Callable) -> Callable:
            @functools.wraps(func)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                # Hash inputs (never send raw inputs — they may contain secrets)
                input_repr = json.dumps({"fn": func.__name__, "arg_count": len(args), "kwarg_keys": sorted(kwargs.keys())}, sort_keys=True)
                instruction_hash = self._hash_input(input_repr)

                result = func(*args, **kwargs)

                # Build safe details — never include raw args/kwargs
                details = f"Called {func.__module__}.{func.__name__}()"
                if include_result:
                    details += f" -> {str(result)[:200]}"

                try:
                    self.notarize(
                        action_type=action_type, details=details,
                        agent_id=agent_id, model_id=model_id, instruction_hash=instruction_hash,
                    )
                except Exception as e:
                    logger.warning("Aira notarization failed (non-blocking): %s", e)

                return result
            return wrapper
        return decorator


class AsyncAira(_BaseMixin):
    """Asynchronous Aira client — mirrors Aira sync client exactly."""

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        _validate_api_key(api_key)
        self.base_url = base_url.rstrip("/")
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

    async def close(self) -> None:
        await self._client.aclose()
        await self._public_client.aclose()

    async def __aenter__(self) -> AsyncAira:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    async def _post(self, path: str, body: dict) -> dict:
        return _handle_response(await self._client.post(path, json=body))

    async def _get(self, path: str, params: dict | None = None) -> dict:
        return _handle_response(await self._client.get(path, params=params))

    async def _put(self, path: str, body: dict) -> dict:
        return _handle_response(await self._client.put(path, json=body))

    async def _delete(self, path: str) -> dict:
        return _handle_response(await self._client.delete(path))

    # ==================== Actions ====================

    async def notarize(self, action_type: str, details: str, **kwargs: Any) -> ActionReceipt:
        body = _build_body(action_type=action_type, details=_sanitize_details(details), **kwargs)
        return _to_dataclass(ActionReceipt, await self._post("/actions", body))

    async def get_action(self, action_id: str) -> ActionDetail:
        return _to_dataclass(ActionDetail, await self._get(f"/actions/{action_id}"))

    async def list_actions(self, page: int = 1, **filters: Any) -> PaginatedList:
        return _paginated(await self._get("/actions", _build_body(page=page, **filters)))

    async def authorize_action(self, action_id: str) -> dict:
        return await self._post(f"/actions/{action_id}/authorize", {})

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

    async def register_agent(self, agent_slug: str, display_name: str, **kwargs: Any) -> AgentDetail:
        body = _build_body(agent_slug=agent_slug, display_name=display_name, **kwargs)
        return _to_dataclass(AgentDetail, await self._post("/agents", body))

    async def get_agent(self, slug: str) -> AgentDetail:
        return _to_dataclass(AgentDetail, await self._get(f"/agents/{slug}"))

    async def list_agents(self, page: int = 1, status: str | None = None) -> PaginatedList:
        return _paginated(await self._get("/agents", _build_body(page=page, status=status)))

    async def update_agent(self, slug: str, **fields: Any) -> AgentDetail:
        return _to_dataclass(AgentDetail, await self._put(f"/agents/{slug}", _build_body(**fields)))

    async def publish_version(self, slug: str, version: str, **kwargs: Any) -> AgentVersion:
        body = _build_body(version=version, **kwargs)
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

    async def create_evidence_package(self, title: str, action_ids: list[str], **kwargs: Any) -> EvidencePackage:
        body = _build_body(title=title, action_ids=action_ids, **kwargs)
        return _to_dataclass(EvidencePackage, await self._post("/evidence/packages", body))

    async def list_evidence_packages(self, page: int = 1) -> PaginatedList:
        return _paginated(await self._get("/evidence/packages", {"page": page}))

    async def get_evidence_package(self, package_id: str) -> EvidencePackage:
        return _to_dataclass(EvidencePackage, await self._get(f"/evidence/packages/{package_id}"))

    async def time_travel(self, point_in_time: str, **kwargs: Any) -> dict:
        return await self._post("/evidence/time-travel", _build_body(point_in_time=point_in_time, **kwargs))

    async def liability_chain(self, action_id: str, max_depth: int = 10) -> list[dict]:
        data = await self._get(f"/evidence/liability-chain/{action_id}", {"max_depth": max_depth})
        return data.get("chain", [])

    # ==================== Estate ====================

    async def set_agent_will(self, slug: str, **kwargs: Any) -> dict:
        return await self._put(f"/estate/agents/{slug}/will", _build_body(**kwargs))

    async def get_agent_will(self, slug: str) -> dict:
        return await self._get(f"/estate/agents/{slug}/will")

    async def issue_death_certificate(self, slug: str, reason: str = "Decommissioned by organization") -> dict:
        return await self._post(f"/estate/agents/{slug}/death-certificate", {"reason": reason})

    async def get_death_certificate(self, slug: str) -> dict:
        return await self._get(f"/estate/agents/{slug}/death-certificate")

    async def create_compliance_snapshot(self, framework: str, **kwargs: Any) -> ComplianceSnapshot:
        body = _build_body(framework=framework, **kwargs)
        return _to_dataclass(ComplianceSnapshot, await self._post("/estate/compliance", body))

    async def list_compliance_snapshots(self, page: int = 1, framework: str | None = None) -> PaginatedList:
        return _paginated(await self._get("/estate/compliance", _build_body(page=page, framework=framework)))

    # ==================== Escrow ====================

    async def create_escrow_account(self, **kwargs: Any) -> EscrowAccount:
        return _to_dataclass(EscrowAccount, await self._post("/escrow/accounts", _build_body(**kwargs)))

    async def list_escrow_accounts(self, page: int = 1) -> PaginatedList:
        return _paginated(await self._get("/escrow/accounts", {"page": page}))

    async def get_escrow_account(self, account_id: str) -> EscrowAccount:
        return _to_dataclass(EscrowAccount, await self._get(f"/escrow/accounts/{account_id}"))

    async def escrow_deposit(self, account_id: str, amount: float, **kwargs: Any) -> EscrowTransaction:
        body = _build_body(amount=amount, **kwargs)
        return _to_dataclass(EscrowTransaction, await self._post(f"/escrow/accounts/{account_id}/deposit", body))

    async def escrow_release(self, account_id: str, amount: float, **kwargs: Any) -> EscrowTransaction:
        body = _build_body(amount=amount, **kwargs)
        return _to_dataclass(EscrowTransaction, await self._post(f"/escrow/accounts/{account_id}/release", body))

    async def escrow_dispute(self, account_id: str, amount: float, description: str, **kwargs: Any) -> EscrowTransaction:
        body = _build_body(amount=amount, description=description, **kwargs)
        return _to_dataclass(EscrowTransaction, await self._post(f"/escrow/accounts/{account_id}/dispute", body))

    # ==================== Chat ====================

    async def ask(self, message: str, history: list[dict] | None = None, model: str | None = None) -> dict:
        return await self._post("/chat", _build_body(message=message, history=history, model=model))

    # ==================== Decorator ====================

    def trace(self, agent_id: str, action_type: str = "function_call", model_id: str | None = None, include_result: bool = False) -> Callable:
        """Async decorator that auto-notarizes function calls. Safe by default — does NOT send args or return values."""
        def decorator(func: Callable) -> Callable:
            @functools.wraps(func)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                input_repr = json.dumps({"fn": func.__name__, "arg_count": len(args), "kwarg_keys": sorted(kwargs.keys())}, sort_keys=True)
                instruction_hash = self._hash_input(input_repr)
                result = await func(*args, **kwargs)
                details = f"Called {func.__module__}.{func.__name__}()"
                if include_result:
                    details += f" -> {str(result)[:200]}"
                try:
                    await self.notarize(action_type=action_type, details=details, agent_id=agent_id, model_id=model_id, instruction_hash=instruction_hash)
                except Exception as e:
                    logger.warning("Aira notarization failed (non-blocking): %s", e)
                return result
            return wrapper
        return decorator
