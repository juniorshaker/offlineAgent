"""
tool_layer/tool_executor.py
Execute tool calls with safety checks (confirmation prompts, shell whitelist).
"""

from .tool_registry import ToolRegistry
from .tool_parser import parse_tool_calls, extract_text_without_tools, has_tool_calls

MAX_TOOL_ITERATIONS = 10


def _needs_confirmation(tool_name: str, config: dict, params: dict) -> bool:
    """Determine if this tool call needs user confirmation."""
    tools_cfg = config.get("tools", {})

    # Shell always needs confirmation if configured
    if tool_name == "shell":
        return tools_cfg.get("shell", {}).get("require_confirm", True)

    # File writes need confirmation if configured
    if tool_name in ("write_file",):
        return tools_cfg.get("file_write", {}).get("require_confirm", True)

    return False


def _user_confirm(tool_name: str, params: dict) -> bool:
    """Ask user to confirm a sensitive tool call."""
    params_str = ", ".join(f"{k}={repr(v)[:60]}" for k, v in params.items())
    print(f"\n  ⚠ Confirm tool: {tool_name}({params_str})")
    try:
        choice = input("  Execute? [Y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return choice in ("", "y", "yes")


def execute_tool_loop(
    llm_chat_fn,
    system_prompt: str,
    state,
    config: dict,
    registry: ToolRegistry,
    logger=None,
) -> str:
    """Run the tool execution loop.

    1. Send messages to LLM
    2. If output contains <tool_call> → execute → inject result → repeat
    3. If output is plain text → return it

    Args:
        llm_chat_fn: Function messages -> response_text
        system_prompt: Full system prompt
        state: StateManager instance
        config: Full config dict
        registry: ToolRegistry instance
        logger: AgentLogger instance (optional)

    Returns:
        Final text response from LLM.
    """
    iterations = 0
    final_text_parts: list[str] = []

    while iterations < MAX_TOOL_ITERATIONS:
        iterations += 1

        # Build messages for API call
        messages = state.get_history_for_api(system_prompt)

        # Call LLM
        response = llm_chat_fn(messages)
        if not response:
            return "[Error] No response from LLM."

        # Check for tool calls
        if not has_tool_calls(response):
            final_text_parts.append(response)
            break

        # Parse and execute tools
        tool_calls = parse_tool_calls(response)
        text_part = extract_text_without_tools(response)
        if text_part:
            final_text_parts.append(text_part)

        if not tool_calls:
            # Has tool_call tags but couldn't parse — treat as plain text
            final_text_parts.append(response)
            break

        for tc in tool_calls:
            # Check if tool exists
            tool_def = registry.get(tc.name)
            if not tool_def:
                state.add_tool_result(f"[Error] Unknown tool: {tc.name}. Available: {', '.join(registry.names())}")
                continue

            # Safety check
            if _needs_confirmation(tc.name, config, tc.params):
                if not _user_confirm(tc.name, tc.params):
                    state.add_tool_result(f"[Cancelled] User denied {tc.name}")
                    if logger:
                        logger.tool_call(tc.name, str(tc.params)[:100], False, "user denied")
                    continue

            # Execute
            try:
                result = registry.dispatch(tc.name, tc.params)
                result_str = str(result)
                state.add_tool_result(result_str)
                if logger:
                    logger.tool_call(tc.name, str(tc.params)[:100], True)
            except Exception as e:
                error_msg = f"[Error] Tool {tc.name} failed: {e}"
                state.add_tool_result(error_msg)
                if logger:
                    logger.tool_call(tc.name, str(tc.params)[:100], False, str(e)[:100])

    else:
        final_text_parts.append("[Note: Max tool iterations reached. Some operations may be incomplete.]")

    return "\n\n".join(p for p in final_text_parts if p)
