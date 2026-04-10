"""Comprehensive tests for Aira SDK — two-step authorize + notarize flow."""

from unittest.mock import patch

import httpx
import pytest

from aira import (
    Aira,
    AsyncAira,
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
)
from aira.client import AiraError, _truncate_details, _validate_api_key, MAX_DETAILS_LENGTH


# --- Helpers ---

def _resp(data, status: int = 200) -> httpx.Response:
    return httpx.Response(status_code=status, json=data, request=httpx.Request("GET", "http://test"))


def _paginated_resp(items: list, total: int | None = None) -> httpx.Response:
    t = total if total is not None else len(items)
    return _resp({"data": items, "pagination": {"page": 1, "per_page": 20, "total": t, "has_more": False}})


AUTH_OK = {
    "action_id": "act-1",
    "status": "authorized",
    "created_at": "2026-04-10T00:00:00Z",
    "request_id": "req-1",
    "warnings": None,
}

AUTH_PENDING = {
    "action_id": "act-1",
    "status": "pending_approval",
    "created_at": "2026-04-10T00:00:00Z",
    "request_id": "req-1",
    "warnings": None,
}

RECEIPT_COMPLETED = {
    "action_id": "act-1",
    "status": "notarized",
    "receipt_id": "rct-1",
    "payload_hash": "sha256:abc",
    "signature": "ed25519:xyz",
    "timestamp_token": "ts",
    "created_at": "2026-04-10T00:00:01Z",
    "request_id": "req-2",
    "warnings": None,
}

RECEIPT_FAILED = {
    "action_id": "act-1",
    "status": "failed",
    "receipt_id": None,
    "payload_hash": None,
    "signature": None,
    "timestamp_token": None,
    "created_at": "2026-04-10T00:00:01Z",
    "request_id": "req-2",
    "warnings": None,
}

ACTION = {
    "action_id": "act-1",
    "org_id": "org-1",
    "action_type": "email_sent",
    "status": "notarized",
    "legal_hold": False,
    "action_details_hash": "sha256:abc",
    "created_at": "2026-04-10T00:00:00Z",
    "request_id": "req-1",
}

AGENT = {
    "id": "ag-1",
    "agent_slug": "my-agent",
    "display_name": "My Agent",
    "status": "active",
    "public": True,
    "registered_at": "2026-04-10T00:00:00Z",
    "request_id": "req-1",
}
VERSION = {"id": "v-1", "version": "1.0.0", "status": "active", "created_at": "2026-04-10T00:00:00Z"}
EVIDENCE = {
    "id": "pkg-1", "title": "Test", "action_ids": ["act-1"], "package_hash": "sha256:p",
    "signature": "ed25519:p", "status": "sealed", "created_at": "2026-04-10T00:00:00Z", "request_id": "req-1",
}
SNAPSHOT = {
    "id": "s-1", "framework": "eu-ai-act", "status": "compliant", "findings": {},
    "snapshot_hash": "sha256:s", "signature": "ed25519:s", "snapshot_at": "2026-04-10T00:00:00Z",
    "created_at": "2026-04-10T00:00:00Z", "request_id": "req-1",
}
ESCROW_ACC = {"id": "esc-1", "currency": "EUR", "balance": "5000.00", "status": "active", "created_at": "2026-04-10T00:00:00Z", "request_id": "req-1"}
ESCROW_TX = {"id": "tx-1", "transaction_type": "deposit", "amount": "5000.00", "currency": "EUR", "transaction_hash": "sha256:tx", "signature": "ed25519:tx", "status": "completed", "created_at": "2026-04-10T00:00:00Z"}


class TestValidation:
    def test_empty_api_key_raises(self):
        with pytest.raises(ValueError, match="api_key is required"):
            Aira(api_key="")

    def test_sanitize_truncates(self):
        assert _truncate_details("x" * (MAX_DETAILS_LENGTH + 100)).endswith("...[truncated]")

    def test_sanitize_normal(self):
        assert _truncate_details("hello") == "hello"


# ==================== Authorize (step 1) ====================

class TestAuthorize:
    def setup_method(self):
        self.c = Aira(api_key="aira_live_test", base_url="http://test")

    def teardown_method(self):
        self.c.close()

    def test_authorize_returns_authorization(self):
        with patch.object(self.c._client, "post", return_value=_resp(AUTH_OK, 201)):
            a = self.c.authorize(action_type="wire_transfer", details="Send EUR 75K")
        assert isinstance(a, Authorization)
        assert a.action_id == "act-1"
        assert a.status == "authorized"

    def test_authorize_posts_to_actions_endpoint(self):
        with patch.object(self.c._client, "post", return_value=_resp(AUTH_OK, 201)) as m:
            self.c.authorize(action_type="wire_transfer", details="Send EUR 75K")
            assert m.call_args[0][0] == "/actions"

    def test_authorize_sends_all_params(self):
        with patch.object(self.c._client, "post", return_value=_resp(AUTH_OK, 201)) as m:
            self.c.authorize(
                action_type="wire_transfer",
                details="Send EUR 75K",
                agent_id="payments",
                agent_version="1.0",
                instruction_hash="sha256:h",
                model_id="claude-sonnet-4-6",
                model_version="20250514",
                parent_action_id="parent-1",
                endpoint_url="https://api.stripe.com/v1/charges",
                store_details=True,
                idempotency_key="idem-1",
            )
            b = m.call_args[1]["json"]
            assert b["action_type"] == "wire_transfer"
            assert b["agent_id"] == "payments"
            assert b["agent_version"] == "1.0"
            assert b["instruction_hash"] == "sha256:h"
            assert b["model_id"] == "claude-sonnet-4-6"
            assert b["model_version"] == "20250514"
            assert b["parent_action_id"] == "parent-1"
            assert b["endpoint_url"] == "https://api.stripe.com/v1/charges"
            assert b["store_details"] is True
            assert b["idempotency_key"] == "idem-1"

    def test_authorize_pending_approval_branch(self):
        with patch.object(self.c._client, "post", return_value=_resp(AUTH_PENDING, 201)):
            a = self.c.authorize(
                action_type="loan_decision",
                details="Approve EUR 50K loan",
                require_approval=True,
                approvers=["mgr@example.com"],
            )
        assert a.status == "pending_approval"
        assert a.action_id == "act-1"

    def test_authorize_policy_denied_raises_with_details(self):
        err_body = {
            "code": "POLICY_DENIED",
            "message": "Action denied by policy 'Block wire transfers'",
            "details": {"action_id": "act-1", "policy_id": "pol-1"},
        }
        with patch.object(self.c._client, "post", return_value=_resp(err_body, 403)):
            with pytest.raises(AiraError) as ei:
                self.c.authorize(action_type="wire_transfer", details="Send EUR 75K")
        assert ei.value.code == "POLICY_DENIED"
        assert ei.value.status_code == 403
        assert ei.value.details == {"action_id": "act-1", "policy_id": "pol-1"}
        assert ei.value.message.startswith("Action denied by policy")

    def test_authorize_endpoint_not_whitelisted_raises(self):
        err_body = {
            "code": "ENDPOINT_NOT_WHITELISTED",
            "message": "Endpoint not whitelisted",
            "details": {"approval_id": "req-1"},
        }
        with patch.object(self.c._client, "post", return_value=_resp(err_body, 403)):
            with pytest.raises(AiraError) as ei:
                self.c.authorize(
                    action_type="api_call",
                    details="POST /charges",
                    endpoint_url="https://api.new-provider.com",
                )
        assert ei.value.code == "ENDPOINT_NOT_WHITELISTED"

    def test_authorize_duplicate_request(self):
        err_body = {"code": "DUPLICATE_REQUEST", "message": "idempotency key already used"}
        with patch.object(self.c._client, "post", return_value=_resp(err_body, 409)):
            with pytest.raises(AiraError) as ei:
                self.c.authorize(
                    action_type="wire_transfer",
                    details="Send EUR 75K",
                    idempotency_key="dup",
                )
        assert ei.value.status_code == 409
        assert ei.value.code == "DUPLICATE_REQUEST"

    def test_authorize_sends_require_approval_when_true(self):
        with patch.object(self.c._client, "post", return_value=_resp(AUTH_PENDING, 201)) as m:
            self.c.authorize(
                action_type="loan_decision",
                details="x",
                require_approval=True,
                approvers=["a@b.com"],
            )
            b = m.call_args[1]["json"]
            assert b["require_approval"] is True
            assert b["approvers"] == ["a@b.com"]

    def test_authorize_omits_require_approval_when_false(self):
        with patch.object(self.c._client, "post", return_value=_resp(AUTH_OK, 201)) as m:
            self.c.authorize(action_type="test", details="x")
            b = m.call_args[1]["json"]
            assert "require_approval" not in b
            assert "approvers" not in b


# ==================== Notarize (step 2) ====================

class TestNotarize:
    def setup_method(self):
        self.c = Aira(api_key="aira_live_test", base_url="http://test")

    def teardown_method(self):
        self.c.close()

    def test_notarize_completed_mints_receipt(self):
        with patch.object(self.c._client, "post", return_value=_resp(RECEIPT_COMPLETED, 200)):
            r = self.c.notarize(
                action_id="act-1",
                outcome="completed",
                outcome_details="Sent, ref TX12345",
            )
        assert isinstance(r, ActionReceipt)
        assert r.status == "notarized"
        assert r.receipt_id == "rct-1"
        assert r.payload_hash == "sha256:abc"
        assert r.signature == "ed25519:xyz"

    def test_notarize_posts_to_action_notarize_endpoint(self):
        with patch.object(self.c._client, "post", return_value=_resp(RECEIPT_COMPLETED, 200)) as m:
            self.c.notarize(action_id="act-1")
            assert m.call_args[0][0] == "/actions/act-1/notarize"
            b = m.call_args[1]["json"]
            assert b["outcome"] == "completed"

    def test_notarize_failed_no_receipt_minted(self):
        with patch.object(self.c._client, "post", return_value=_resp(RECEIPT_FAILED, 200)):
            r = self.c.notarize(
                action_id="act-1",
                outcome="failed",
                outcome_details="Rejected by upstream API",
            )
        assert r.status == "failed"
        assert r.receipt_id is None
        assert r.signature is None

    def test_notarize_invalid_state_raises(self):
        err_body = {
            "code": "INVALID_STATE",
            "message": "Action is not in authorized or approved state",
        }
        with patch.object(self.c._client, "post", return_value=_resp(err_body, 409)):
            with pytest.raises(AiraError) as ei:
                self.c.notarize(action_id="act-1")
        assert ei.value.code == "INVALID_STATE"

    def test_notarize_omits_outcome_details_when_none(self):
        with patch.object(self.c._client, "post", return_value=_resp(RECEIPT_COMPLETED, 200)) as m:
            self.c.notarize(action_id="act-1", outcome="completed")
            b = m.call_args[1]["json"]
            assert "outcome_details" not in b


# ==================== Full flow ====================

class TestFullFlow:
    def setup_method(self):
        self.c = Aira(api_key="aira_live_test", base_url="http://test")

    def teardown_method(self):
        self.c.close()

    def test_authorize_then_notarize_end_to_end(self):
        # Authorize
        with patch.object(self.c._client, "post", return_value=_resp(AUTH_OK, 201)):
            auth = self.c.authorize(action_type="wire_transfer", details="Send EUR 75K")
        assert auth.status == "authorized"

        # Notarize
        with patch.object(self.c._client, "post", return_value=_resp(RECEIPT_COMPLETED, 200)) as m:
            receipt = self.c.notarize(
                action_id=auth.action_id,
                outcome="completed",
                outcome_details="ref TX12345",
            )
            assert m.call_args[0][0] == f"/actions/{auth.action_id}/notarize"

        assert receipt.action_id == auth.action_id
        assert receipt.status == "notarized"
        assert receipt.signature is not None

    def test_pending_approval_then_wait(self):
        with patch.object(self.c._client, "post", return_value=_resp(AUTH_PENDING, 201)):
            auth = self.c.authorize(
                action_type="loan_decision",
                details="Approve EUR 50K loan",
                require_approval=True,
            )
        # Agent must NOT execute — status is pending_approval
        assert auth.status == "pending_approval"
        # (No notarize call yet — that happens after human approves.)


# ==================== Other actions ====================

class TestOtherActions:
    def setup_method(self):
        self.c = Aira(api_key="aira_live_test", base_url="http://test")

    def teardown_method(self):
        self.c.close()

    def test_get_action(self):
        with patch.object(self.c._client, "get", return_value=_resp(ACTION)):
            assert isinstance(self.c.get_action("act-1"), ActionDetail)

    def test_list_actions(self):
        with patch.object(self.c._client, "get", return_value=_paginated_resp([{"id": "1"}])):
            assert self.c.list_actions(action_type="email_sent").total == 1

    def test_cosign_action(self):
        cosign_body = {
            "action_id": "act-1",
            "cosigner_email": "alice@example.com",
            "cosigned_at": "2026-04-10T01:00:00Z",
            "cosignature_id": "cos-1",
        }
        with patch.object(self.c._client, "post", return_value=_resp(cosign_body)) as m:
            r = self.c.cosign_action("act-1")
            assert m.call_args[0][0] == "/actions/act-1/cosign"
        assert isinstance(r, CosignResult)
        assert r.cosigner_email == "alice@example.com"
        assert r.cosignature_id == "cos-1"

    def test_legal_hold(self):
        with patch.object(self.c._client, "post", return_value=_resp({"legal_hold": True})):
            assert self.c.set_legal_hold("act-1")["legal_hold"]

    def test_release_hold(self):
        with patch.object(self.c._client, "delete", return_value=_resp({"legal_hold": False})):
            assert not self.c.release_legal_hold("act-1")["legal_hold"]

    def test_chain(self):
        with patch.object(self.c._client, "get", return_value=_resp({"chain": [{"id": "1"}, {"id": "2"}]})):
            assert len(self.c.get_action_chain("act-1")) == 2

    def test_verify_uses_public_client(self):
        with patch.object(
            self.c._public_client,
            "get",
            return_value=_resp({"valid": True, "public_key_id": "k", "message": "OK", "verified_at": "t", "request_id": "r"}),
        ):
            assert self.c.verify_action("act-1").valid


class TestSyncAgents:
    def setup_method(self):
        self.c = Aira(api_key="aira_live_test", base_url="http://test")

    def teardown_method(self):
        self.c.close()

    def test_register(self):
        with patch.object(self.c._client, "post", return_value=_resp(AGENT, 201)):
            assert self.c.register_agent("my-agent", "My Agent").agent_slug == "my-agent"

    def test_get(self):
        with patch.object(self.c._client, "get", return_value=_resp(AGENT)):
            assert self.c.get_agent("my-agent").display_name == "My Agent"

    def test_list(self):
        with patch.object(self.c._client, "get", return_value=_paginated_resp([AGENT])):
            assert self.c.list_agents(status="active").total == 1

    def test_update(self):
        with patch.object(self.c._client, "put", return_value=_resp({**AGENT, "display_name": "Updated"})):
            assert self.c.update_agent("my-agent", display_name="Updated").display_name == "Updated"

    def test_publish_version(self):
        with patch.object(self.c._client, "post", return_value=_resp(VERSION, 201)):
            assert self.c.publish_version("my-agent", "1.0.0", model_id="claude").version == "1.0.0"

    def test_list_versions(self):
        with patch.object(self.c._client, "get", return_value=_resp([VERSION])):
            assert len(self.c.list_versions("my-agent")) == 1

    def test_decommission(self):
        with patch.object(self.c._client, "post", return_value=_resp({**AGENT, "status": "decommissioned"})):
            assert self.c.decommission_agent("my-agent").status == "decommissioned"

    def test_transfer(self):
        with patch.object(self.c._client, "post", return_value=_resp({"status": "transferred"})):
            assert self.c.transfer_agent("my-agent", "org-2", reason="M&A")["status"] == "transferred"

    def test_agent_actions(self):
        with patch.object(self.c._client, "get", return_value=_paginated_resp([{"id": "a1"}])):
            assert self.c.get_agent_actions("my-agent").total == 1


class TestSyncEvidence:
    def setup_method(self):
        self.c = Aira(api_key="aira_live_test", base_url="http://test")

    def teardown_method(self):
        self.c.close()

    def test_create(self):
        with patch.object(self.c._client, "post", return_value=_resp(EVIDENCE, 201)):
            assert self.c.create_evidence_package("Test", ["act-1"]).package_hash == "sha256:p"

    def test_list(self):
        with patch.object(self.c._client, "get", return_value=_paginated_resp([{"id": "p1"}])):
            assert self.c.list_evidence_packages().total == 1

    def test_get(self):
        with patch.object(self.c._client, "get", return_value=_resp(EVIDENCE)):
            assert self.c.get_evidence_package("pkg-1").title == "Test"

    def test_time_travel(self):
        with patch.object(self.c._client, "post", return_value=_resp({"result_count": 5})):
            assert self.c.time_travel("2026-03-20T00:00:00Z")["result_count"] == 5

    def test_liability_chain(self):
        with patch.object(self.c._client, "get", return_value=_resp({"chain": [{"id": "1"}]})):
            assert len(self.c.liability_chain("act-1")) == 1


class TestSyncEstate:
    def setup_method(self):
        self.c = Aira(api_key="aira_live_test", base_url="http://test")

    def teardown_method(self):
        self.c.close()

    def test_set_will(self):
        with patch.object(self.c._client, "put", return_value=_resp({"id": "w1"})):
            assert self.c.set_agent_will("my-agent", successor_slug="v2")["id"] == "w1"

    def test_get_will(self):
        with patch.object(self.c._client, "get", return_value=_resp({"id": "w1"})):
            assert self.c.get_agent_will("my-agent")["id"] == "w1"

    def test_issue_death_cert(self):
        with patch.object(self.c._client, "post", return_value=_resp({"id": "dc-1"}, 201)):
            assert self.c.issue_death_certificate("my-agent")["id"] == "dc-1"

    def test_get_death_cert(self):
        with patch.object(self.c._client, "get", return_value=_resp({"id": "dc-1"})):
            assert self.c.get_death_certificate("my-agent")["id"] == "dc-1"

    def test_create_snapshot(self):
        with patch.object(self.c._client, "post", return_value=_resp(SNAPSHOT, 201)):
            assert self.c.create_compliance_snapshot("eu-ai-act").framework == "eu-ai-act"

    def test_list_snapshots(self):
        with patch.object(self.c._client, "get", return_value=_paginated_resp([{"id": "s1"}])):
            assert self.c.list_compliance_snapshots(framework="eu-ai-act").total == 1


class TestSyncEscrow:
    def setup_method(self):
        self.c = Aira(api_key="aira_live_test", base_url="http://test")

    def teardown_method(self):
        self.c.close()

    def test_create_account(self):
        with patch.object(self.c._client, "post", return_value=_resp(ESCROW_ACC, 201)):
            assert self.c.create_escrow_account(purpose="Test").balance == "5000.00"

    def test_list_accounts(self):
        with patch.object(self.c._client, "get", return_value=_paginated_resp([{"id": "e1"}])):
            assert self.c.list_escrow_accounts().total == 1

    def test_get_account(self):
        with patch.object(self.c._client, "get", return_value=_resp(ESCROW_ACC)):
            assert self.c.get_escrow_account("esc-1").status == "active"

    def test_deposit(self):
        with patch.object(self.c._client, "post", return_value=_resp(ESCROW_TX, 201)):
            assert self.c.escrow_deposit("esc-1", 5000.0).transaction_type == "deposit"

    def test_release(self):
        with patch.object(self.c._client, "post", return_value=_resp({**ESCROW_TX, "transaction_type": "release"}, 201)):
            assert self.c.escrow_release("esc-1", 2000.0).transaction_type == "release"

    def test_dispute(self):
        with patch.object(self.c._client, "post", return_value=_resp({**ESCROW_TX, "transaction_type": "dispute", "status": "disputed"}, 201)):
            assert self.c.escrow_dispute("esc-1", 1000.0, "Agent error").status == "disputed"


class TestSyncChat:
    def setup_method(self):
        self.c = Aira(api_key="aira_live_test", base_url="http://test")

    def teardown_method(self):
        self.c.close()

    def test_ask(self):
        with patch.object(self.c._client, "post", return_value=_resp({"content": "3 agents", "tools_used": []})):
            assert self.c.ask("How many?")["content"] == "3 agents"


class TestErrors:
    def setup_method(self):
        self.c = Aira(api_key="aira_live_test", base_url="http://test")

    def teardown_method(self):
        self.c.close()

    def test_404(self):
        with patch.object(self.c._client, "get", return_value=_resp({"message": "Not found", "code": "NOT_FOUND"}, 404)):
            with pytest.raises(AiraError) as e:
                self.c.get_action("bad")
            assert e.value.status_code == 404
            assert e.value.message == "Not found"

    def test_429(self):
        with patch.object(self.c._client, "post", return_value=_resp({"message": "Rate limited", "code": "RATE_LIMIT_EXCEEDED"}, 429)):
            with pytest.raises(AiraError) as e:
                self.c.authorize(action_type="x", details="y")
            assert e.value.status_code == 429

    def test_500(self):
        with patch.object(self.c._client, "get", return_value=_resp({"message": "Internal", "code": "INTERNAL"}, 500)):
            with pytest.raises(AiraError):
                self.c.get_agent("x")

    def test_non_json(self):
        resp = httpx.Response(status_code=502, text="Bad Gateway", request=httpx.Request("GET", "http://test"))
        with patch.object(self.c._client, "get", return_value=resp):
            with pytest.raises(AiraError) as e:
                self.c.get_action("x")
            assert e.value.status_code == 502


class TestContextManager:
    def test_sync(self):
        with Aira(api_key="aira_live_test", base_url="http://test") as c:
            assert c._client is not None

    @pytest.mark.asyncio
    async def test_async(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            assert c._client is not None


# ==================== Async ====================

class TestAsync:
    @pytest.mark.asyncio
    async def test_authorize(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "post", return_value=_resp(AUTH_OK, 201)):
                a = await c.authorize(action_type="x", details="y")
                assert a.action_id == "act-1"
                assert a.status == "authorized"

    @pytest.mark.asyncio
    async def test_notarize(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "post", return_value=_resp(RECEIPT_COMPLETED, 200)) as m:
                r = await c.notarize(action_id="act-1", outcome="completed")
                assert m.call_args[0][0] == "/actions/act-1/notarize"
                assert r.status == "notarized"

    @pytest.mark.asyncio
    async def test_notarize_failed(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "post", return_value=_resp(RECEIPT_FAILED, 200)):
                r = await c.notarize(action_id="act-1", outcome="failed", outcome_details="oops")
                assert r.status == "failed"
                assert r.receipt_id is None

    @pytest.mark.asyncio
    async def test_authorize_policy_denied(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            err = {"code": "POLICY_DENIED", "message": "denied", "details": {"action_id": "act-1", "policy_id": "pol-1"}}
            with patch.object(c._client, "post", return_value=_resp(err, 403)):
                with pytest.raises(AiraError) as ei:
                    await c.authorize(action_type="x", details="y")
                assert ei.value.code == "POLICY_DENIED"
                assert ei.value.details["policy_id"] == "pol-1"

    @pytest.mark.asyncio
    async def test_full_flow_end_to_end(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "post", return_value=_resp(AUTH_OK, 201)):
                auth = await c.authorize(action_type="x", details="y")
            with patch.object(c._client, "post", return_value=_resp(RECEIPT_COMPLETED, 200)):
                receipt = await c.notarize(action_id=auth.action_id, outcome="completed")
            assert receipt.action_id == auth.action_id
            assert receipt.status == "notarized"

    @pytest.mark.asyncio
    async def test_get_action(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "get", return_value=_resp(ACTION)):
                assert (await c.get_action("act-1")).action_type == "email_sent"

    @pytest.mark.asyncio
    async def test_list_actions(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "get", return_value=_paginated_resp([{"id": "1"}])):
                assert (await c.list_actions()).total == 1

    @pytest.mark.asyncio
    async def test_cosign_action(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            cosign_body = {
                "action_id": "act-1",
                "cosigner_email": "alice@example.com",
                "cosigned_at": "2026-04-10T01:00:00Z",
                "cosignature_id": "cos-1",
            }
            with patch.object(c._client, "post", return_value=_resp(cosign_body)):
                r = await c.cosign_action("act-1")
                assert r.cosigner_email == "alice@example.com"

    @pytest.mark.asyncio
    async def test_register_agent(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "post", return_value=_resp(AGENT, 201)):
                assert (await c.register_agent("a", "A")).agent_slug == "my-agent"

    @pytest.mark.asyncio
    async def test_verify_no_auth(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._public_client, "get", return_value=_resp({"valid": True, "public_key_id": "k", "message": "OK", "verified_at": "t", "request_id": "r"})):
                assert (await c.verify_action("act-1")).valid

    @pytest.mark.asyncio
    async def test_escrow_deposit(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "post", return_value=_resp(ESCROW_TX, 201)):
                assert (await c.escrow_deposit("esc-1", 5000.0)).transaction_type == "deposit"

    @pytest.mark.asyncio
    async def test_evidence_package(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "post", return_value=_resp(EVIDENCE, 201)):
                assert (await c.create_evidence_package("T", ["a"])).package_hash == "sha256:p"

    @pytest.mark.asyncio
    async def test_compliance_snapshot(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "post", return_value=_resp(SNAPSHOT, 201)):
                assert (await c.create_compliance_snapshot("eu-ai-act")).framework == "eu-ai-act"

    @pytest.mark.asyncio
    async def test_set_will(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "put", return_value=_resp({"id": "w1"})):
                assert (await c.set_agent_will("a", successor_slug="b"))["id"] == "w1"

    @pytest.mark.asyncio
    async def test_list_agents(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "get", return_value=_paginated_resp([AGENT])):
                assert (await c.list_agents()).total == 1

    @pytest.mark.asyncio
    async def test_time_travel(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "post", return_value=_resp({"result_count": 3})):
                assert (await c.time_travel("2026-03-20T00:00:00Z"))["result_count"] == 3

    @pytest.mark.asyncio
    async def test_set_legal_hold(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "post", return_value=_resp({"legal_hold": True})):
                assert (await c.set_legal_hold("act-1"))["legal_hold"]

    @pytest.mark.asyncio
    async def test_release_legal_hold(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "delete", return_value=_resp({"legal_hold": False})):
                assert not (await c.release_legal_hold("act-1"))["legal_hold"]

    @pytest.mark.asyncio
    async def test_get_action_chain(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "get", return_value=_resp({"chain": [{"id": "1"}, {"id": "2"}]})):
                assert len(await c.get_action_chain("act-1")) == 2

    @pytest.mark.asyncio
    async def test_get_agent(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "get", return_value=_resp(AGENT)):
                assert (await c.get_agent("my-agent")).display_name == "My Agent"

    @pytest.mark.asyncio
    async def test_update_agent(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "put", return_value=_resp({**AGENT, "display_name": "Updated"})):
                assert (await c.update_agent("my-agent", display_name="Updated")).display_name == "Updated"

    @pytest.mark.asyncio
    async def test_publish_version(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "post", return_value=_resp(VERSION, 201)):
                assert (await c.publish_version("my-agent", "1.0.0")).version == "1.0.0"

    @pytest.mark.asyncio
    async def test_list_versions(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "get", return_value=_resp([VERSION])):
                assert len(await c.list_versions("my-agent")) == 1

    @pytest.mark.asyncio
    async def test_list_versions_empty(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "get", return_value=_resp({})):
                assert await c.list_versions("my-agent") == []

    @pytest.mark.asyncio
    async def test_decommission_agent(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "post", return_value=_resp({**AGENT, "status": "decommissioned"})):
                assert (await c.decommission_agent("my-agent")).status == "decommissioned"

    @pytest.mark.asyncio
    async def test_transfer_agent(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "post", return_value=_resp({"status": "transferred"})):
                assert (await c.transfer_agent("my-agent", "org-2", reason="M&A"))["status"] == "transferred"

    @pytest.mark.asyncio
    async def test_get_agent_actions(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "get", return_value=_paginated_resp([{"id": "a1"}])):
                assert (await c.get_agent_actions("my-agent")).total == 1

    @pytest.mark.asyncio
    async def test_run_case(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "post", return_value=_resp({"case_id": "c1"})):
                assert (await c.run_case("test", ["gpt-4"]))["case_id"] == "c1"

    @pytest.mark.asyncio
    async def test_run_case_with_options(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "post", return_value=_resp({"case_id": "c1"})) as m:
                await c.run_case("test", ["gpt-4"], temperature=0.5)
                body = m.call_args[1]["json"]
                assert body["options"]["temperature"] == 0.5

    @pytest.mark.asyncio
    async def test_get_case(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "get", return_value=_resp({"case_id": "c1", "status": "complete"})):
                assert (await c.get_case("c1"))["status"] == "complete"

    @pytest.mark.asyncio
    async def test_list_cases(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "get", return_value=_paginated_resp([{"id": "c1"}])):
                assert (await c.list_cases()).total == 1

    @pytest.mark.asyncio
    async def test_get_receipt(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "get", return_value=_resp({"receipt_id": "r1"})):
                assert (await c.get_receipt("r1"))["receipt_id"] == "r1"

    @pytest.mark.asyncio
    async def test_export_receipt(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "get", return_value=_resp({"url": "https://..."})):
                assert (await c.export_receipt("r1", format="pdf"))["url"]

    @pytest.mark.asyncio
    async def test_list_evidence_packages(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "get", return_value=_paginated_resp([{"id": "p1"}])):
                assert (await c.list_evidence_packages()).total == 1

    @pytest.mark.asyncio
    async def test_get_evidence_package(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "get", return_value=_resp(EVIDENCE)):
                assert (await c.get_evidence_package("pkg-1")).title == "Test"

    @pytest.mark.asyncio
    async def test_liability_chain(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "get", return_value=_resp({"chain": [{"id": "1"}]})):
                assert len(await c.liability_chain("act-1")) == 1

    @pytest.mark.asyncio
    async def test_get_agent_will(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "get", return_value=_resp({"id": "w1"})):
                assert (await c.get_agent_will("a"))["id"] == "w1"

    @pytest.mark.asyncio
    async def test_issue_death_certificate(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "post", return_value=_resp({"id": "dc-1"}, 201)):
                assert (await c.issue_death_certificate("a"))["id"] == "dc-1"

    @pytest.mark.asyncio
    async def test_get_death_certificate(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "get", return_value=_resp({"id": "dc-1"})):
                assert (await c.get_death_certificate("a"))["id"] == "dc-1"

    @pytest.mark.asyncio
    async def test_list_compliance_snapshots(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "get", return_value=_paginated_resp([{"id": "s1"}])):
                assert (await c.list_compliance_snapshots(framework="eu-ai-act")).total == 1

    @pytest.mark.asyncio
    async def test_create_escrow_account(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "post", return_value=_resp(ESCROW_ACC, 201)):
                assert (await c.create_escrow_account(purpose="Test")).balance == "5000.00"

    @pytest.mark.asyncio
    async def test_list_escrow_accounts(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "get", return_value=_paginated_resp([{"id": "e1"}])):
                assert (await c.list_escrow_accounts()).total == 1

    @pytest.mark.asyncio
    async def test_get_escrow_account(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "get", return_value=_resp(ESCROW_ACC)):
                assert (await c.get_escrow_account("esc-1")).status == "active"

    @pytest.mark.asyncio
    async def test_escrow_release(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "post", return_value=_resp({**ESCROW_TX, "transaction_type": "release"}, 201)):
                assert (await c.escrow_release("esc-1", 2000.0)).transaction_type == "release"

    @pytest.mark.asyncio
    async def test_escrow_dispute(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "post", return_value=_resp({**ESCROW_TX, "transaction_type": "dispute", "status": "disputed"}, 201)):
                assert (await c.escrow_dispute("esc-1", 1000.0, "Agent error")).status == "disputed"

    @pytest.mark.asyncio
    async def test_ask(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "post", return_value=_resp({"content": "hello", "tools_used": []})):
                assert (await c.ask("hi"))["content"] == "hello"


# ==================== Trust Layer: DID ====================

class TestSyncDID:
    def setup_method(self):
        self.c = Aira(api_key="aira_live_test", base_url="http://test")

    def teardown_method(self):
        self.c.close()

    def test_get_agent_did(self):
        did_data = {"did": "did:web:airaproof.com:agents:my-agent", "document": {}, "version": 1}
        with patch.object(self.c._client, "get", return_value=_resp(did_data)):
            result = self.c.get_agent_did("my-agent")
            assert result["did"] == "did:web:airaproof.com:agents:my-agent"

    def test_rotate_agent_keys(self):
        with patch.object(self.c._client, "post", return_value=_resp({"did": "did:web:airaproof.com:agents:my-agent", "version": 2})):
            result = self.c.rotate_agent_keys("my-agent")
            assert result["version"] == 2

    def test_resolve_did(self):
        doc = {"id": "did:web:example.com:agents:other", "verificationMethod": []}
        with patch.object(self.c._client, "post", return_value=_resp(doc)) as m:
            result = self.c.resolve_did("did:web:example.com:agents:other")
            assert result["id"] == "did:web:example.com:agents:other"
            body = m.call_args[1]["json"]
            assert body["did"] == "did:web:example.com:agents:other"


class TestSyncCredentials:
    def setup_method(self):
        self.c = Aira(api_key="aira_live_test", base_url="http://test")

    def teardown_method(self):
        self.c.close()

    def test_get_agent_credential(self):
        vc = {"type": ["VerifiableCredential", "AgentCapabilityCredential"], "issuer": "did:web:airaproof.com"}
        with patch.object(self.c._client, "get", return_value=_resp(vc)):
            result = self.c.get_agent_credential("my-agent")
            assert "VerifiableCredential" in result["type"]

    def test_get_agent_credentials(self):
        with patch.object(self.c._client, "get", return_value=_resp({"credentials": [{"id": "vc-1"}, {"id": "vc-2"}]})):
            result = self.c.get_agent_credentials("my-agent")
            assert len(result["credentials"]) == 2

    def test_revoke_credential(self):
        with patch.object(self.c._client, "post", return_value=_resp({"revoked": True})) as m:
            result = self.c.revoke_credential("my-agent", reason="Compromised")
            assert result["revoked"] is True
            body = m.call_args[1]["json"]
            assert body["reason"] == "Compromised"

    def test_revoke_credential_default_reason(self):
        with patch.object(self.c._client, "post", return_value=_resp({"revoked": True})) as m:
            self.c.revoke_credential("my-agent")
            body = m.call_args[1]["json"]
            assert body["reason"] == ""

    def test_verify_credential(self):
        vc = {"type": ["VerifiableCredential"], "proof": {"type": "Ed25519Signature2020"}}
        with patch.object(self.c._client, "post", return_value=_resp({"valid": True, "checks": {}})) as m:
            result = self.c.verify_credential(vc)
            assert result["valid"] is True
            body = m.call_args[1]["json"]
            assert body["credential"] == vc


class TestSyncMutualSign:
    def setup_method(self):
        self.c = Aira(api_key="aira_live_test", base_url="http://test")

    def teardown_method(self):
        self.c.close()

    def test_request_mutual_sign(self):
        with patch.object(self.c._client, "post", return_value=_resp({"status": "pending", "action_id": "act-1"})) as m:
            result = self.c.request_mutual_sign("act-1", "did:web:example.com:agents:other")
            assert result["status"] == "pending"
            body = m.call_args[1]["json"]
            assert body["counterparty_did"] == "did:web:example.com:agents:other"

    def test_get_pending_mutual_sign(self):
        with patch.object(self.c._client, "get", return_value=_resp({"payload": {"action_id": "act-1"}, "payload_hash": "sha256:abc"})):
            result = self.c.get_pending_mutual_sign("act-1")
            assert result["payload_hash"] == "sha256:abc"

    def test_complete_mutual_sign(self):
        with patch.object(self.c._client, "post", return_value=_resp({"status": "completed", "combined_receipt_hash": "sha256:xyz"})) as m:
            result = self.c.complete_mutual_sign("act-1", "did:web:example.com:agents:other", "zsig123", "sha256:abc")
            assert result["status"] == "completed"
            body = m.call_args[1]["json"]
            assert body["did"] == "did:web:example.com:agents:other"
            assert body["signature"] == "zsig123"
            assert body["signed_payload_hash"] == "sha256:abc"

    def test_get_mutual_sign_receipt(self):
        with patch.object(self.c._client, "get", return_value=_resp({"receipt_id": "rct-1", "signatures": ["sig-a", "sig-b"]})):
            result = self.c.get_mutual_sign_receipt("act-1")
            assert len(result["signatures"]) == 2

    def test_reject_mutual_sign(self):
        with patch.object(self.c._client, "post", return_value=_resp({"status": "rejected"})) as m:
            result = self.c.reject_mutual_sign("act-1", reason="Not authorized")
            assert result["status"] == "rejected"
            body = m.call_args[1]["json"]
            assert body["reason"] == "Not authorized"

    def test_reject_mutual_sign_default_reason(self):
        with patch.object(self.c._client, "post", return_value=_resp({"status": "rejected"})) as m:
            self.c.reject_mutual_sign("act-1")
            body = m.call_args[1]["json"]
            assert body["reason"] == ""


class TestSyncReputation:
    def setup_method(self):
        self.c = Aira(api_key="aira_live_test", base_url="http://test")

    def teardown_method(self):
        self.c.close()

    def test_get_reputation(self):
        with patch.object(self.c._client, "get", return_value=_resp({"score": 84, "tier": "Verified"})):
            result = self.c.get_reputation("my-agent")
            assert result["score"] == 84
            assert result["tier"] == "Verified"

    def test_get_reputation_history(self):
        with patch.object(self.c._client, "get", return_value=_resp({"history": [{"score": 80}, {"score": 84}]})):
            result = self.c.get_reputation_history("my-agent")
            assert len(result["history"]) == 2

    def test_attest_reputation(self):
        with patch.object(self.c._client, "post", return_value=_resp({"recorded": True})) as m:
            result = self.c.attest_reputation("my-agent", "did:web:example.com:agents:other", "act-1", "positive", "zsig456")
            assert result["recorded"] is True
            body = m.call_args[1]["json"]
            assert body["counterparty_did"] == "did:web:example.com:agents:other"
            assert body["action_id"] == "act-1"
            assert body["attestation"] == "positive"
            assert body["signature"] == "zsig456"

    def test_verify_reputation(self):
        with patch.object(self.c._client, "get", return_value=_resp({"score_hash": "sha256:rep", "inputs": {}})):
            result = self.c.verify_reputation("my-agent")
            assert result["score_hash"] == "sha256:rep"
