"""Tests for require_approval parameter in Aira SDK."""

from unittest.mock import patch

import httpx
import pytest

from aira import Aira, AsyncAira, ActionReceipt


# --- Helpers ---

def _resp(data, status: int = 200) -> httpx.Response:
    return httpx.Response(status_code=status, json=data, request=httpx.Request("GET", "http://test"))


RECEIPT = {
    "action_id": "act-1",
    "receipt_id": "rct-1",
    "payload_hash": "sha256:abc",
    "signature": "ed25519:xyz",
    "timestamp_token": "ts",
    "created_at": "2026-03-25T00:00:00Z",
    "request_id": "req-1",
    "warnings": None,
}

PENDING_RECEIPT = {
    "action_id": "act-1",
    "status": "pending_approval",
    "receipt_id": None,
    "payload_hash": None,
    "signature": None,
    "timestamp_token": None,
    "created_at": "2026-03-25T00:00:00Z",
    "request_id": "req-1",
    "warnings": None,
}


class TestRequireApproval:
    def setup_method(self):
        self.c = Aira(api_key="aira_live_test", base_url="http://test")

    def teardown_method(self):
        self.c.close()

    def test_notarize_sends_require_approval_field(self):
        with patch.object(self.c._client, "post", return_value=_resp(PENDING_RECEIPT, 201)) as m:
            self.c.notarize(
                action_type="loan_decision",
                details="Approve loan for $50k",
                require_approval=True,
                approvers=["manager@example.com"],
            )
            body = m.call_args[1]["json"]
            assert body["require_approval"] is True
            assert body["approvers"] == ["manager@example.com"]

    def test_notarize_omits_require_approval_when_false(self):
        with patch.object(self.c._client, "post", return_value=_resp(RECEIPT, 201)) as m:
            self.c.notarize(action_type="test", details="No approval needed")
            body = m.call_args[1]["json"]
            # Default False → converted to None → omitted by _build_body
            assert "require_approval" not in body

    def test_notarize_omits_approvers_when_none(self):
        with patch.object(self.c._client, "post", return_value=_resp(RECEIPT, 201)) as m:
            self.c.notarize(action_type="test", details="No approval")
            body = m.call_args[1]["json"]
            assert "approvers" not in body

    def test_pending_receipt_parsed_correctly(self):
        with patch.object(self.c._client, "post", return_value=_resp(PENDING_RECEIPT, 201)):
            r = self.c.notarize(
                action_type="loan_decision",
                details="test",
                require_approval=True,
            )
            assert isinstance(r, ActionReceipt)
            assert r.status == "pending_approval"
            assert r.receipt_id is None
            assert r.action_id == "act-1"

    def test_notarize_with_approvers_list(self):
        with patch.object(self.c._client, "post", return_value=_resp(PENDING_RECEIPT, 201)) as m:
            self.c.notarize(
                action_type="test",
                details="test",
                require_approval=True,
                approvers=["a@b.com", "c@d.com"],
            )
            body = m.call_args[1]["json"]
            assert body["approvers"] == ["a@b.com", "c@d.com"]

    def test_trace_passes_require_approval(self):
        with patch.object(self.c._client, "post", return_value=_resp(RECEIPT, 201)) as m:

            @self.c.trace(
                agent_id="test-agent",
                action_type="function_call",
                require_approval=True,
                approvers=["boss@example.com"],
            )
            def my_function():
                return "result"

            my_function()

            body = m.call_args[1]["json"]
            assert body["require_approval"] is True
            assert body["approvers"] == ["boss@example.com"]


class TestAsyncRequireApproval:
    @pytest.mark.asyncio
    async def test_async_notarize_sends_require_approval(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "post", return_value=_resp(PENDING_RECEIPT, 201)) as m:
                await c.notarize(
                    action_type="loan_decision",
                    details="Approve loan",
                    require_approval=True,
                    approvers=["mgr@example.com"],
                )
                body = m.call_args[1]["json"]
                assert body["require_approval"] is True
                assert body["approvers"] == ["mgr@example.com"]

    @pytest.mark.asyncio
    async def test_async_notarize_omits_require_approval_when_false(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "post", return_value=_resp(RECEIPT, 201)) as m:
                await c.notarize(action_type="test", details="No approval")
                body = m.call_args[1]["json"]
                assert "require_approval" not in body

    @pytest.mark.asyncio
    async def test_async_pending_receipt_parsed(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "post", return_value=_resp(PENDING_RECEIPT, 201)):
                r = await c.notarize(
                    action_type="test",
                    details="test",
                    require_approval=True,
                )
                assert r.status == "pending_approval"
                assert r.receipt_id is None

    @pytest.mark.asyncio
    async def test_async_trace_passes_require_approval(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "post", return_value=_resp(RECEIPT, 201)) as m:

                @c.trace(
                    agent_id="test-agent",
                    require_approval=True,
                    approvers=["boss@example.com"],
                )
                async def my_async_fn():
                    return "done"

                await my_async_fn()

                body = m.call_args[1]["json"]
                assert body["require_approval"] is True
                assert body["approvers"] == ["boss@example.com"]
