"""
orchestrator/topic_guard.py
Detect topic shifts and ask user whether to start a fresh conversation.
"""

from .state_manager import StateManager, TokenEstimator

TOPIC_CHECK_PROMPT = """You are a topic shift detector. Compare the recent conversation topic with the new user message.

Recent topic context:
{context}

New user message:
"{user_input}"

Is the new message about the SAME topic as the recent conversation, or a clearly DIFFERENT topic?

Answer with ONLY one word: SAME or DIFFERENT."""


def detect_topic_shift(
    state: StateManager,
    user_input: str,
    llm_chat_fn,
) -> str | None:
    """Check if the user's new input represents a topic shift.

    Args:
        state: Current conversation state.
        user_input: The new user message.
        llm_chat_fn: Function to call LLM: llm_chat_fn(messages) -> str.

    Returns:
        "SAME" or "DIFFERENT", or None if detection fails.
    """
    # Need at least some conversation history to compare against
    recent = state.get_recent_assistant_messages(count=2)
    if not recent:
        return "SAME"  # First turn, no history to compare

    # Build a short context from recent assistant messages
    context_text = " ".join(r[:200] for r in recent)[:500]

    prompt = TOPIC_CHECK_PROMPT.format(context=context_text, user_input=user_input[:300])

    detection_messages = [
        {"role": "user", "content": prompt},
    ]

    try:
        result = llm_chat_fn(detection_messages).strip().upper()
        if "DIFFERENT" in result:
            return "DIFFERENT"
        return "SAME"
    except Exception:
        return "SAME"  # On failure, default to SAME (don't interrupt)


def ask_user_new_conversation(from_topic: str, to_topic: str) -> str:
    """Ask user if they want to start a new conversation.

    Returns: 'Y' (new), 'N' (continue), 'S' (skip for this session).
    """
    print()
    print(f"  ⚠  Topic shift detected:")
    print(f"     From: {from_topic[:60]}")
    print(f"     To:   {to_topic[:60]}")
    print()

    try:
        choice = input("  [Y] Start fresh conversation  [N] Continue  [S] Skip & don't ask again: ").strip().upper()
    except (EOFError, KeyboardInterrupt):
        return "N"

    if choice in ("Y", "N", "S"):
        return choice
    return "N"
