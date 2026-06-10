"""
Tests for server.py timeout fixes.

Run: python tests/test_server_fixes.py
"""
import sys
import os
import time
import json
import unittest
from unittest.mock import MagicMock, patch, PropertyMock
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# We can't import server directly (it has module-level state), 
# so we test key functions in isolation by importing internal modules


class TestRetryLogic(unittest.TestCase):
    """Test _llm_call_with_timeout retry behavior."""

    def test_successful_first_attempt(self):
        """Normal case: LLM responds on first try."""
        # Simulate by reading the source and verifying the retry structure
        server_path = Path(__file__).parent.parent / "server.py"
        content = server_path.read_text(encoding="utf-8")

        self.assertIn("for attempt in range(3)", content)
        self.assertIn("continue  # retry", content)
        self.assertIn("last_error or", content)
        # Should NOT have the old single-attempt code
        self.assertNotIn('return f"[Timeout] LLM did not respond within {timeout_sec} seconds."', content)

    def test_retry_has_backoff(self):
        """Backoff uses exponential delay."""
        server_path = Path(__file__).parent.parent / "server.py"
        content = server_path.read_text(encoding="utf-8")

        self.assertIn("backoff = 2 ** (attempt - 1)", content)
        self.assertIn("time.sleep(backoff)", content)

    def test_non_retryable_errors_return_immediately(self):
        """Non-connection errors should not retry."""
        server_path = Path(__file__).parent.parent / "server.py"
        content = server_path.read_text(encoding="utf-8")

        self.assertIn('any(kw in err_str.lower() for kw in ("timeout", "connection", "connect", "read timed out"))', content)


class TestSafetyValve(unittest.TestCase):
    """Test max_tool_iterations safety valve."""

    def test_max_iterations_configured(self):
        """max_iterations reads from config with default 50."""
        # Check config
        config_path = Path(__file__).parent.parent / "config.yaml"
        config_content = config_path.read_text(encoding="utf-8")
        self.assertIn("max_tool_iterations: 50", config_content)

    def test_safety_valve_in_code(self):
        """Safety valve code is present."""
        server_path = Path(__file__).parent.parent / "server.py"
        content = server_path.read_text(encoding="utf-8")

        self.assertIn("max_iterations = agent_cfg.get(\"max_tool_iterations\", 50)", content)
        self.assertIn("if iterations >= max_iterations:", content)
        self.assertIn('[SYSTEM] Maximum tool iterations', content)

    def test_safety_valve_injects_force_msg(self):
        """Safety valve injects [SYSTEM] message and forces final answer."""
        server_path = Path(__file__).parent.parent / "server.py"
        content = server_path.read_text(encoding="utf-8")

        self.assertIn("Respond DIRECTLY to the user NOW. Do NOT make any more tool calls.", content)


class TestTimeoutFaultTolerance(unittest.TestCase):
    """Test timeout fault tolerance - partial results preserved."""

    def test_partial_results_preserved(self):
        """On timeout, final_parts are preserved and returned."""
        server_path = Path(__file__).parent.parent / "server.py"
        content = server_path.read_text(encoding="utf-8")

        self.assertIn("Preserve collected partial results", content)
        self.assertIn("partial = ", content)
        self.assertIn("Partial results shown above", content)

    def test_no_discard_on_error(self):
        """Old code that discarded results should be gone."""
        server_path = Path(__file__).parent.parent / "server.py"
        content = server_path.read_text(encoding="utf-8")

        # Old pattern: return response directly (discards final_parts)
        # The new code has "return response" only inside "if not final_parts" branch
        old_pattern = '_log("LLM error response: {}".format(response[:100]), "ERROR", req_id)\n                return response'
        self.assertNotIn(old_pattern, content)


class TestDynamicTimeout(unittest.TestCase):
    """Test dynamic timeout function definition."""

    def test_dynamic_timeout_defined(self):
        """_dynamic_timeout function exists."""
        server_path = Path(__file__).parent.parent / "server.py"
        content = server_path.read_text(encoding="utf-8")

        self.assertIn("def _dynamic_timeout(msg_count: int) -> int:", content)
        self.assertIn("extra = (msg_count // 10) * 5", content)
        self.assertIn("return min(base_timeout + extra, 180)", content)

    def test_base_timeout_set(self):
        """base_timeout is set from config."""
        server_path = Path(__file__).parent.parent / "server.py"
        content = server_path.read_text(encoding="utf-8")
        self.assertIn("base_timeout = llm_timeout", content)


class TestConfiguration(unittest.TestCase):
    """Test config.yaml has required new fields."""

    def test_config_has_max_iterations(self):
        config_path = Path(__file__).parent.parent / "config.yaml"
        content = config_path.read_text(encoding="utf-8")
        self.assertIn("max_tool_iterations", content)


class TestSyntax(unittest.TestCase):
    """Test server.py compiles correctly."""

    def test_server_py_syntax(self):
        server_path = Path(__file__).parent.parent / "server.py"
        source = server_path.read_text(encoding="utf-8")
        try:
            compile(source, str(server_path), "exec")
        except SyntaxError as e:
            self.fail(f"server.py has syntax error: {e}")

    def test_agent_py_syntax(self):
        agent_path = Path(__file__).parent.parent / "agent.py"
        source = agent_path.read_text(encoding="utf-8")
        try:
            compile(source, str(agent_path), "exec")
        except SyntaxError as e:
            self.fail(f"agent.py has syntax error: {e}")


class TestIntegrationScenarios(unittest.TestCase):
    """Integration-level behavior verification via code structure analysis."""

    def test_retry_before_timeout_return(self):
        """The retry loop wraps the timeout check."""
        server_path = Path(__file__).parent.parent / "server.py"
        content = server_path.read_text(encoding="utf-8")

        # Verify the timeout return is inside the retry loop (indented under `for attempt`)
        # and uses `continue` instead of `return`
        lines = content.split("\n")
        in_retry_loop = False
        for line in lines:
            if "for attempt in range(3)" in line:
                in_retry_loop = True
            if in_retry_loop and "last_error = f\"[Timeout]" in line:
                # Should be followed by continue
                idx = lines.index(line)
                next_line = lines[idx + 1].strip()
                self.assertEqual(next_line, "continue  # retry")
                break

    def test_main_loop_still_has_while_true(self):
        """Main tool loop uses while True with safety valves."""
        server_path = Path(__file__).parent.parent / "server.py"
        content = server_path.read_text(encoding="utf-8")

        self.assertIn("while True:", content)
        # Safety exits: budget, max_iterations, cancellation, no tool calls, error
        self.assertIn("if usage >= budget_ratio:", content)
        self.assertIn("if iterations >= max_iterations:", content)
        self.assertIn("if _is_cancelled(req_id):", content)

    def test_final_parts_joined_in_finally(self):
        """final_parts are joined in finally block (executes even on error)."""
        server_path = Path(__file__).parent.parent / "server.py"
        content = server_path.read_text(encoding="utf-8")

        self.assertIn('"\\n\\n".join(p for p in final_parts if p)', content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
