"""Tests for the require_approval parameter of authorize()."""

from unittest.mock import patch

import httpx
import pytest

from aira import Aira, AsyncAira, Authorization


def _resp(data, status: int = 200) -> httpx.Response:
    return httpx.Response(status_code=status, json=data, request=httpx.Request("GET", "http://test"))


PENDING_AUTH = {
    "action_id": "act-1",
    "status": "pending_approval",
    "created_at": "2026-04-10T00:00:00Z",
    "request_id": "req-1",
    "warnings": None,
}

AUTHORIZED = {
    "action_id": "act-1",
    "status": "authorized",
    "created_at": "2026-04-10T00:00:00Z",
    "request_id": "req-1",
    "warnings": None,
}


class TestRequireApproval:
    def setup_method(self):
        self.c = Aira(api_key="aira_live_test", base_url="http://test")

    def teardown_method(self):
        self.c.close()

    def test_authorize_sends_require_approval(self):
        with patch.object(self.c._client, "post", return_value=_resp(PENDING_AUTH, 201)) as m:
            self.c.authorize(
                action_type="loan_decision",
                details="Approve loan for $50k",
                require_approval=True,
                approvers=["manager@example.com"],
            )
            body = m.call_args[1]["json"]
            assert body["require_approval"] is True
            assert body["approvers"] == ["manager@example.com"]

    def test_authorize_omits_require_approval_when_false(self):
        with patch.object(self.c._client, "post", return_value=_resp(AUTHORIZED, 201)) as m:
            self.c.authorize(action_type="test", details="No approval needed")
            body = m.call_args[1]["json"]
            # False → None → omitted by _build_body
            assert "require_approval" not in body

    def test_authorize_omits_approvers_when_none(self):
        with patch.object(self.c._client, "post", return_value=_resp(AUTHORIZED, 201)) as m:
            self.c.authorize(action_type="test", details="No approval")
            body = m.call_args[1]["json"]
            assert "approvers" not in body

    def test_pending_approval_parsed(self):
        with patch.object(self.c._client, "post", return_value=_resp(PENDING_AUTH, 201)):
            a = self.c.authorize(
                action_type="loan_decision",
                details="test",
                require_approval=True,
            )
        assert isinstance(a, Authorization)
        assert a.status == "pending_approval"
        assert a.action_id == "act-1"

    def test_authorize_with_multiple_approvers(self):
        with patch.object(self.c._client, "post", return_value=_resp(PENDING_AUTH, 201)) as m:
            self.c.authorize(
                action_type="test",
                details="test",
                require_approval=True,
                approvers=["a@b.com", "c@d.com"],
            )
            body = m.call_args[1]["json"]
            assert body["approvers"] == ["a@b.com", "c@d.com"]


class TestAsyncRequireApproval:
    @pytest.mark.asyncio
    async def test_async_authorize_sends_require_approval(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "post", return_value=_resp(PENDING_AUTH, 201)) as m:
                await c.authorize(
                    action_type="loan_decision",
                    details="Approve loan",
                    require_approval=True,
                    approvers=["mgr@example.com"],
                )
                body = m.call_args[1]["json"]
                assert body["require_approval"] is True
                assert body["approvers"] == ["mgr@example.com"]

    @pytest.mark.asyncio
    async def test_async_authorize_omits_require_approval_when_false(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "post", return_value=_resp(AUTHORIZED, 201)) as m:
                await c.authorize(action_type="test", details="No approval")
                body = m.call_args[1]["json"]
                assert "require_approval" not in body

    @pytest.mark.asyncio
    async def test_async_pending_parsed(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "post", return_value=_resp(PENDING_AUTH, 201)):
                a = await c.authorize(
                    action_type="test",
                    details="test",
                    require_approval=True,
                )
                assert a.status == "pending_approval"
                assert a.action_id == "act-1"
