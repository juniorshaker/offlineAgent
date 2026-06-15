#!/usr/bin/env python3
"""
server.py - OfflineAgent Web Server

Single-file HTTP server with SSE streaming for the OfflineAgent frontend.
"""
import http.server
import json as _json
import os
import re
import sys
import time
import uuid
import traceback
import threading
import signal
import urllib.parse
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# -- Set up path --
_AGENT_DIR = Path(__file__).resolve().parent
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))
_PARENT_DIR = _AGENT_DIR.parent
if str(_PARENT_DIR) not in sys.path:
    sys.path.insert(0, str(_PARENT_DIR))

# -- Imports --
from Offlineagent.vendor import requests
from Offlineagent.prompt_layer.system_prompt import build_system_prompt
from Offlineagent.prompt_layer.skill_loader import load_all_skills, match_skills, get_skill_body
from Offlineagent.orchestrator.state_manager import StateManager
from Offlineagent.orchestrator.context_compressor import compress_history
from Offlineagent.orchestrator.error_recovery import check_before_send, repair_after_error
from Offlineagent.tool_layer.tool_registry import ToolRegistry
from Offlineagent.tool_layer.tool_parser import parse_tool_calls_full, has_tool_calls, extract_text_without_tools
from Offlineagent.tool_layer import file_tools, shell_tools, document_tools, browser_tools, db_tools
from Offlineagent.memory_layer.memory_store import MemoryStore

# Log directory
_LOG_DIR = _AGENT_DIR / "log"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
_LOG_FILE = None
_LOG_LOCK = threading.Lock()

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}

# Global state
_server_state: dict = {
    "config": {},
    "skills": [],
    "system_prompt": "",
    "llm_chat_fn": None,
    "registry": None,
    "logger": None,
    "state_manager_class": None,
    "llm_primary_chat_fn": None,
    "llm_secondary_chat_fn": None,
    "token_tracker": None,
}

# Track active states for multi-session
_active_states: dict[str, StateManager] = {}
_current_state_id: str = "default"
_cancel_flags: dict[str, bool] = {}
_cancel_lock = threading.Lock()

# ============================================================
# Logging
# ============================================================

def _init_log_file():
    """Initialize the log file for this session."""
    global _LOG_FILE
    from datetime import datetime
    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = _LOG_DIR / f"server_{session_id}.log"
    _LOG_FILE = open(str(log_path), "a", encoding="utf-8")
    return log_path

def _log(msg: str, level: str = "INFO", req_id: str = ""):
    """Write a log message to file and console."""
    from datetime import datetime
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    prefix = f"[{ts}] [{level}]"
    if req_id:
        prefix += f" [{req_id[:8]}]"
    line = f"{prefix} {msg}"
    try:
        print(line)
    except Exception:
        pass
    with _LOG_LOCK:
        if _LOG_FILE:
            _LOG_FILE.write(line + "\n")
            _LOG_FILE.flush()

# ============================================================
# LLM Client
# ============================================================

def _get_active_model_name() -> str:
    """Get the currently active model name."""
    config = _server_state.get("config", {})
    llm_cfg = config.get("llm", {})
    if "primary" in llm_cfg:
        active = llm_cfg.get("active", "primary")
        return llm_cfg.get(active, {}).get("model", "unknown")
    return llm_cfg.get("model", "unknown")

def _get_active_timeout() -> int:
    """Get the currently active LLM timeout."""
    config = _server_state.get("config", {})
    llm_cfg = config.get("llm", {})
    if "primary" in llm_cfg:
        active = llm_cfg.get("active", "primary")
        return llm_cfg.get(active, {}).get("timeout", 300)
    return llm_cfg.get("timeout", 300)

def create_llm_chat_fn(config: dict, base_dir: Path):
    """Create a unified LLM chat function supporting multi-backend config.

    Supports two config formats:
    1. Multi-backend: llm.primary / llm.secondary with llm.active
    2. Legacy flat: llm.url / llm.model (auto-converted)

    Returns: (chat_fn, switch_backend_fn, get_active_model_fn, list_backends_fn)
    """
    llm_cfg = config.get("llm", {})

    # -- Detect config format and build backend dict --
    if "primary" in llm_cfg:
        # Multi-backend format
        backends = {}
        for name in ("primary", "secondary"):
            if name in llm_cfg:
                be = llm_cfg[name]
                backends[name] = {
                    "url": be.get("url", ""),
                    "model": be.get("model", "unknown"),
                    "timeout": be.get("timeout", 300),
                    "api_key": be.get("api_key", ""),
                }
        active = llm_cfg.get("active", "primary")
        if active not in backends:
            _log(f"active backend '{active}' not found, using first available", "WARN")
            active = next(iter(backends.keys()))
    else:
        # Legacy flat format
        backends = {
            "default": {
                "url": llm_cfg.get("url", ""),
                "model": llm_cfg.get("model", "Qwen3"),
                "timeout": llm_cfg.get("timeout", 300),
                "api_key": llm_cfg.get("api_key", ""),
            }
        }
        active = "default"
        config["llm"] = {
            "active": "default",
            "default": backends["default"],
        }

    # -- Validate --
    if not backends:
        _log("No LLM backends configured, using echo fallback", "WARN")
        def _echo(messages, **kwargs):
            return f"[Echo mode] Received {len(messages)} messages."
        return _echo, lambda name: "No backends", lambda: "echo", lambda: "No backends"

    # State for backend switching
    _active_name = [active]  # list for mutable closure capture

    # -- Connection test on startup --
    be = backends[active]
    url = be["url"]
    if url:
        try:
            headers = {"Content-Type": "application/json"}
            if be["api_key"]:
                headers["Authorization"] = f"Bearer {be['api_key']}"
            test_data = {"model": be["model"], "messages": [{"role": "user", "content": "hi"}]}
            test_resp = requests.post(url, headers=headers, json=test_data, timeout=min(be["timeout"], 15))
            if test_resp.status_code == 200:
                _log(f"LLM connection OK: {url} (backend={active}, model={be['model']})")
            else:
                _log(f"LLM test returned status={test_resp.status_code}", "WARN")
        except Exception as e:
            _log(f"LLM connection test failed: {e}", "WARN")
    else:
        _log("Active backend has no URL, chat will fail at call time", "WARN")

    # -- The actual chat function --
    def _chat(messages, **kwargs):
        b = backends[_active_name[0]]
        if not b["url"]:
            return f"[Error] Backend '{_active_name[0]}' has no URL configured."

        headers = {"Content-Type": "application/json"}
        if b["api_key"]:
            headers["Authorization"] = f"Bearer {b['api_key']}"

        data = {"model": b["model"], "messages": messages}
        if "temperature" in kwargs:
            data["temperature"] = kwargs["temperature"]
        if "max_tokens" in kwargs:
            data["max_tokens"] = kwargs["max_tokens"]

        resp = requests.post(b["url"], headers=headers, json=data, timeout=b["timeout"])
        resp.raise_for_status()
        result = resp.json()

        # Track usage
        usage = result.get("usage")
        if usage:
            tracker = _server_state.get("token_tracker")
            if tracker:
                try:
                    tracker.record(
                        backend=_active_name[0],
                        model=b["model"],
                        prompt_tokens=usage.get("prompt_tokens", 0),
                        completion_tokens=usage.get("completion_tokens", 0),
                        total_tokens=usage.get("total_tokens", 0),
                    )
                except Exception:
                    pass

        choices = result.get("choices", [])
        if not choices:
            return "[Error] LLM returned empty choices."
        return choices[0].get("message", {}).get("content", "[Error] No content in LLM response.")

    # -- Helper functions --
    def _switch_backend(name):
        if name not in backends:
            return f"Unknown backend: {name}. Available: {', '.join(backends.keys())}"
        _active_name[0] = name
        config["llm"]["active"] = name
        return f"Switched to {name} ({backends[name]['model']})"

    def _get_model():
        return backends[_active_name[0]]["model"]

    def _list_backends():
        return ", ".join(f"{k}({v['model']})" for k, v in backends.items())

    return _chat, _switch_backend, _get_model, _list_backends


def _prepare_user_content(user_input: str):
    """Convert user input with embedded base64 images to multimodal content blocks."""
    # Pattern: data:image/...;base64,...
    import re as _re
    img_pattern = _re.compile(r'!?\[.*?\]\((data:image/[^;]+;base64,[A-Za-z0-9+/=]+)\)')

    matches = list(img_pattern.finditer(user_input))
    if not matches:
        return user_input

    # Build multimodal content array
    content_blocks = []
    last_end = 0
    for match in matches:
        # Text before this image
        text_before = user_input[last_end:match.start()].strip()
        if text_before:
            content_blocks.append({"type": "text", "text": text_before})

        # Image block
        img_url = match.group(1)
        content_blocks.append({
            "type": "image_url",
            "image_url": {"url": img_url},
        })
        last_end = match.end()

    # Remaining text
    text_after = user_input[last_end:].strip()
    if text_after:
        content_blocks.append({"type": "text", "text": text_after})

    return content_blocks if len(content_blocks) > 1 else content_blocks[0].get("text", user_input)


# ============================================================
# Message building
# ============================================================

def build_messages(system_prompt: str, state: StateManager, user_input: str, config: dict, req_id: str = "") -> list[dict]:
    """Build the full message list for the LLM API call."""
    # Convert embedded images to multimodal content blocks
    user_content = _prepare_user_content(user_input)
    state.add_user_message(user_content)

    # --- Auto-inject matching skills ---
    skills = _server_state.get("skills", [])
    if skills:
        matched = match_skills(user_input, skills, max_skills=3)
        recent_text = " ".join(
            m.get("content", "") if isinstance(m.get("content"), str) else ""
            for m in state.messages[-6:] if m.get("role") == "user"
        )
        for skill in matched:
            if f"[Skill Context: {skill.name}]" in recent_text:
                _log(f"Skill already in context, skipping: {skill.name}", req_id=req_id)
                continue
            skill_body = get_skill_body(skill)
            if skill_body:
                skill_msg = (f"[Skill Context: {skill.name}]\n\n{skill_body}\n\n"
                             f"---\n\n"
                             f"[Follow the skill instructions above for the user's request below.]")
                state.messages.append({"role": "user", "content": skill_msg})
                skill.use_count += 1
                _log(f"Auto-injected skill: {skill.name}", req_id=req_id)

    model = _get_active_model_name()
    messages = state.get_history_for_api(system_prompt)
    _log(f"Messages built: {len(messages)} items", req_id=req_id)

    # Pre-check for unsupported content
    stripped = check_before_send(model, [m for m in messages if m["role"] != "system"], _AGENT_DIR / "memory")
    if stripped:
        _log(f"Pre-stripped unsupported content for model={model}", "INFO", req_id)
        non_system = [m for m in state.messages if m["role"] != "system"]
        state.messages = [m for m in state.messages if m["role"] == "system"] + stripped
        messages = state.get_history_for_api(system_prompt)

    # Compression check (only when token budget > 70%)
    agent_cfg = config.get("agent", {})
    compression_cfg = agent_cfg.get("compression", {})
    if compression_cfg.get("enabled", True):
        if state.needs_compression(compression_cfg.get("trigger_ratio", 0.7)):
            _log("Triggering context compression...", req_id=req_id)
            try:
                compress_history(
                    state, system_prompt, _server_state["llm_chat_fn"],
                    keep_recent=compression_cfg.get("keep_recent", 2),
                )
                messages = state.get_history_for_api(system_prompt)
                _log(f"Compression done, now {len(messages)} messages", req_id=req_id)
            except Exception as e:
                _log(f"Compression failed (non-fatal): {e}", "WARN", req_id)

    return messages


# ============================================================
# LLM Call with timeout and retry
# ============================================================

def _llm_call_with_timeout(llm_fn, messages, timeout_sec: int, req_id: str = ""):
    """Call LLM with timeout, retry up to 3 times (with backoff) on timeout/connection errors."""
    import threading as _threading

    result_container = {"response": None, "error": None, "done": False}

    def _call():
        try:
            result_container["response"] = llm_fn(messages)
        except Exception as e:
            result_container["error"] = str(e)
        finally:
            result_container["done"] = True

    last_error = None
    for attempt in range(3):
        if attempt > 0:
            backoff = 2 ** (attempt - 1)
            _log(f"Retry attempt {attempt + 1}/3 after {backoff}s...", "WARN", req_id)
            time.sleep(backoff)

        result_container = {"response": None, "error": None, "done": False}
        t = _threading.Thread(target=_call, daemon=True)
        t.start()
        t.join(timeout=timeout_sec)

        if not result_container["done"]:
            _log(f"LLM call timed out after {timeout_sec}s (attempt {attempt + 1}/3)", "WARN", req_id)
            last_error = f"[Timeout] LLM did not respond within {timeout_sec} seconds."
            continue  # retry

        if result_container["error"]:
            err_str = str(result_container["error"]).lower()
            # Check if retryable (connection, timeout, rate-limit, server-error, json-parse)
            retryable_kw = (
                "timeout", "connection", "refused", "reset",
                "expecting value", "json", "decode",
                "rate limit", "too many requests",
                "server error", "internal server error",
                "service unavailable", "bad gateway",
                "gateway timeout",
            )
            if any(kw in err_str.lower() for kw in retryable_kw):
                last_error = f"[LLM Error] {err_str}"
                _log(f"Retryable LLM error (attempt {attempt + 1}/3): {err_str[:120]}", "WARN", req_id)
                continue  # retry
            return f"[LLM Error] {err_str}"

        return result_container["response"] or "[LLM Error] Empty response from LLM function"

    # All retries exhausted
    return last_error or "[LLM Error] Unknown failure after retries"


def _is_cancelled(req_id: str) -> bool:
    """Check if a request has been cancelled."""
    with _cancel_lock:
        return _cancel_flags.get(req_id, False)


# ============================================================
# Tool Loop (Hermes-style while-True with budget/safety valves)
# ============================================================

def run_tool_loop(messages: list[dict], system_prompt: str, state: StateManager,
                  config: dict, registry: ToolRegistry, logger, req_id: str = "",
                  status_callback=None) -> str:
    """Run the tool execution loop with token-budget control.

    Replaces old fixed max_iterations=10 with Hermes-style while-True loop.
    - Loop exits naturally when LLM returns no tool calls
    - Token budget at tool_budget_ratio (default 0.9) triggers forced answer
    - Cycle detection: 3 consecutive same-tool+same-param triggers warning
    """
    llm_fn = _server_state["llm_chat_fn"]
    llm_timeout = _get_active_timeout()
    base_timeout = llm_timeout

    def _dynamic_timeout(msg_count: int) -> int:
        extra = (msg_count // 10) * 5
        return min(base_timeout + extra, 180)

    agent_cfg = config.get("agent", {})
    budget_ratio = agent_cfg.get("tool_budget_ratio", 0.9)
    cycle_detection = agent_cfg.get("cycle_detection", True)
    max_iterations = agent_cfg.get("max_tool_iterations", 50)

    iterations = 0
    final_parts = []
    model = _get_active_model_name()
    recent_tool_calls: list[tuple[str, str]] = []

    try:
        while True:
            if _is_cancelled(req_id):
                _log(f"Request cancelled by user at iteration {iterations}", "INFO", req_id)
                return "[Cancelled] Request was cancelled by user."

            usage = state.usage_ratio()
            if usage >= budget_ratio:
                _log(
                    "Token budget exhausted: {:.1%} >= {:.1%}, forcing final response".format(
                        usage, budget_ratio
                    ),
                    "WARN", req_id,
                )
                if status_callback:
                    status_callback("status", {
                        "text": "Token budget exhausted, generating final response...",
                        "type": "warn",
                    })
                force_msg = (
                    "[SYSTEM] Token budget nearly exhausted "
                    + "({}/{}). ".format(state.estimate_total_tokens(), state.max_tokens)
                    + "Respond DIRECTLY to the user NOW. Do NOT make any more tool calls. "
                    + "Summarize findings and provide your best answer."
                )
                state.messages.append({"role": "user", "content": force_msg})
                messages = state.get_history_for_api(system_prompt)
                t0 = time.time()
                response = _llm_call_with_timeout(llm_fn, messages, llm_timeout, req_id)
                elapsed = time.time() - t0
                resp_len = len(response) if response else 0
                _log(
                    "Forced final LLM response in {:.1f}s: {} chars".format(elapsed, resp_len),
                    req_id=req_id,
                )
                if (
                    response
                    and not response.startswith("[Timeout]")
                    and not response.startswith("[LLM Error]")
                ):
                    final_parts.append(response)
                else:
                    final_parts.append(
                        "[Note: Token budget reached. Unable to generate final response.]"
                    )
                break

            iterations += 1
            # Safety valve: max iterations reached => force final answer
            if iterations >= max_iterations:
                _log(
                    "Max iterations reached ({}), forcing final response".format(max_iterations),
                    "WARN", req_id,
                )
                if status_callback:
                    status_callback("status", {
                        "text": "Max iterations reached, generating final response...",
                        "type": "warn",
                    })
                force_msg = (
                    "[SYSTEM] Maximum tool iterations ({}) reached. ".format(max_iterations)
                    + "Respond DIRECTLY to the user NOW. Do NOT make any more tool calls. "
                    + "Summarize findings and provide your best answer."
                )
                state.messages.append({"role": "user", "content": force_msg})
                messages = state.get_history_for_api(system_prompt)
                t0 = time.time()
                response = _llm_call_with_timeout(llm_fn, messages, llm_timeout, req_id)
                elapsed = time.time() - t0
                resp_len = len(response) if response else 0
                _log(
                    "Max-iter forced response in {:.1f}s: {} chars".format(elapsed, resp_len),
                    req_id=req_id,
                )
                if (
                    response
                    and not response.startswith("[Timeout]")
                    and not response.startswith("[LLM Error]")
                ):
                    final_parts.append(response)
                else:
                    final_parts.append(
                        "[Note: Max iterations reached. Unable to generate final response.]"
                    )
                break
            _log(
                "Tool loop iteration {}, budget={:.1%}, messages={}".format(
                    iterations, usage, len(messages)
                ),
                req_id=req_id,
            )

            if status_callback:
                status_callback("status", {
                    "text": "Calling model (iteration {})...".format(iterations),
                    "type": "llm",
                })

            t0 = time.time()
            response = _llm_call_with_timeout(llm_fn, messages, llm_timeout, req_id)

            if _is_cancelled(req_id):
                _log(
                    "Request cancelled during LLM call at iteration {}".format(iterations),
                    "INFO", req_id,
                )
                return "[Cancelled] Request was cancelled by user."

            elapsed = time.time() - t0
            resp_len = len(response) if response else 0
            has_tc = has_tool_calls(response) if response else False
            _log(
                "LLM response in {:.1f}s: {} chars, has_tool_calls={}".format(
                    elapsed, resp_len, has_tc
                ),
                req_id=req_id,
            )

            if not response:
                _log("LLM returned empty response", "WARN", req_id)
                return "[Error] No response from LLM."

            if response.startswith("[Timeout]") or response.startswith("[LLM Error]"):
                model = _get_active_model_name()
                non_system = [m for m in messages if m["role"] != "system"]
                repaired = repair_after_error(model, response, non_system, _AGENT_DIR / "memory")
                if repaired != non_system:
                    _log("Auto-repaired: stripped unsupported content, retrying...", "INFO", req_id)
                    state.messages = [m for m in state.messages if m["role"] == "system"] + repaired
                    messages = state.get_history_for_api(system_prompt)
                    continue

                _log("LLM error response: {}".format(response[:100]), "ERROR", req_id)
                if final_parts:
                    _log(
                        "Preserving {} partial text parts despite LLM error".format(len(final_parts)),
                        "WARN", req_id,
                    )
                    partial = "\n\n".join(p for p in final_parts if p)
                    partial += "\n\n---\n*[Note: LLM request failed ({}). Partial results shown above.]*".format(
                        response[:80]
                    )
                    return partial
                return response

            if not has_tc:
                _log(
                    "No tool calls, final response: {} chars".format(resp_len),
                    req_id=req_id,
                )
                final_parts.append(response)
                break

            tool_calls = parse_tool_calls_full(response)
            text_part = extract_text_without_tools(response)
            if text_part:
                final_parts.append(text_part)

            if not tool_calls:
                _log(
                    "has_tool_calls=True but parse empty, treating as text",
                    req_id=req_id,
                )
                final_parts.append(response)
                break

            tc_names = [tc.name for tc in tool_calls]
            _log(
                "Parsed {} tool call(s): {}".format(len(tool_calls), tc_names),
                req_id=req_id,
            )

            for tc in tool_calls:
                if _is_cancelled(req_id):
                    return "[Cancelled] Request was cancelled by user."

                if cycle_detection:
                    call_key = (tc.name, str(tc.params))
                    recent_tool_calls.append(call_key)
                    if len(recent_tool_calls) > 6:
                        recent_tool_calls.pop(0)
                    # Check last 3
                    if len(recent_tool_calls) >= 3:
                        last3 = recent_tool_calls[-3:]
                        if last3[0] == last3[1] == last3[2]:
                            _log(
                                "Cycle detected: {} called 3x with same params".format(tc.name),
                                "WARN", req_id,
                            )
                            cycle_msg = (
                                "[SYSTEM] You have called '{}' with the same parameters 3 times. "
                                "This is a cycle. Stop using this tool and either:\n"
                                "1. Try a DIFFERENT approach or tool\n"
                                "2. Respond to the user with what you have found so far"
                            ).format(tc.name)
                            state.messages.append({"role": "user", "content": cycle_msg})
                            messages = state.get_history_for_api(system_prompt)
                            break  # Break out of per-tool-call loop, re-enter main loop

                if status_callback:
                    status_callback("status", {
                        "text": "Executing {}...".format(tc.name),
                        "type": "tool",
                        "tool": tc.name,
                    })

                result = registry.execute(tc.name, tc.params)
                result_str = str(result)[:4000]

                state.messages.append({
                    "role": "assistant",
                    "content": response,
                })
                state.messages.append({
                    "role": "user",
                    "content": f"[Tool Result: {tc.name}]\n{result_str}",
                })

                if status_callback:
                    status_callback("status", {
                        "text": "{} completed".format(tc.name),
                        "type": "tool_done",
                        "tool": tc.name,
                        "result": result_str[:500],
                    })

                if status_callback:
                    status_callback("message", {
                        "text": response,
                        "tool_result": {"tool": tc.name, "content": result_str[:500]},
                    })

                messages = state.get_history_for_api(system_prompt)

            # After processing tool calls, check if this iteration had any cycle break
            if cycle_detection and len(recent_tool_calls) >= 3:
                last3 = recent_tool_calls[-3:]
                if last3[0] == last3[1] == last3[2]:
                    continue  # Re-enter main loop with cycle warning injected

            # If no cycle break, re-enter main loop naturally (LLM will see tool results)

    except Exception as e:
        _log(f"Tool loop exception: {e}\n{traceback.format_exc()}", "ERROR", req_id)
        if final_parts:
            return "\n\n".join(p for p in final_parts if p)
        return f"[Error] Tool loop crashed: {e}"

    # Ensure final_parts is joined even when exceptions occur in finally
    return "\n\n".join(p for p in final_parts if p)


# ============================================================
# State management
# ============================================================

def get_or_create_state() -> StateManager:
    """Get current session state, create if not exists."""
    global _current_state_id
    sid = _current_state_id
    if sid not in _active_states:
        config = _server_state["config"]
        max_tokens = config.get("agent", {}).get("max_tokens_estimate", 128000)
        _active_states[sid] = StateManager(max_tokens=max_tokens)
        _log(f"State manager created (new session: {sid})", req_id=sid)
    return _active_states[sid]


def switch_state(session_id: str):
    """Switch to a different session."""
    global _current_state_id
    _current_state_id = session_id
    if session_id not in _active_states:
        config = _server_state["config"]
        max_tokens = config.get("agent", {}).get("max_tokens_estimate", 128000)
        _active_states[session_id] = StateManager(max_tokens=max_tokens)
    return _active_states[session_id]


# ============================================================
# Conversation storage
# ============================================================

def _save_conversation(state_id: str, state: StateManager):
    """Save conversation state to disk."""
    conv_dir = _AGENT_DIR / "memory" / "conversations"
    conv_dir.mkdir(parents=True, exist_ok=True)
    conv_file = conv_dir / f"{state_id}.json"
    try:
        data = {
            "id": state_id,
            "created": getattr(state, "created_at", time.time()),
            "updated": time.time(),
            "title": _get_conv_title(state),
            "state": {
                "messages": state.messages,
                "message_count": len(state.messages),
            }
        }
        conv_file.write_text(_json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        _log(f"Failed to save conversation: {e}", "WARN")


def _get_conv_title(state: StateManager) -> str:
    """Extract a title from conversation history."""
    for msg in state.messages:
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str) and len(content) > 3:
                return content[:50]
    return "New Conversation"


# ============================================================
# HTTP Server
# ============================================================

class OfflineAgentHandler(http.server.BaseHTTPRequestHandler):
    """HTTP request handler with SSE streaming support."""

    def log_message(self, format, *args):
        """Override to use our logger."""
        _log("HTTP: " + format % args)

    def _send_cors(self):
        """Send CORS headers."""
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Request-ID")

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/"):
            self._handle_api_get(parsed)
        else:
            self._serve_static(path)

    def _handle_api_get(self, parsed):
        """Handle GET API requests."""
        path = parsed.path

        if path == "/api/status":
            self._handle_api_status()
        elif path == "/api/conversations":
            self._handle_api_conversations()
        elif path == "/api/conversation/current":
            self._handle_api_current_conversation()
        elif path.startswith("/api/conversation/"):
            conv_id = path.split("/")[-1]
            self._handle_api_conversation_load(conv_id)
        elif path == "/api/tokens/backends":
            self._handle_api_tokens_backends()
        elif path == "/api/tokens/models":
            self._handle_api_tokens_models(parsed)
        elif path == "/api/tokens/stats":
            self._handle_api_tokens_stats(parsed)
        elif path == "/api/skills":
            self._handle_api_skills()
        elif path == "/api/chat/search":
            self._handle_api_chat_search(parsed)
        else:
            self._serve_static(path)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/chat":
            self._handle_api_chat()
        elif path.startswith("/api/chat/switch/"):
            conv_id = path.split("/")[-1]
            self._handle_api_chat_switch(conv_id)
        elif path == "/api/chat/new":
            self._handle_api_chat_new()
        elif path == "/api/stop":
            self._handle_api_stop()
        elif path == "/api/upload":
            self._handle_api_upload()
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error": "Not Found"}')

    def _serve_static(self, path: str):
        """Serve a static file from frontend/."""
        if path == "/" or path == "":
            path = "/index.html"

        rel = path.lstrip("/")
        file_path = _AGENT_DIR / "frontend" / rel

        if not file_path.exists() or not file_path.is_file():
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")
            return

        ext = os.path.splitext(path)[1].lower()
        mime = MIME_TYPES.get(ext, "application/octet-stream")

        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Cache-Control", "no-cache")
        self._send_cors()
        self.end_headers()

        try:
            content = file_path.read_bytes()
            self.wfile.write(content)
        except Exception:
            pass

    def _handle_api_chat(self):
        """Handle POST /api/chat with SSE streaming."""
        req_id = str(uuid.uuid4())
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        try:
            data = _json.loads(body)
            user_input = data.get("message", "")
        except Exception:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'{"error": "Invalid JSON"}')
            return

        if not user_input:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'{"error": "Empty message"}')
            return

        _log(f"Chat request [{req_id[:8]}]: {user_input[:120]}...", req_id=req_id)

        with _cancel_lock:
            _cancel_flags[req_id] = False

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Request-ID", req_id[:8])
        self._send_cors()
        self.end_headers()

        def send_sse(event: str, data: dict):
            try:
                msg = f"event: {event}\ndata: {_json.dumps(data, ensure_ascii=False)}\n\n"
                self.wfile.write(msg.encode("utf-8"))
                self.wfile.flush()
                return True
            except (BrokenPipeError, ConnectionResetError, OSError):
                _log(f"Client disconnected during SSE", "INFO", req_id)
                with _cancel_lock:
                    _cancel_flags[req_id] = True
                return False

        try:
            state = get_or_create_state()
            config = _server_state["config"]
            system_prompt = _server_state["system_prompt"]
            registry = _server_state["registry"]
            logger = _server_state["logger"]

            if user_input.startswith("/"):
                _log(f"Built-in command: {user_input}", req_id=req_id)
                response = _handle_web_command(user_input, state, req_id)
                if not send_sse("message", {"text": response}):
                    return
                send_sse("done", {})
                return

            t0_total = time.time()
            if not send_sse("status", {"text": "Analyzing context...", "type": "llm"}):
                return

            messages = build_messages(system_prompt, state, user_input, config, req_id)

            response = run_tool_loop(messages, system_prompt, state, config, registry, logger, req_id, send_sse)
            if response and not response.startswith("[LLM Error]") and not response.startswith("[Timeout]"):
                state.add_assistant_message(response)
            else:
                _log("Adding error recovery marker to state history", req_id=req_id)
                state.messages.append({"role": "system", "content": "[System] Previous request encountered an error and was recovered. You may continue the conversation normally."})

            elapsed_total = time.time() - t0_total
            resp_len = len(response) if response else 0
            _log(f"Turn complete in {elapsed_total:.1f}s: {resp_len} chars response", req_id=req_id)

            send_sse("message", {"text": response})
            send_sse("done", {})

            # Save conversation
            _save_conversation(_current_state_id, state)

        except Exception as e:
            _log(f"Chat error: {e}\n{traceback.format_exc()}", "ERROR", req_id)
            try:
                send_sse("error", {"text": str(e)})
            except Exception:
                pass
        finally:
            with _cancel_lock:
                _cancel_flags.pop(req_id, None)

    def _handle_api_status(self):
        """Handle GET /api/status."""
        config = _server_state["config"]
        skills = _server_state["skills"]
        tools = _server_state["registry"]

        status = {
            "server": "running",
            "model": _get_active_model_name(),
            "skills_count": len(skills),
            "tools_count": len(tools.names()) if tools else 0,
            "active_sessions": len(_active_states),
            "current_session": _current_state_id,
        }
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self._send_cors()
        self.end_headers()
        self.wfile.write(_json.dumps(status, ensure_ascii=False).encode("utf-8"))

    # --- API stubs for other endpoints (abbreviated for brevity, full versions in file) ---

    def _handle_api_conversations(self):
        conv_dir = _AGENT_DIR / "memory" / "conversations"
        if not conv_dir.exists():
            result = []
        else:
            result = []
            for f in sorted(conv_dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
                try:
                    data = _json.loads(f.read_text(encoding="utf-8"))
                    result.append({
                        "id": data.get("id", f.stem),
                        "title": data.get("title", f.stem),
                        "updated": data.get("updated", 0),
                        "message_count": data.get("state", {}).get("message_count", 0),
                    })
                except Exception:
                    pass
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self._send_cors()
        self.end_headers()
        self.wfile.write(_json.dumps({"conversations": result}, ensure_ascii=False).encode("utf-8"))

    def _handle_api_current_conversation(self):
        state = get_or_create_state()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self._send_cors()
        self.end_headers()
        self.wfile.write(_json.dumps({
            "id": _current_state_id,
            "messages": state.messages,
        }, ensure_ascii=False).encode("utf-8"))

    def _handle_api_conversation_load(self, conv_id: str):
        conv_file = _AGENT_DIR / "memory" / "conversations" / f"{conv_id}.json"
        if not conv_file.exists():
            self.send_response(404)
            self.end_headers()
            return
        try:
            data = _json.loads(conv_file.read_text(encoding="utf-8"))
            state = switch_state(conv_id)
            state.messages = data.get("state", {}).get("messages", [])
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._send_cors()
            self.end_headers()
            self.wfile.write(_json.dumps({"ok": True}, ensure_ascii=False).encode("utf-8"))
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(_json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8"))

    def _handle_api_chat_switch(self, conv_id: str):
        switch_state(conv_id)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self._send_cors()
        self.end_headers()
        self.wfile.write(_json.dumps({"ok": True, "session": conv_id}, ensure_ascii=False).encode("utf-8"))

    def _handle_api_chat_new(self):
        new_id = f"conv_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        switch_state(new_id)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self._send_cors()
        self.end_headers()
        self.wfile.write(_json.dumps({"ok": True, "session": new_id}, ensure_ascii=False).encode("utf-8"))

    def _handle_api_stop(self):
        req_id = self.headers.get("X-Request-ID", "")
        with _cancel_lock:
            if req_id:
                _cancel_flags[req_id] = True
            else:
                for k in _cancel_flags:
                    _cancel_flags[k] = True
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self._send_cors()
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

    def _handle_api_upload(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        content_type = self.headers.get("Content-Type", "")

        if "multipart/form-data" in content_type:
            boundary = content_type.split("boundary=")[-1]
            parts = body.split(b"--" + boundary.encode())
            for part in parts:
                if b"filename=" in part:
                    header_end = part.find(b"\r\n\r\n")
                    if header_end == -1:
                        continue
                    headers_raw = part[:header_end].decode("utf-8", errors="replace")
                    file_data = part[header_end + 4:]
                    if file_data.endswith(b"\r\n"):
                        file_data = file_data[:-2]

                    filename = "uploaded_file"
                    if 'filename="' in headers_raw:
                        fn_start = headers_raw.index('filename="') + 10
                        fn_end = headers_raw.index('"', fn_start)
                        filename = headers_raw[fn_start:fn_end]

                    upload_dir = _AGENT_DIR / "uploads"
                    upload_dir.mkdir(parents=True, exist_ok=True)
                    file_path = upload_dir / filename
                    file_path.write_bytes(file_data)

                    ext = os.path.splitext(filename)[1].lower()
                    file_type = "binary"
                    if ext in (".txt", ".md", ".json", ".xml", ".yaml", ".yml", ".sql",
                               ".py", ".java", ".js", ".ts", ".html", ".css", ".csv"):
                        file_type = "text"
                        try:
                            preview = file_data.decode("utf-8")[:500]
                        except Exception:
                            preview = f"[Binary file, {len(file_data)} bytes]"
                    else:
                        preview = f"[{ext.upper()} file, {len(file_data)} bytes]"

                    _log(f"File uploaded: {filename} ({len(file_data)} bytes)")

                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self._send_cors()
                    self.end_headers()
                    self.wfile.write(_json.dumps({
                        "ok": True,
                        "filename": filename,
                        "path": str(file_path),
                        "size": len(file_data),
                        "type": file_type,
                        "preview": preview[:300],
                    }, ensure_ascii=False).encode("utf-8"))
                    return

        self.send_response(400)
        self.end_headers()
        self.wfile.write(b'{"error": "No file found"}')

    def _handle_api_tokens_backends(self):
        tracker = _server_state.get("token_tracker")
        backends = tracker.get_backends() if tracker else []
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self._send_cors()
        self.end_headers()
        self.wfile.write(_json.dumps({"backends": backends}, ensure_ascii=False).encode("utf-8"))

    def _handle_api_tokens_models(self, parsed):
        query = parse_qs(parsed.query)
        backend = query.get("backend", ["primary"])[0]
        tracker = _server_state.get("token_tracker")
        models = tracker.get_models(backend) if tracker else []
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self._send_cors()
        self.end_headers()
        self.wfile.write(_json.dumps({"models": models}, ensure_ascii=False).encode("utf-8"))

    def _handle_api_tokens_stats(self, parsed):
        query = parse_qs(parsed.query)
        backend = query.get("backend", [None])[0]
        model = query.get("model", [None])[0]
        range_val = query.get("range", ["week"])[0]
        tracker = _server_state.get("token_tracker")
        stats = tracker.query(backend=backend, model=model, range=range_val) if tracker else []
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self._send_cors()
        self.end_headers()
        self.wfile.write(_json.dumps({"stats": stats}, ensure_ascii=False).encode("utf-8"))

    def _handle_api_skills(self):
        skills = _server_state.get("skills", [])
        result = []
        for s in skills:
            result.append({
                "name": s.name,
                "source": s.source,
                "description": s.short_desc,
                "use_count": getattr(s, "use_count", 0),
            })
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self._send_cors()
        self.end_headers()
        self.wfile.write(_json.dumps({"skills": result, "total": len(result)}, ensure_ascii=False).encode("utf-8"))

    def _handle_api_chat_search(self, parsed):
        query = parse_qs(parsed.query)
        q = query.get("q", [""])[0]
        if not q:
            self.send_response(400)
            self.end_headers()
            return

        conv_dir = _AGENT_DIR / "memory" / "conversations"
        results = []
        q_lower = q.lower()
        if conv_dir.exists():
            for f in sorted(conv_dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
                try:
                    data = _json.loads(f.read_text(encoding="utf-8"))
                    title = data.get("title", "")
                    msgs = data.get("state", {}).get("messages", [])
                    full_text = title + " " + " ".join(
                        m.get("content", "") if isinstance(m.get("content"), str) else ""
                        for m in msgs
                    )
                    if q_lower in full_text.lower():
                        idx = full_text.lower().find(q_lower)
                        snippet_start = max(0, idx - 60)
                        snippet_end = min(len(full_text), idx + len(q) + 60)
                        snippet = full_text[snippet_start:snippet_end]
                        results.append({
                            "id": data.get("id", f.stem),
                            "title": title[:80],
                            "snippet": snippet[:200],
                            "updated": data.get("updated", 0),
                        })
                    if len(results) >= 20:
                        break
                except Exception:
                    pass

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self._send_cors()
        self.end_headers()
        self.wfile.write(_json.dumps({"results": results, "total": len(results)}, ensure_ascii=False).encode("utf-8"))


# ============================================================
# Built-in commands (web version)
# ============================================================

def _handle_web_command(cmd: str, state: StateManager, req_id: str = "") -> str:
    """Handle built-in commands for the web interface."""
    parts = cmd.split(maxsplit=1)
    command = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if command == "/help":
        return "Commands: /help /skills /skill <name> /tools /status /memory /clear /config /logs /exit"

    elif command == "/skills":
        skills = _server_state["skills"]
        if not skills:
            return "No skills loaded."
        lines = []
        for s in skills:
            lines.append(f"[{s.source}] {s.name}: {s.short_desc}")
        return "\n".join(lines)

    elif command == "/skill":
        if not arg:
            return "Usage: /skill <name>"
        for s in _server_state["skills"]:
            if s.name.lower() == arg.lower():
                body = get_skill_body(s)
                s.use_count += 1
                return f"## Skill: {s.name}\n\n{body}"
        return f"Skill not found: {arg}"

    elif command == "/tools":
        tools = _server_state["registry"]
        return f"Available tools: {', '.join(tools.names())}"

    elif command == "/status":
        status = state.status_summary(_server_state["system_prompt"])
        return (
            f"**Session**: {_current_state_id}\n"
            f"**Messages**: {len(state.messages)}\n"
            + status
        )

    elif command == "/memory":
        store = MemoryStore(_AGENT_DIR / "memory")
        mems = store.list_recent(10)
        if not mems:
            return "No memories stored."
        lines = []
        for m in mems:
            lines.append(f"- [{m['id']}] {m['content'][:100]}")
        return "\n".join(lines)

    elif command == "/clear":
        state.messages = []
        _log("Conversation cleared by user", req_id=req_id)
        return "Conversation cleared."

    elif command == "/config":
        config = _server_state["config"]
        llm_cfg = config.get("llm", {})
        active = llm_cfg.get("active", "N/A")
        if "primary" in llm_cfg:
            lines = [f"**Active backend**: {active}"]
            for name in ("primary", "secondary"):
                if name in llm_cfg:
                    be = llm_cfg[name]
                    mark = " *" if name == active else "  "
                    l = f"{mark} {name}: {be.get("model", "N/A")} @ {be.get("url", "N/A")[:80]}"
                    lines.append(l)
            lines.append(f"**Max tokens**: {config.get("agent", {}).get("max_tokens_estimate", "N/A")}")
            return "\n".join(lines)
        return (
            f"**Model**: {llm_cfg.get("model", "N/A")}\n"
            f"**URL**: {llm_cfg.get("url", "N/A")[:80]}\n"
        )

    elif command == "/logs":
        log_files = sorted(_LOG_DIR.glob("*.log"), key=lambda x: x.stat().st_mtime, reverse=True)[:5]
        if not log_files:
            return "No log files found."
        lines = ["## Recent Logs"]
        for lf in log_files:
            size = lf.stat().st_size
            lines.append(f"- {lf.name} ({size} bytes)")
        return "\n".join(lines)

    elif command == "/exit":
        _save_conversation(_current_state_id, state)
        return "Conversation saved. You can close the browser now."

    else:
        return f"Unknown command: {command}. Type /help for available commands."


# ============================================================
# Agent Initialization
# ============================================================

def init_agent(config: dict, base_dir: Path):
    """Initialize the agent with config and load all components."""
    # Logger
    _server_state["logger"] = _log

    # Skills
    _log("Loading skills...")
    skills = load_all_skills(config, base_dir)
    _server_state["skills"] = skills
    _log(f"Loaded {len(skills)} skills")
    for s in skills:
        _log(f"  Skill: [{s.source}] {s.name}")

    # Memory
    memory_dir = base_dir / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    store = MemoryStore(memory_dir)
    recent_entries = store.list_all()[:3]
    recent_memories = [store.get(e["id"]) for e in recent_entries if store.get(e["id"])]

    # System prompt
    system_prompt, _ = build_system_prompt(config, skills, base_dir, recent_memories=recent_memories)
    _server_state["system_prompt"] = system_prompt
    _log(f"System prompt built: {len(system_prompt)} chars")

    # Token tracker
    from Offlineagent.metrics.token_tracker import TokenTracker
    token_tracker = TokenTracker(memory_dir)
    _server_state["token_tracker"] = token_tracker

    # LLM client
    _log("Creating LLM client...")
    llm_fn, switch_backend_fn, get_model_fn, list_backends_fn = create_llm_chat_fn(config, base_dir)
    _server_state["llm_chat_fn"] = llm_fn
    _server_state["llm_primary_chat_fn"] = llm_fn
    _server_state["llm_switch_backend"] = switch_backend_fn
    _server_state["llm_list_backends"] = list_backends_fn
    _log(f"LLM client created (backends: {list_backends_fn()})")

    # Tool registry
    registry = ToolRegistry()
    _server_state["registry"] = registry

    # Register tools
    file_tools.set_file_base(base_dir)
    register_tools(registry, config, base_dir)

    # Initialize browser automation (non-blocking if Playwright not available)
    browser_init_msg = browser_tools.init_browser(base_dir)
    _log(f"Browser: {browser_init_msg}")

    _log(f"Agent initialized: {len(skills)} skills, {len(registry.names())} tools")


def register_tools(registry: ToolRegistry, config: dict, base_dir: Path):
    """Register all enabled tools."""
    enabled = config.get("tools", {}).get("enabled", [])
    shell_cfg = config.get("tools", {}).get("shell", {})
    file_write_cfg = config.get("tools", {}).get("file_write", {})

    # File tools
    if "read_file" in enabled:
        registry.register("read_file", lambda **kw: file_tools.read_file(kw.get("path", "")))
    if "write_file" in enabled:
        require_confirm = file_write_cfg.get("require_confirm", True)
        registry.register("write_file", lambda **kw: file_tools.write_file(
            kw.get("path", ""), kw.get("content", "")))
    if "list_dir" in enabled:
        registry.register("list_dir", lambda **kw: file_tools.list_dir(kw.get("path", "")))
    if "search_code" in enabled:
        registry.register("search_code", lambda **kw: file_tools.search_code(
            kw.get("pattern", ""), kw.get("path", "")))
    if "find_files" in enabled:
        registry.register("find_files", lambda **kw: file_tools.find_files(
            kw.get("pattern", "*"), kw.get("path", "")))

    # Shell tools
    if "shell" in enabled:
        allowed = shell_cfg.get("allowed", [])
        registry.register("shell", lambda **kw: shell_tools.shell(
            kw.get("command", ""), allowed_commands=allowed))

    # Document tools
    if "read_template" in enabled:
        registry.register("read_template", lambda **kw: document_tools.read_template(
            kw.get("path", ""), base_dir))
    if "write_output" in enabled:
        registry.register("write_output", lambda **kw: document_tools.write_output(
            kw.get("path", ""), kw.get("content", ""), base_dir))
    if "write_docx" in enabled:
        registry.register("write_docx", lambda **kw: document_tools.write_docx(
            kw.get("path", ""), kw.get("fields", {}), kw.get("template_path", ""), base_dir))
    if "write_xlsx" in enabled:
        registry.register("write_xlsx", lambda **kw: document_tools.write_xlsx(
            kw.get("path", ""), kw.get("fields", {}), kw.get("template_path", ""), base_dir))
    if "write_pptx" in enabled:
        registry.register("write_pptx", lambda **kw: document_tools.write_pptx(
            kw.get("path", ""), kw.get("fields", {}), kw.get("template_path", ""), base_dir))

    # Web tools
    if "web_fetch" in enabled:
        registry.register("web_fetch", lambda **kw: browser_tools.web_fetch(
            kw.get("url", ""), kw.get("method", "GET"), kw.get("body", ""),
            kw.get("headers", ""), kw.get("timeout", 30)))
    if "browser_status" in enabled:
        registry.register("browser_status", lambda **kw: browser_tools.browser_status(base_dir))
    if "browser_navigate" in enabled:
        registry.register("browser_navigate", lambda **kw: browser_tools.browser_navigate(
            kw.get("url", ""), base_dir))
    if "browser_screenshot" in enabled:
        registry.register("browser_screenshot", lambda **kw: browser_tools.browser_screenshot(
            kw.get("name", "screenshot"), base_dir))
    if "browser_click" in enabled:
        registry.register("browser_click", lambda **kw: browser_tools.browser_click(
            kw.get("selector", ""), base_dir))
    if "browser_type" in enabled:
        registry.register("browser_type", lambda **kw: browser_tools.browser_type(
            kw.get("selector", ""), kw.get("text", ""), base_dir))
    if "browser_get_content" in enabled:
        registry.register("browser_get_content", lambda **kw: browser_tools.browser_get_content(
            kw.get("selector", None), kw.get("max_length", 5000), base_dir))
    if "browser_get_html" in enabled:
        registry.register("browser_get_html", lambda **kw: browser_tools.browser_get_html(
            kw.get("selector", None), base_dir))
    if "browser_exec" in enabled:
        registry.register("browser_exec", lambda **kw: browser_tools.browser_exec(
            kw.get("js", ""), base_dir))


# ============================================================
# Server startup
# ============================================================

    # Database tools
    if "db_connect" in enabled:
        registry.register("db_connect", lambda **kw: db_tools.db_connect(
            kw.get("engine", ""), kw.get("host", ""), int(kw.get("port", 3306)),
            kw.get("user", ""), kw.get("password", ""), kw.get("database", "")))
    if "db_list_procedures" in enabled:
        registry.register("db_list_procedures", lambda **kw: db_tools.db_list_procedures(
            kw.get("filter", "")))
    if "db_get_procedure" in enabled:
        registry.register("db_get_procedure", lambda **kw: db_tools.db_get_procedure(
            kw.get("name", "")))
    if "db_list_tables" in enabled:
        registry.register("db_list_tables", lambda **kw: db_tools.db_list_tables(
            kw.get("filter", "")))
    if "db_query" in enabled:
        registry.register("db_query", lambda **kw: db_tools.db_query(
            kw.get("sql", ""), int(kw.get("limit", 100))))
    if "db_status" in enabled:
        registry.register("db_status", lambda **kw: db_tools.db_status())
    if "db_disconnect" in enabled:
        registry.register("db_disconnect", lambda **kw: db_tools.db_disconnect())

def start_server(config: dict, base_dir: Path):
    """Start the HTTP server."""
    init_agent(config, base_dir)

    host = config.get("server", {}).get("host", "0.0.0.0")
    port = config.get("server", {}).get("port", 8999)

    server = http.server.HTTPServer((host, port), OfflineAgentHandler)
    _log(f"Server running at http://localhost:{port}")

    def shutdown_handler(signum, frame):
        _log("Shutting down server...")
        server.shutdown()

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    try:
        # Polling loop handles Ctrl+C reliably on Windows (serve_forever doesn't)
        server.timeout = 0.5
        while True:
            server.handle_request()
    except KeyboardInterrupt:
        _log("Server stopped by user.")
    finally:
        _log("Server shutdown complete.")


if __name__ == "__main__":
    import yaml
    config_path = _AGENT_DIR / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    _init_log_file()
    _server_state["config"] = config
    start_server(config, _AGENT_DIR)
