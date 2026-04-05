"""Tests for offline queue and offline-mode client behavior."""

from unittest.mock import patch, MagicMock, AsyncMock

import httpx
import pytest

from aira import Aira, AsyncAira
from aira.client import AiraError
from aira._offline import OfflineQueue, QueuedRequest


# --- Helpers (same pattern as test_client.py) ---

def _resp(data, status: int = 200) -> httpx.Response:
    return httpx.Response(status_code=status, json=data, request=httpx.Request("GET", "http://test"))


RECEIPT = {
    "action_id": "act-1", "receipt_id": "rct-1", "payload_hash": "sha256:abc",
    "signature": "ed25519:xyz", "timestamp_token": "ts",
    "created_at": "2026-03-25T00:00:00Z", "request_id": "req-1", "warnings": None,
}


class TestOfflineQueue:
    """Unit tests for the OfflineQueue data structure."""

    def test_enqueue_stores_item(self):
        q = OfflineQueue()
        qid = q.enqueue("POST", "/actions", {"action_type": "x"})
        assert q.pending_count == 1
        assert qid.startswith("offline_")

    def test_drain_returns_all_and_empties(self):
        q = OfflineQueue()
        q.enqueue("POST", "/actions", {"a": 1})
        q.enqueue("POST", "/actions", {"a": 2})
        items = q.drain()
        assert len(items) == 2
        assert q.pending_count == 0

    def test_drain_empty_queue(self):
        q = OfflineQueue()
        items = q.drain()
        assert items == []

    def test_clear_drops_queue(self):
        q = OfflineQueue()
        q.enqueue("POST", "/actions", {"a": 1})
        q.enqueue("POST", "/actions", {"a": 2})
        q.clear()
        assert q.pending_count == 0

    def test_len_matches_pending_count(self):
        q = OfflineQueue()
        q.enqueue("POST", "/a", {})
        q.enqueue("POST", "/b", {})
        assert len(q) == 2
        assert len(q) == q.pending_count

    def test_multiple_items_fifo_order(self):
        q = OfflineQueue()
        q.enqueue("POST", "/first", {"order": 1})
        q.enqueue("POST", "/second", {"order": 2})
        q.enqueue("POST", "/third", {"order": 3})
        items = q.drain()
        assert items[0].path == "/first"
        assert items[1].path == "/second"
        assert items[2].path == "/third"


class TestOfflineModeClient:
    """Tests for Aira client in offline mode."""

    def test_offline_mode_post_queues_no_network(self):
        c = Aira(api_key="aira_live_test", base_url="http://test", offline=True)
        # Should NOT make any HTTP call — mock would fail if called
        result = c._post("/actions", {"action_type": "email_sent", "details": "Test"})
        assert result["_offline"] is True
        assert result["_queue_id"].startswith("offline_")
        assert c._queue.pending_count == 1
        c.close()

    def test_offline_mode_get_raises(self):
        c = Aira(api_key="aira_live_test", base_url="http://test", offline=True)
        with pytest.raises(AiraError) as exc:
            c.get_action("act-1")
        assert exc.value.code == "OFFLINE"
        c.close()

    def test_sync_flushes_queue(self):
        c = Aira(api_key="aira_live_test", base_url="http://test", offline=True)
        c._post("/actions", {"action_type": "email_sent", "details": "Test 1"})
        c._post("/actions", {"action_type": "email_sent", "details": "Test 2"})
        assert c._queue.pending_count == 2

        with patch.object(c._client, "request", return_value=_resp(RECEIPT, 201)):
            results = c.sync()
        assert len(results) == 2
        assert results[0]["action_id"] == "act-1"
        assert c._queue.pending_count == 0
        c.close()

    def test_non_offline_client_has_no_queue(self):
        c = Aira(api_key="aira_live_test", base_url="http://test")
        assert c._queue is None
        c.close()

    def test_sync_on_non_offline_raises(self):
        c = Aira(api_key="aira_live_test", base_url="http://test")
        with pytest.raises(ValueError, match="sync\\(\\) is only available in offline mode"):
            c.sync()
        c.close()

    def test_partial_failure_continues(self):
        c = Aira(api_key="aira_live_test", base_url="http://test", offline=True)
        c._post("/actions", {"action_type": "x", "details": "ok"})
        c._post("/actions", {"action_type": "y", "details": "fail"})
        c._post("/actions", {"action_type": "z", "details": "ok2"})

        responses = [
            _resp(RECEIPT, 201),
            _resp({"error": "Bad", "code": "BAD_REQUEST"}, 400),
            _resp(RECEIPT, 201),
        ]

        with patch.object(c._client, "request", side_effect=responses):
            results = c.sync()

        assert len(results) == 3
        assert results[0]["action_id"] == "act-1"
        assert results[1]["_error"] is True
        assert results[1]["_status"] == 400
        assert results[2]["action_id"] == "act-1"
        c.close()


class TestAsyncOfflineMode:
    """Tests for AsyncAira client in offline mode."""

    @pytest.mark.asyncio
    async def test_async_post_queues_when_offline(self):
        async with AsyncAira(api_key="aira_test_xxx", base_url="http://test", offline=True) as c:
            result = await c._post("/actions", {"action_type": "email_sent", "details": "Test offline"})
            assert result["_offline"] is True
            assert result["_queue_id"].startswith("offline_")
            assert c._queue.pending_count == 1

    @pytest.mark.asyncio
    async def test_async_get_raises_offline(self):
        async with AsyncAira(api_key="aira_test_xxx", base_url="http://test", offline=True) as c:
            with pytest.raises(AiraError) as exc:
                await c.list_actions()
            assert exc.value.code == "OFFLINE"

    @pytest.mark.asyncio
    async def test_async_sync_flushes_queue(self):
        c = AsyncAira(api_key="aira_test_xxx", base_url="http://test", offline=True)
        await c._post("/actions", {"action_type": "email_sent", "details": "Test 1"})
        await c._post("/actions", {"action_type": "email_sent", "details": "Test 2"})
        assert c._queue.pending_count == 2

        mock_resp = _resp(RECEIPT, 201)
        with patch.object(c._client, "request", new_callable=AsyncMock, return_value=mock_resp):
            results = await c.sync()
        assert len(results) == 2
        assert results[0]["action_id"] == "act-1"
        assert c._queue.pending_count == 0
        await c.close()

    @pytest.mark.asyncio
    async def test_async_queue_count(self):
        async with AsyncAira(api_key="aira_test_xxx", base_url="http://test", offline=True) as c:
            assert c._queue.pending_count == 0
            await c._post("/actions", {"action_type": "a", "details": "1"})
            assert c._queue.pending_count == 1
            await c._post("/actions", {"action_type": "b", "details": "2"})
            assert c._queue.pending_count == 2
            await c._post("/actions", {"action_type": "c", "details": "3"})
            assert c._queue.pending_count == 3
