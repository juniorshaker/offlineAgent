"""
metrics/logger.py
Structured logging with timestamps, turn tracking, and optional file output.
"""

import time
import json
from datetime import datetime
from pathlib import Path


class AgentLogger:
    """Lightweight structured logger for the agent session."""

    def __init__(self, log_dir: Path | None = None):
        self.turn_count = 0
        self.total_llm_calls = 0
        self.total_tokens_estimate = 0
        self.start_time = time.time()
        self.log_dir = log_dir
        self._session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._log_entries: list[dict] = []

    def turn_start(self, user_input: str):
        self.turn_count += 1
        self._log("turn_start", input_preview=user_input[:80])

    def llm_call(self, tokens_estimate: int, success: bool, error: str = ""):
        self.total_llm_calls += 1
        self.total_tokens_estimate += tokens_estimate
        self._log("llm_call", tokens=tokens_estimate, success=success, error=error)

    def tool_call(self, tool_name: str, params: str, success: bool, error: str = ""):
        self._log("tool_call", tool=tool_name, params=params[:100], success=success, error=error)

    def error_recovery(self, model: str, error_snippet: str, action: str):
        self._log("error_recovery", model=model, error=error_snippet[:100], action=action)

    def compression(self, before_tokens: int, after_tokens: int):
        self._log("compression", before=before_tokens, after=after_tokens, saved=before_tokens - after_tokens)

    def topic_shift(self, from_topic: str, to_topic: str, user_choice: str):
        self._log("topic_shift", from_topic=from_topic, to_topic=to_topic, choice=user_choice)

    def skill_injected(self, skill_name: str, body_length: int):
        self._log("skill_injected", skill=skill_name, body_len=body_length)

    def status(self) -> dict:
        """Return a status snapshot."""
        elapsed = time.time() - self.start_time
        return {
            "session": self._session_id,
            "turns": self.turn_count,
            "llm_calls": self.total_llm_calls,
            "tokens_estimate": self.total_tokens_estimate,
            "elapsed_seconds": int(elapsed),
        }

    def write_log_file(self):
        """Flush accumulated log entries to disk."""
        if not self.log_dir:
            return
        self.log_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.log_dir / f"session_{self._session_id}.jsonl"
        with open(log_path, "w", encoding="utf-8") as f:
            for entry in self._log_entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _log(self, event_type: str, **kwargs):
        entry = {
            "ts": datetime.now().isoformat(),
            "turn": self.turn_count,
            "event": event_type,
            **kwargs,
        }
        self._log_entries.append(entry)
