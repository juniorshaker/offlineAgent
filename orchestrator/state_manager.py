"""
orchestrator/state_manager.py
Dialogue state: message history, token estimation, budget dashboard.
"""


class TokenEstimator:
    """Zero-dependency token estimator.

    Uses rough character-based heuristics:
    - English / code: chars / 4
    - Chinese: chars / 1.5
    - Mixed: segment-then-estimate
    """

    @staticmethod
    def estimate(text: str) -> int:
        """Rough token count estimation."""
        if not text:
            return 0

        total = len(text)
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff' or '\u3400' <= c <= '\u4dbf')
        non_chinese = total - chinese_chars

        # Chinese: ~1.5 chars/token, English/code: ~4 chars/token
        return int(chinese_chars / 1.5 + non_chinese / 4.0)

    @staticmethod
    def estimate_messages(messages: list[dict]) -> int:
        """Estimate tokens for a list of messages."""
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total += TokenEstimator.estimate(content)
            elif isinstance(content, list):
                # Multi-modal content blocks
                for block in content:
                    if isinstance(block, dict):
                        total += TokenEstimator.estimate(block.get("text", ""))
            total += 4  # Message overhead
        return total + 2  # Reply priming


class StateManager:
    """Manages conversation state and token budget."""

    def __init__(self, max_history: int = 20, max_tokens: int = 8000):
        self.max_history = max_history
        self.max_tokens = max_tokens
        self.messages: list[dict] = []  # Full conversation messages
        self._tool_results: list[str] = []  # Accumulate tool results for this turn

    def add_user_message(self, content: str):
        self.messages.append({"role": "user", "content": content})
        self._tool_results = []

    def add_assistant_message(self, content: str):
        self.messages.append({"role": "assistant", "content": content})

    def add_tool_result(self, result: str):
        """Append a tool execution result as a system-level message."""
        self._tool_results.append(result)
        self.messages.append({"role": "system", "content": f"[Tool Result]\n{result}"})

    def get_last_user_message(self) -> str:
        for msg in reversed(self.messages):
            if msg["role"] == "user":
                return msg["content"]
        return ""

    def get_last_assistant_message(self) -> str:
        for msg in reversed(self.messages):
            if msg["role"] == "assistant":
                return msg["content"]
        return ""

    def get_recent_assistant_messages(self, count: int = 3) -> list[str]:
        """Get the last N assistant responses (for topic detection)."""
        results = []
        for msg in reversed(self.messages):
            if msg["role"] == "assistant":
                results.append(msg["content"])
                if len(results) >= count:
                    break
        return list(reversed(results))

    def estimate_total_tokens(self) -> int:
        """Estimate total tokens in current conversation."""
        # System prompt is typically ~2000 tokens, add message tokens
        return TokenEstimator.estimate_messages(self.messages)

    def usage_ratio(self) -> float:
        """Return current token usage as a fraction of max."""
        return self.estimate_total_tokens() / self.max_tokens

    def needs_compression(self, trigger_ratio: float = 0.7) -> bool:
        """Check if compression should be triggered."""
        return self.usage_ratio() > trigger_ratio

    def clear_history(self):
        """Clear conversation history but keep system prompt."""
        self.messages = [m for m in self.messages if m["role"] == "system"]
        self._tool_results = []

    def get_history_for_api(self, system_prompt: str) -> list[dict]:
        """Return messages ready for LLM API call: system prompt + conversation."""
        result = [{"role": "system", "content": system_prompt}]

        # Only include non-system, non-tool-result messages in the API call
        # (tool results are already merged as system messages)
        for msg in self.messages:
            result.append(msg)

        # Enforce max_history (count user/assistant pairs)
        user_assistant = [m for m in result if m["role"] in ("user", "assistant")]
        if len(user_assistant) > self.max_history * 2:
            # Keep system + last N user/assistant messages
            trimmed = [m for m in result if m["role"] == "system"]
            trimmed += user_assistant[-(self.max_history * 2):]
            result = trimmed

        return result

    def status_summary(self, system_prompt: str) -> dict:
        """Return a status snapshot."""
        tokens = TokenEstimator.estimate(system_prompt) + self.estimate_total_tokens()
        return {
            "tokens_estimate": tokens,
            "max_tokens": self.max_tokens,
            "usage_percent": round(tokens / self.max_tokens * 100, 1) if self.max_tokens else 0,
            "turns": len([m for m in self.messages if m["role"] == "user"]),
            "max_history": self.max_history,
        }
