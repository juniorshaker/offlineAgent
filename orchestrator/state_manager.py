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
        self.messages: list[dict] = []
        self._tool_results: list[str] = []

    def add_user_message(self, content: str):
        self.messages.append({"role": "user", "content": content})
        self._tool_results = []

    def add_assistant_message(self, content: str):
        self.messages.append({"role": "assistant", "content": content})

    def add_tool_result(self, result: str):
        """Append a tool execution result.

        Uses 'user' role (not 'system') to avoid confusing LLMs that only
        expect a single system message at the beginning of the conversation.
        """
        self._tool_results.append(result)
        self.messages.append({"role": "user", "content": f"[Tool Result]\n{result}"})

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
        results = []
        for msg in reversed(self.messages):
            if msg["role"] == "assistant":
                results.append(msg["content"])
                if len(results) >= count:
                    break
        return list(reversed(results))

    def estimate_total_tokens(self) -> int:
        return TokenEstimator.estimate_messages(self.messages)

    def usage_ratio(self) -> float:
        return self.estimate_total_tokens() / self.max_tokens

    def needs_compression(self, trigger_ratio: float = 0.7) -> bool:
        return self.usage_ratio() > trigger_ratio

    def clear_history(self):
        """Clear conversation history — wipe all messages."""
        self.messages = []
        self._tool_results = []

    def get_history_for_api(self, system_prompt: str) -> list[dict]:
        """Return messages ready for LLM API call.

        Returns: [system_prompt] + [all non-system messages from state]
        Skips any 'system' role messages in state to avoid mid-conversation
        system messages that confuse some LLM APIs.
        """
        result = [{"role": "system", "content": system_prompt}]

        for msg in self.messages:
            # Skip old system messages — we supply our own at the top
            if msg["role"] == "system":
                continue
            result.append(msg)

        # Enforce max_history limit on user/assistant pairs
        user_assistant = [m for m in result if m["role"] in ("user", "assistant")]
        if len(user_assistant) > self.max_history * 2:
            trimmed = [result[0]]  # Keep system prompt
            trimmed += user_assistant[-(self.max_history * 2):]
            result = trimmed

        return result

    def status_summary(self, system_prompt: str) -> dict:
        tokens = TokenEstimator.estimate(system_prompt) + self.estimate_total_tokens()
        return {
            "tokens_estimate": tokens,
            "max_tokens": self.max_tokens,
            "usage_percent": round(tokens / self.max_tokens * 100, 1) if self.max_tokens else 0,
            "turns": len([m for m in self.messages if m["role"] == "user"]),
            "max_history": self.max_history,
        }
