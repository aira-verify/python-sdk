"""Tests for the LangChain callback handler — two-step authorize + notarize flow."""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock


# Mock langchain_core at module level so tests run without installing it
_mock_langchain_core = types.ModuleType("langchain_core")
_mock_callbacks = types.ModuleType("langchain_core.callbacks")
_mock_callbacks_base = types.ModuleType("langchain_core.callbacks.base")


class _MockBaseCallbackHandler:
    """Minimal stand-in for langchain_core BaseCallbackHandler."""
    pass


_mock_callbacks_base.BaseCallbackHandler = _MockBaseCallbackHandler
_mock_callbacks.base = _mock_callbacks_base
_mock_langchain_core.callbacks = _mock_callbacks

sys.modules["langchain_core"] = _mock_langchain_core
sys.modules["langchain_core.callbacks"] = _mock_callbacks
sys.modules["langchain_core.callbacks.base"] = _mock_callbacks_base

# Now we can import the module under test
from aira.extras.langchain import AiraCallbackHandler, AiraToolDenied


def _auth(status: str = "authorized", action_id: str = "act-1"):
    a = MagicMock()
    a.status = status
    a.action_id = action_id
    return a


class TestAiraCallbackHandler(unittest.TestCase):
    """Tests for AiraCallbackHandler."""

    def _make_handler(self, **kwargs):
        client = MagicMock()
        client.authorize.return_value = _auth("authorized")
        defaults = {"client": client, "agent_id": "test-agent"}
        defaults.update(kwargs)
        handler = AiraCallbackHandler(**defaults)
        return handler, client

    # 1. on_tool_start calls authorize BEFORE the tool runs
    def test_on_tool_start_calls_authorize(self):
        handler, client = self._make_handler()
        handler.on_tool_start({"name": "search"}, "query input", run_id="r1")
        client.authorize.assert_called_once()
        call_kwargs = client.authorize.call_args[1]
        self.assertEqual(call_kwargs["action_type"], "tool_call")
        self.assertEqual(call_kwargs["agent_id"], "test-agent")

    # 2. on_tool_end calls notarize with the action_id from on_tool_start
    def test_on_tool_end_notarizes_completed(self):
        handler, client = self._make_handler()
        handler.on_tool_start({"name": "search"}, "q", run_id="r1")
        handler.on_tool_end("some output", run_id="r1", name="search")
        client.notarize.assert_called_once()
        kw = client.notarize.call_args[1]
        self.assertEqual(kw["action_id"], "act-1")
        self.assertEqual(kw["outcome"], "completed")

    # 3. on_tool_error notarizes with outcome=failed
    def test_on_tool_error_notarizes_failed(self):
        handler, client = self._make_handler()
        handler.on_tool_start({"name": "search"}, "q", run_id="r1")
        handler.on_tool_error(RuntimeError("boom"), run_id="r1", name="search")
        client.notarize.assert_called_once()
        kw = client.notarize.call_args[1]
        self.assertEqual(kw["outcome"], "failed")
        self.assertIn("boom", kw["outcome_details"])

    # 4. POLICY_DENIED on authorize raises AiraToolDenied → abort
    def test_policy_denied_raises_tool_denied(self):
        handler, client = self._make_handler()
        err = Exception("denied")
        err.code = "POLICY_DENIED"
        err.message = "Blocked by policy"
        client.authorize.side_effect = err
        with self.assertRaises(AiraToolDenied) as ctx:
            handler.on_tool_start({"name": "search"}, "q", run_id="r1")
        self.assertEqual(ctx.exception.code, "POLICY_DENIED")
        client.notarize.assert_not_called()

    # 5. pending_approval blocks tool execution
    def test_pending_approval_raises(self):
        handler, client = self._make_handler()
        client.authorize.return_value = _auth("pending_approval")
        with self.assertRaises(AiraToolDenied) as ctx:
            handler.on_tool_start({"name": "search"}, "q", run_id="r1")
        self.assertEqual(ctx.exception.code, "PENDING_APPROVAL")
        client.notarize.assert_not_called()

    # 6. custom action_types override defaults
    def test_custom_action_types_override_defaults(self):
        handler, client = self._make_handler(action_types={"tool": "custom_tool"})
        handler.on_tool_start({"name": "calc"}, "q", run_id="r1")
        kw = client.authorize.call_args[1]
        self.assertEqual(kw["action_type"], "custom_tool")

    # 7. notarize failure after authorize is non-blocking
    def test_notarize_failure_is_non_blocking(self):
        handler, client = self._make_handler()
        client.notarize.side_effect = RuntimeError("API down")
        handler.on_tool_start({"name": "search"}, "q", run_id="r1")
        # Should not raise
        handler.on_tool_end("output", run_id="r1", name="search")

    # 8. agent_id / model_id passed through to authorize
    def test_agent_model_id_passed_through(self):
        handler, client = self._make_handler(model_id="gpt-4")
        handler.on_tool_start({"name": "tool1"}, "q", run_id="r1")
        kw = client.authorize.call_args[1]
        self.assertEqual(kw["agent_id"], "test-agent")
        self.assertEqual(kw["model_id"], "gpt-4")

    # 9. on_chain_end runs audit-only authorize + notarize
    def test_on_chain_end_audit_only(self):
        handler, client = self._make_handler()
        handler.on_chain_end({"output": "hello"})
        client.authorize.assert_called_once()
        kw = client.authorize.call_args[1]
        self.assertEqual(kw["action_type"], "chain_completed")
        client.notarize.assert_called_once()

    # 10. on_llm_end runs audit-only authorize + notarize
    def test_on_llm_end_audit_only(self):
        handler, client = self._make_handler()
        response = MagicMock()
        response.generations = [["gen1"], ["gen2"]]
        handler.on_llm_end(response)
        client.authorize.assert_called_once()
        kw = client.authorize.call_args[1]
        self.assertEqual(kw["action_type"], "llm_completion")
        client.notarize.assert_called_once()

    # 11. on_chain_end non-blocking on authorize failure
    def test_on_chain_end_non_blocking(self):
        handler, client = self._make_handler()
        client.authorize.side_effect = RuntimeError("network")
        # Should not raise
        handler.on_chain_end({"output": "x"})

    # 12. import error message is clear when langchain not installed
    def test_import_error_message_when_langchain_missing(self):
        saved = {}
        for key in list(sys.modules):
            if key.startswith("langchain_core"):
                saved[key] = sys.modules.pop(key)
        saved_aira = sys.modules.pop("aira.extras.langchain", None)

        import builtins
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "langchain_core.callbacks.base" or name == "langchain_core":
                raise ImportError("No module named 'langchain_core'")
            return real_import(name, *args, **kwargs)

        builtins.__import__ = fake_import
        try:
            with self.assertRaises(ImportError) as ctx:
                import importlib
                importlib.import_module("aira.extras.langchain")
            self.assertIn("pip install aira-sdk[langchain]", str(ctx.exception))
        finally:
            builtins.__import__ = real_import
            sys.modules.update(saved)
            if saved_aira:
                sys.modules["aira.extras.langchain"] = saved_aira

    # 13. raw tool output is not sent to authorize
    def test_no_raw_output_in_authorize(self):
        handler, client = self._make_handler()
        handler.on_tool_start({"name": "search"}, "super_secret_input_123", run_id="r1")
        kw = client.authorize.call_args[1]
        self.assertNotIn("super_secret_input_123", kw["details"])

    # 14. inflight map cleaned up after notarize
    def test_inflight_cleaned_up_after_end(self):
        handler, client = self._make_handler()
        handler.on_tool_start({"name": "search"}, "q", run_id="r1")
        self.assertIn("r1", handler._inflight)
        handler.on_tool_end("output", run_id="r1", name="search")
        self.assertNotIn("r1", handler._inflight)


if __name__ == "__main__":
    unittest.main()
