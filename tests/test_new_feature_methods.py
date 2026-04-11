"""Tests for the post-LangChain-RFC SDK methods.

Pins the contract for the SDK methods that wrap:
- Replay context (F10)
- Compliance bundles (PR #15)
- Drift detection (PR #16)
- Merkle settlement (PR #22)

Uses ``unittest.mock.patch`` against the internal ``_post`` / ``_get``
helpers, matching the pattern in ``test_client.py``.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from aira import Aira


@pytest.fixture
def aira():
    return Aira(api_key="aira_live_test", base_url="https://api.airaproof.com")


# ─── Replay context ──────────────────────────────────────────────────


def test_authorize_passes_replay_context(aira):
    expected_body = None

    def fake_post(path, body):
        nonlocal expected_body
        expected_body = body
        return {
            "action_id": "a1",
            "status": "authorized",
            "created_at": "2026-04-11T10:00:00Z",
            "request_id": "r1",
            "warnings": None,
        }

    with patch.object(aira, "_post", side_effect=fake_post):
        result = aira.authorize(
            action_type="tool_call",
            details="x",
            system_prompt_hash="sha256:" + "a" * 64,
            tool_inputs_hash="sha256:" + "b" * 64,
            model_params={"temperature": 0.0, "seed": 42},
            execution_env={"sdk_version": "2.0.1", "framework": "langchain"},
        )

    assert result.action_id == "a1"
    assert expected_body["system_prompt_hash"] == "sha256:" + "a" * 64
    assert expected_body["tool_inputs_hash"] == "sha256:" + "b" * 64
    assert expected_body["model_params"] == {"temperature": 0.0, "seed": 42}
    assert expected_body["execution_env"]["framework"] == "langchain"


def test_authorize_omits_unset_replay_context(aira):
    """When replay context fields aren't supplied they shouldn't appear in the body."""
    captured = None

    def fake_post(path, body):
        nonlocal captured
        captured = body
        return {
            "action_id": "a1", "status": "authorized",
            "created_at": "x", "request_id": "r", "warnings": None,
        }

    with patch.object(aira, "_post", side_effect=fake_post):
        aira.authorize(action_type="x", details="x")

    assert "system_prompt_hash" not in captured
    assert "model_params" not in captured


def test_get_replay_context(aira):
    expected = {"action_id": "a1", "system_prompt_hash": "sha256:abc", "model_params": {"temperature": 0.7}}
    with patch.object(aira, "_get", return_value=expected) as m:
        result = aira.get_replay_context("a1")
    m.assert_called_once_with("/actions/a1/replay-context")
    assert result == expected


# ─── Compliance bundles ──────────────────────────────────────────────


def test_create_compliance_bundle(aira):
    expected = {"id": "b1", "framework": "eu_ai_act_art12", "merkle_root": "abc"}
    with patch.object(aira, "_post", return_value=expected) as m:
        result = aira.create_compliance_bundle(
            framework="eu_ai_act_art12",
            period_start="2026-01-01T00:00:00Z",
            period_end="2026-04-01T00:00:00Z",
            title="Q1 2026",
        )
    m.assert_called_once()
    path, body = m.call_args[0]
    assert path == "/compliance/bundles"
    assert body["framework"] == "eu_ai_act_art12"
    assert body["title"] == "Q1 2026"
    assert result["id"] == "b1"


def test_list_compliance_bundles(aira):
    payload = {
        "data": [{"id": "b1"}, {"id": "b2"}],
        "pagination": {"page": 1, "per_page": 20, "total": 2, "has_more": False},
        "request_id": "r",
    }
    with patch.object(aira, "_get", return_value=payload) as m:
        result = aira.list_compliance_bundles(page=1, per_page=20)
    m.assert_called_once_with("/compliance/bundles?page=1&per_page=20")
    assert result.total == 2
    assert len(result.data) == 2


def test_get_compliance_bundle(aira):
    with patch.object(aira, "_get", return_value={"id": "b1"}) as m:
        result = aira.get_compliance_bundle("b1")
    m.assert_called_once_with("/compliance/bundles/b1")
    assert result["id"] == "b1"


def test_export_compliance_bundle(aira):
    expected = {
        "bundle_id": "b1",
        "merkle_root": "abc",
        "receipts": [],
        "signing": {"jwks_url": "https://api.airaproof.com/api/v1/.well-known/jwks.json"},
    }
    with patch.object(aira, "_get", return_value=expected) as m:
        result = aira.export_compliance_bundle("b1")
    m.assert_called_once_with("/compliance/bundles/b1/export")
    assert "merkle_root" in result
    assert "jwks_url" in result["signing"]


def test_get_bundle_inclusion_proof(aira):
    expected = {"bundle_id": "b1", "receipt_id": "r1", "leaf_hash": "h", "siblings": []}
    with patch.object(aira, "_get", return_value=expected) as m:
        result = aira.get_bundle_inclusion_proof("b1", "r1")
    m.assert_called_once_with("/compliance/bundles/b1/inclusion-proof/r1")
    assert result["receipt_id"] == "r1"


# ─── Drift detection ─────────────────────────────────────────────────


def test_get_drift_status(aira):
    expected = {"agent_id": "bot", "has_baseline": True, "kl_divergence": 0.12}
    with patch.object(aira, "_get", return_value=expected) as m:
        result = aira.get_drift_status("bot", lookback_hours=48)
    m.assert_called_once_with("/agents/bot/drift?lookback_hours=48")
    assert result["has_baseline"] is True


def test_compute_drift_baseline(aira):
    expected = {"id": "b1", "baseline_type": "production"}
    with patch.object(aira, "_post", return_value=expected) as m:
        result = aira.compute_drift_baseline(
            agent_id="bot",
            window_start="2026-01-01T00:00:00Z",
            window_end="2026-01-08T00:00:00Z",
        )
    m.assert_called_once()
    path, body = m.call_args[0]
    assert path == "/agents/bot/drift/baseline"
    assert body["window_start"] == "2026-01-01T00:00:00Z"
    assert result["baseline_type"] == "production"


def test_seed_synthetic_baseline(aira):
    expected = {"id": "b1", "baseline_type": "synthetic"}
    with patch.object(aira, "_post", return_value=expected) as m:
        result = aira.seed_synthetic_baseline(
            agent_id="bot",
            expected_distribution={"email": 0.7, "api": 0.3},
            expected_actions_per_day=50,
        )
    path, body = m.call_args[0]
    assert path == "/agents/bot/drift/baseline/synthetic"
    assert body["expected_distribution"] == {"email": 0.7, "api": 0.3}
    assert result["baseline_type"] == "synthetic"


def test_run_drift_check_no_drift(aira):
    with patch.object(aira, "_post", return_value=None) as m:
        result = aira.run_drift_check("bot")
    m.assert_called_once_with("/agents/bot/drift/check?lookback_hours=24", {})
    assert result is None


def test_run_drift_check_with_alert(aira):
    expected = {"id": "a1", "severity": "warning"}
    with patch.object(aira, "_post", return_value=expected):
        result = aira.run_drift_check("bot")
    assert result["severity"] == "warning"


def test_list_drift_alerts(aira):
    payload = {
        "data": [{"id": "a1"}],
        "pagination": {"page": 1, "per_page": 50, "total": 1, "has_more": False},
        "request_id": "r",
    }
    with patch.object(aira, "_get", return_value=payload) as m:
        result = aira.list_drift_alerts("bot", page=1, acknowledged=False)
    m.assert_called_once_with("/agents/bot/drift/alerts?page=1&per_page=50&acknowledged=false")
    assert result.total == 1


def test_acknowledge_drift_alert(aira):
    expected = {"id": "a1", "acknowledged_by": "ops@x.com"}
    with patch.object(aira, "_post", return_value=expected) as m:
        result = aira.acknowledge_drift_alert("bot", "a1")
    m.assert_called_once_with("/agents/bot/drift/alerts/a1/acknowledge", {})
    assert result["acknowledged_by"] == "ops@x.com"


# ─── Merkle settlement ───────────────────────────────────────────────


def test_create_settlement(aira):
    expected = {"id": "s1", "merkle_root": "abc", "receipt_count": 100}
    with patch.object(aira, "_post", return_value=expected) as m:
        result = aira.create_settlement()
    m.assert_called_once_with("/settlements", {})
    assert result["receipt_count"] == 100


def test_create_settlement_noop(aira):
    with patch.object(aira, "_post", return_value=None):
        result = aira.create_settlement()
    assert result is None


def test_list_settlements(aira):
    payload = {
        "data": [{"id": "s1"}],
        "pagination": {"page": 1, "per_page": 20, "total": 1, "has_more": False},
        "request_id": "r",
    }
    with patch.object(aira, "_get", return_value=payload) as m:
        result = aira.list_settlements()
    m.assert_called_once_with("/settlements?page=1&per_page=20")
    assert result.total == 1


def test_get_settlement(aira):
    with patch.object(aira, "_get", return_value={"id": "s1"}) as m:
        result = aira.get_settlement("s1")
    m.assert_called_once_with("/settlements/s1")
    assert result["id"] == "s1"


def test_get_settlement_inclusion_proof(aira):
    expected = {
        "settlement_id": "s1",
        "receipt_id": "r1",
        "merkle_root": "abc",
        "leaf_hash": "h",
        "index": 5,
        "leaf_count": 100,
        "siblings": ["a", "b", "c"],
    }
    with patch.object(aira, "_get", return_value=expected) as m:
        result = aira.get_settlement_inclusion_proof("r1")
    m.assert_called_once_with("/settlements/inclusion-proof/r1")
    assert result["leaf_count"] == 100
    assert len(result["siblings"]) == 3
