"""Tests for AiraSession and AsyncAiraSession — two-step flow."""

from unittest.mock import patch

import httpx
import pytest

from aira import Aira, AsyncAira


def _resp(data, status: int = 200) -> httpx.Response:
    return httpx.Response(status_code=status, json=data, request=httpx.Request("GET", "http://test"))


AUTH_OK = {
    "action_id": "act-1",
    "status": "authorized",
    "created_at": "2026-04-10T00:00:00Z",
    "request_id": "req-1",
    "warnings": None,
}

RECEIPT = {
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


class TestSyncSession:
    def setup_method(self):
        self.c = Aira(api_key="aira_live_test", base_url="http://test")

    def teardown_method(self):
        self.c.close()

    def test_session_prefills_agent_id_on_authorize(self):
        with patch.object(self.c._client, "post", return_value=_resp(AUTH_OK, 201)) as m:
            s = self.c.session(agent_id="my-agent")
            s.authorize(action_type="x", details="y")
            body = m.call_args[1]["json"]
            assert body["agent_id"] == "my-agent"

    def test_kwarg_override(self):
        with patch.object(self.c._client, "post", return_value=_resp(AUTH_OK, 201)) as m:
            s = self.c.session(agent_id="default-agent")
            s.authorize(action_type="x", details="y", agent_id="override-agent")
            body = m.call_args[1]["json"]
            assert body["agent_id"] == "override-agent"

    def test_context_manager_works(self):
        with self.c.session(agent_id="my-agent") as s:
            assert s._defaults["agent_id"] == "my-agent"

    def test_multiple_defaults(self):
        with patch.object(self.c._client, "post", return_value=_resp(AUTH_OK, 201)) as m:
            s = self.c.session(agent_id="my-agent", model_id="claude-4", agent_version="1.0")
            s.authorize(action_type="x", details="y")
            body = m.call_args[1]["json"]
            assert body["agent_id"] == "my-agent"
            assert body["model_id"] == "claude-4"
            assert body["agent_version"] == "1.0"

    def test_session_does_not_close_parent(self):
        s = self.c.session(agent_id="my-agent")
        s.__exit__(None, None, None)
        # Parent client should still be usable
        with patch.object(self.c._client, "post", return_value=_resp(AUTH_OK, 201)):
            a = self.c.authorize(action_type="x", details="y")
            assert a.action_id == "act-1"

    def test_all_authorize_params_forwarded(self):
        with patch.object(self.c._client, "post", return_value=_resp(AUTH_OK, 201)) as m:
            s = self.c.session(agent_id="a", model_id="m")
            s.authorize(
                action_type="email_sent", details="test",
                instruction_hash="h", parent_action_id="p",
                store_details=True, idempotency_key="k",
            )
            body = m.call_args[1]["json"]
            assert body["agent_id"] == "a"
            assert body["model_id"] == "m"
            assert body["instruction_hash"] == "h"
            assert body["parent_action_id"] == "p"
            assert body["idempotency_key"] == "k"

    def test_session_notarize_forwards_to_client(self):
        with patch.object(self.c._client, "post", return_value=_resp(RECEIPT, 200)) as m:
            s = self.c.session(agent_id="a")
            receipt = s.notarize(action_id="act-1", outcome="completed", outcome_details="ok")
            assert m.call_args[0][0] == "/actions/act-1/notarize"
            body = m.call_args[1]["json"]
            assert body["outcome"] == "completed"
            assert body["outcome_details"] == "ok"
        assert receipt.status == "notarized"


class TestAsyncSession:
    @pytest.mark.asyncio
    async def test_async_session_prefills(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "post", return_value=_resp(AUTH_OK, 201)) as m:
                s = c.session(agent_id="async-agent")
                await s.authorize(action_type="x", details="y")
                body = m.call_args[1]["json"]
                assert body["agent_id"] == "async-agent"

    @pytest.mark.asyncio
    async def test_async_session_context_manager(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            async with c.session(agent_id="my-agent") as s:
                assert s._defaults["agent_id"] == "my-agent"

    @pytest.mark.asyncio
    async def test_async_session_authorize_and_notarize(self):
        async with AsyncAira(api_key="aira_live_test", base_url="http://test") as c:
            with patch.object(c._client, "post", return_value=_resp(AUTH_OK, 201)):
                s = c.session(agent_id="a", model_id="claude")
                auth = await s.authorize(action_type="decision", details="approved")
                assert auth.action_id == "act-1"
            with patch.object(c._client, "post", return_value=_resp(RECEIPT, 200)) as m:
                r = await s.notarize(action_id=auth.action_id, outcome="completed")
                assert m.call_args[0][0] == "/actions/act-1/notarize"
            assert r.status == "notarized"
