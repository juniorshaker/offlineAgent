"""
tool_layer/tool_executor.py
Execute tool calls with safety checks (confirmation prompts, shell whitelist).
"""

import threading

from .tool_registry import ToolRegistry
from .tool_parser import parse_tool_calls, extract_text_without_tools, has_tool_calls

MAX_TOOL_ITERATIONS = 10


def _llm_call_with_timeout(llm_fn, messages, timeout_sec: int) -> str:
    """Call LLM with a timeout. Returns error string on timeout."""
    result_container = {"response": None, "error": None, "done": False}

    def _call():
        try:
            result_container["response"] = llm_fn(messages)
        except Exception as e:
            result_container["error"] = str(e)
        finally:
            result_container["done"] = True

    thread = threading.Thread(target=_call, daemon=True)
    thread.start()
    thread.join(timeout=timeout_sec)

    if not result_container["done"]:
        return f"[Timeout] LLM did not respond within {timeout_sec}s."

    if result_container["error"]:
        return f"[LLM Error] {result_container['error']}"

    return result_container["response"] or ""


def _needs_confirmation(tool_name: str, config: dict, params: dict) -> bool:
    """Determine if this tool call needs user confirmation."""
    tools_cfg = config.get("tools", {})

    if tool_name == "shell":
        return tools_cfg.get("shell", {}).get("require_confirm", True)

    if tool_name in ("write_file",):
        return tools_cfg.get("file_write", {}).get("require_confirm", True)

    return False


def _user_confirm(tool_name: str, params: dict) -> bool:
    """Ask user to confirm a sensitive tool call."""
    params_str = ", ".join(f"{k}={repr(v)[:60]}" for k, v in params.items())
    print(f"\n  [Confirm] tool: {tool_name}({params_str})")
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
    llm_timeout = config.get("llm", {}).get("timeout", 60)

    while iterations < MAX_TOOL_ITERATIONS:
        iterations += 1

        messages = state.get_history_for_api(system_prompt)

        # Call LLM with timeout
        response = _llm_call_with_timeout(llm_chat_fn, messages, llm_timeout)

        if not response:
            return "[Error] No response from LLM."

        if response.startswith("[Timeout]") or response.startswith("[LLM Error]"):
            if logger:
                logger.error_recovery("tool_loop", response[:100], "return_error")
            return response

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
            final_text_parts.append(response)
            break

        for tc in tool_calls:
            tool_def = registry.get(tc.name)
            if not tool_def:
                state.add_tool_result(
                    f"[Error] Unknown tool: {tc.name}. Available: {', '.join(registry.names())}"
                )
                continue

            if _needs_confirmation(tc.name, config, tc.params):
                if not _user_confirm(tc.name, tc.params):
                    state.add_tool_result(f"[Cancelled] User denied {tc.name}")
                    if logger:
                        logger.tool_call(tc.name, str(tc.params)[:100], False, "user denied")
                    continue

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
        final_text_parts.append(
            "[Note: Max tool iterations reached. Some operations may be incomplete.]"
        )

    return "\n\n".join(p for p in final_text_parts if p)
