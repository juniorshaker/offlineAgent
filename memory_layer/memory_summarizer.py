"""
memory_layer/memory_summarizer.py
Generate conversation summaries on exit and persist to memory.
"""

from .memory_store import MemoryStore

SUMMARIZE_PROMPT = """Summarize the following conversation in one or two sentences in Chinese. Focus on:
- What the user was trying to accomplish
- Key decisions or conclusions reached
- Any code or tools used

Conversation:
{history}

Summary (1-2 sentences):"""


def summarize_conversation(history: list[dict], llm_chat_fn) -> str | None:
    """Generate a summary of the conversation.

    Args:
        history: List of message dicts from the conversation.
        llm_chat_fn: Function to call LLM.

    Returns:
        Summary string or None if summarization fails.
    """
    # Build a condensed text of the conversation
    lines = []
    for msg in history:
        role = msg.get("role", "?")
        content = msg.get("content", "")
        if isinstance(content, str):
            content = content[:300]
        lines.append(f"[{role}]: {content}")

    if len(lines) < 2:
        return None

    history_text = "\n".join(lines[-20:])  # Last 20 messages
    prompt = SUMMARIZE_PROMPT.format(history=history_text)

    try:
        summary_messages = [
            {"role": "user", "content": prompt},
        ]
        result = llm_chat_fn(summary_messages)
        if result and len(result) > 5:
            return result.strip()
    except Exception:
        pass

    return None
