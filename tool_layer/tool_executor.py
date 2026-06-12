"""
tool_layer/tool_executor.py
Execute tool calls with safety checks (confirmation prompts, shell whitelist).
Now with token budget control and cycle detection (v6).
"""

import threading

from .tool_registry import ToolRegistry
from .tool_parser import parse_tool_calls_full, extract_text_without_tools, has_tool_calls


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
    """Run the tool execution loop with token budget control and cycle detection.

    1. Send messages to LLM
    2. If output contains <tool_call> -> execute -> inject result -> repeat
    3. Token budget check: stop and force final response when usage >= budget_ratio
    4. Cycle detection: break loops where same tool called 3x with same params
    5. Max iterations safety valve (default 50)

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

    agent_cfg = config.get("agent", {})
    budget_ratio = agent_cfg.get("tool_budget_ratio", 0.9)
    cycle_detection = agent_cfg.get("cycle_detection", True)
    max_iterations = agent_cfg.get("max_tool_iterations", 50)
    recent_tool_calls: list[tuple[str, str]] = []

    while True:
        # --- Token budget check ---
        usage = state.usage_ratio()
        if usage >= budget_ratio:
            if logger:
                logger.error_recovery(
                    "token_budget",
                    "{:.1%} >= {:.1%}".format(usage, budget_ratio),
                    "force_final",
                )
            force_msg = (
                "[SYSTEM] Token budget nearly exhausted "
                + "({}/{}). ".format(state.estimate_total_tokens(), state.max_tokens)
                + "Respond DIRECTLY to the user NOW. Do NOT make any more tool calls. "
                + "Summarize findings and provide your best answer."
            )
            state.messages.append({"role": "user", "content": force_msg})
            messages = state.get_history_for_api(system_prompt)
            response = _llm_call_with_timeout(llm_chat_fn, messages, llm_timeout)
            if (
                response
                and not response.startswith("[Timeout]")
                and not response.startswith("[LLM Error]")
            ):
                final_text_parts.append(response)
            else:
                final_text_parts.append(
                    "[Note: Token budget reached. Unable to generate final response.]"
                )
            break

        iterations += 1

        # --- Safety valve: max iterations ---
        if iterations >= max_iterations:
            if logger:
                logger.error_recovery(
                    "max_iterations",
                    "{} >= {}".format(iterations, max_iterations),
                    "force_final",
                )
            force_msg = (
                "[SYSTEM] Maximum tool iterations ({}) reached. ".format(max_iterations)
                + "Respond DIRECTLY to the user NOW. Do NOT make any more tool calls. "
            )
            state.messages.append({"role": "user", "content": force_msg})
            messages = state.get_history_for_api(system_prompt)
            response = _llm_call_with_timeout(llm_chat_fn, messages, llm_timeout)
            if (
                response
                and not response.startswith("[Timeout]")
                and not response.startswith("[LLM Error]")
            ):
                final_text_parts.append(response)
            break

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
        tool_calls = parse_tool_calls_full(response)
        text_part = extract_text_without_tools(response)
        if text_part:
            final_text_parts.append(text_part)

        if not tool_calls:
            final_text_parts.append(response)
            break

        for tc in tool_calls:
            # --- Cycle detection ---
            if cycle_detection:
                first_param = list(tc.params.values())[0] if tc.params else ""
                first_param_str = str(first_param)[:80]
                recent_tool_calls.append((tc.name, first_param_str))
                if len(recent_tool_calls) > 3:
                    recent_tool_calls.pop(0)
                if len(recent_tool_calls) >= 3:
                    a, b, c = (
                        recent_tool_calls[0],
                        recent_tool_calls[1],
                        recent_tool_calls[2],
                    )
                    if a == b == c:
                        if logger:
                            logger.error_recovery(
                                "cycle_detection",
                                "{}({}) x3".format(tc.name, first_param_str),
                                "inject_warning",
                            )
                        cycle_warning = (
                            "[SYSTEM] You have called {} with the same parameters 3 times. ".format(
                                tc.name
                            )
                            + "Stop repeating. Either read actual file contents, switch to a different "
                            + "tool, or provide your analysis now."
                        )
                        state.messages.append(
                            {"role": "user", "content": cycle_warning}
                        )
                        recent_tool_calls.clear()
                        break

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
                        logger.tool_call(
                            tc.name, str(tc.params)[:100], False, "user denied"
                        )
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
                    logger.tool_call(
                        tc.name, str(tc.params)[:100], False, str(e)[:100]
                    )

    return "\n\n".join(p for p in final_text_parts if p)
