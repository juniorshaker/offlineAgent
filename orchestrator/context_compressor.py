"""
orchestrator/context_compressor.py
Compress old conversation turns using LLM summarization.
When token usage exceeds trigger_ratio, the oldest N turns are
replaced with a concise summary, preserving recent turns verbatim.
"""

from .state_manager import StateManager


def _build_compression_prompt(old_messages: list[dict]) -> str:
    """Build a prompt asking the LLM to summarize old messages."""
    dialogue = []
    for m in old_messages:
        role = m["role"]
        content = m.get("content", "")
        if isinstance(content, str):
            content = content[:500]  # Truncate per-message for the summarization prompt
        dialogue.append(f"[{role}]: {content}")

    dialogue_text = "\n".join(dialogue)

    return f"""Summarize the following conversation in 200 characters or fewer, preserving key decisions, code patterns, and facts. Output only the summary text, no preamble.

Conversation:
{dialogue_text}

Summary:"""


def compress_history(
    state: StateManager,
    system_prompt: str,
    llm_chat_fn,
    keep_recent: int = 2,
) -> bool:
    """Attempt to compress conversation history.

    Args:
        state: The StateManager instance.
        system_prompt: The current system prompt.
        llm_chat_fn: Async function to call LLM: llm_chat_fn(messages) -> str.
        keep_recent: Number of recent turns to preserve verbatim.

    Returns:
        True if compression was performed.
    """
    messages = state.messages

    # Identify user/assistant pairs
    pairs = []
    i = 0
    while i < len(messages):
        if messages[i]["role"] == "user":
            user_msg = messages[i]
            assistant_msg = None
            if i + 1 < len(messages) and messages[i + 1]["role"] == "assistant":
                assistant_msg = messages[i + 1]
                i += 2
            else:
                i += 1
            pairs.append((user_msg, assistant_msg))
        else:
            i += 1

    if len(pairs) <= keep_recent + 2:
        return False  # Not enough to compress

    # Keep recent pairs, compress the rest
    to_compress = pairs[:-keep_recent]
    recent = pairs[-keep_recent:]

    old_messages = []
    for user_msg, assistant_msg in to_compress:
        old_messages.append(user_msg)
        if assistant_msg:
            old_messages.append(assistant_msg)

    if not old_messages:
        return False

    # Build summarization prompt and call LLM
    summary_prompt = _build_compression_prompt(old_messages)

    try:
        summary_messages = [
            {"role": "system", "content": "You are a precise conversation summarizer. Output only the summary."},
            {"role": "user", "content": summary_prompt},
        ]
        summary = llm_chat_fn(summary_messages)
        if not summary:
            return False
    except Exception:
        return False

    # Use 'user' role for summary since get_history_for_api skips system messages
    new_messages = [{"role": "user", "content": f"[Conversation History Summary]\n{summary}"}]
    for user_msg, assistant_msg in recent:
        new_messages.append(user_msg)
        if assistant_msg:
            new_messages.append(assistant_msg)

    state.messages = new_messages
    return True
