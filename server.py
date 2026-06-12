#!/usr/bin/env python3
"""
server.py - OfflineAgent Web Server

Starts an HTTP server on http://localhost:8999 (default) that serves:
  - Static frontend (index.html, style.css, app.js)
  - POST /api/chat  - Send message, get SSE streaming response
  - GET  /api/status - Current agent status
  - GET  /api/files  - File browser & reader
  - POST /api/upload - File upload
  - GET  /api/logs   - Recent log entries
  - POST /api/cancel - Cancel current LLM request

Zero external dependencies: uses only Python stdlib.
"""

import sys
import os
import json as _json
import time
import threading
import traceback
import uuid
from pathlib import Path
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer  # concurrent request support
from urllib.parse import urlparse, parse_qs

# -- Path setup --
_THIS_FILE = Path(__file__).resolve()
_AGENT_DIR = _THIS_FILE.parent
_PARENT_DIR = _AGENT_DIR.parent

if str(_PARENT_DIR) not in sys.path:
    sys.path.insert(0, str(_PARENT_DIR))

# -- Imports --
from Offlineagent.vendor import requests
from Offlineagent.prompt_layer.skill_loader import load_all_skills
from Offlineagent.prompt_layer.system_prompt import build_system_prompt
from Offlineagent.orchestrator.state_manager import StateManager
from Offlineagent.orchestrator.context_compressor import compress_history
from Offlineagent.orchestrator.error_recovery import check_before_send
from Offlineagent.tool_layer.tool_registry import ToolRegistry
from Offlineagent.tool_layer.tool_parser import parse_tool_calls, has_tool_calls, extract_text_without_tools
from Offlineagent.tool_layer import file_tools, shell_tools, document_tools, browser_tools
from Offlineagent.memory_layer.memory_store import MemoryStore
from Offlineagent.metrics.logger import AgentLogger

# Reuse agent.py's config and tool setup
from Offlineagent.agent import load_config, create_llm_chat_fn, register_tools


# -- Global agent state --
_server_state = {
    "config": None,
    "base_dir": _AGENT_DIR,
    "skills": [],
    "system_prompt": "",
    "state": None,
    "registry": None,
    "llm_chat_fn": None,
    "memory_store": None,
    "logger": None,
}

# Per-request cancellation support
_cancel_flags: dict[str, bool] = {}
_cancel_lock = threading.Lock()

# Per-session conversation persistence
_CONV_DIR = _AGENT_DIR / "memory" / "conversations"
_CONV_DIR.mkdir(parents=True, exist_ok=True)
_conversations: dict[str, dict] = {}  # in-memory index

def _get_active_timeout() -> int:
    """Get the active backend timeout."""
    config = _server_state.get("config", {})
    llm = config.get("llm", {})
    if "primary" in llm:
        active = llm.get("active", "primary")
        return llm.get(active, {}).get("timeout", 60)
    return llm.get("timeout", 60)


def _get_active_model_name() -> str:
    """Get the active backend model name from config."""
    fn = _server_state.get("get_active_model_fn")
    if fn:
        return fn()
    config = _server_state.get("config", {})
    llm = config.get("llm", {})
    if "primary" in llm:
        active = llm.get("active", "primary")
        return llm.get(active, {}).get("model", "unknown")
    return llm.get("model", "unknown")




def _save_conversation(state) -> str | None:
    """Save current conversation to disk. Returns conversation id."""
    if not state or len(state.messages) <= 1:
        return None
    import uuid, json
    conv_id = uuid.uuid4().hex[:12]
    user_msgs = [m["content"] for m in state.messages if m["role"] == "user"]
    title = (user_msgs[0][:40] + "...") if user_msgs else "(empty)"
    data = {
        "id": conv_id,
        "title": title,
        "created_at": __import__("datetime").datetime.now().isoformat(),
        "message_count": len(state.messages),
        "state": state.to_dict(),
    }
    filepath = _CONV_DIR / f"{conv_id}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    _conversations[conv_id] = {
        "id": conv_id, "title": title, "path": str(filepath),
        "created_at": data["created_at"], "message_count": data["message_count"],
    }
    _log(f"Conversation saved: {conv_id} ({title})")
    return conv_id

def _load_conversation(conv_id: str) -> dict | None:
    """Load a conversation from disk. Returns full data dict or None."""
    filepath = _CONV_DIR / f"{conv_id}.json"
    if not filepath.exists():
        return None
    import json
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)

def _list_conversations() -> list[dict]:
    """List all saved conversations (newest first)."""
    import json
    results = []
    for fpath in sorted(_CONV_DIR.glob("*.json"), reverse=True):
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            results.append({
                "id": data["id"],
                "title": data["title"],
                "created_at": data["created_at"],
                "message_count": data["message_count"],
            })
        except Exception:
            pass
    return results



# -- Unified Logging --
LOG_DIR = _AGENT_DIR / "log"
LOG_DIR.mkdir(parents=True, exist_ok=True)
_log_write_lock = threading.Lock()


def _log(msg: str, level: str = "INFO", req_id: str = ""):
    """Write a line to the session log file and print to stdout (thread-safe)."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    req_tag = f"[{req_id[:8]}] " if req_id else ""
    line = f"[{ts}] [{level}] {req_tag}{msg}"
    print(line, flush=True)

    try:
        today = datetime.now().strftime("%Y%m%d")
        log_path = LOG_DIR / f"agent_{today}.log"
        with _log_write_lock:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        pass  # Don't let logging failure crash the server


def _llm_call_with_timeout(llm_fn, messages, timeout_sec: int, req_id: str = "") -> str:
    """Call LLM with timeout and exponential-backoff retry.

    Retries: up to 2 additional attempts on timeout (1s, 2s backoff).
    Connection errors and timeouts trigger retry; other errors return immediately.
    """
    last_error = None

    for attempt in range(3):  # 1 initial + 2 retries
        if attempt > 0:
            backoff = 2 ** (attempt - 1)  # 1s, 2s
            _log(f"LLM retry {attempt}/{2}, waiting {backoff}s...", "WARN", req_id)
            time.sleep(backoff)

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
            _log(f"LLM call timed out after {timeout_sec}s (attempt {attempt + 1}/3)", "WARN", req_id)
            last_error = f"[Timeout] LLM did not respond within {timeout_sec} seconds."
            continue  # retry

        if result_container["error"]:
            err_str = result_container["error"]
            _log(f"LLM call failed: {err_str}", "ERROR", req_id)
            retryable_kw = (
                "timeout", "connection", "connect", "read timed out",
                "expecting value", "json", "decode", "empty",
                "bad request", "server error", "unavailable",
                "rate limit", "too many requests"
            )
            if any(kw in err_str.lower() for kw in retryable_kw):
                last_error = f"[LLM Error] {err_str}"
                continue  # retry
            return f"[LLM Error] {err_str}"

        return result_container["response"] or ""

    # All retries exhausted
    with _cancel_lock:
        _cancel_flags.pop(req_id, None)
    return last_error or "[LLM Error] Unknown failure after retries"


def _is_cancelled(req_id: str) -> bool:
    with _cancel_lock:
        return _cancel_flags.get(req_id, False)


def init_agent():
    """Initialize the agent for web serving."""
    base_dir = _AGENT_DIR
    config_path = base_dir / "config.yaml"

    _log(f"Loading config from {config_path}")
    config = load_config(config_path)
    _server_state["config"] = config

    # Logger (memory-layer logger for structured events)
    log_dir = base_dir / "memory"
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = AgentLogger(log_dir)
    _server_state["logger"] = logger
    _log(f"Logger initialized, session={logger._session_id}")

    # Skills
    _log("Loading skills...")
    skills = load_all_skills(config, base_dir)
    _server_state["skills"] = skills
    _log(f"Loaded {len(skills)} skills")
    for s in skills:
        _log(f"  Skill: [{s.source}] {s.name}")

    # System prompt
    agent_cfg = config.get("agent", {})
    memory_store = None
    if agent_cfg.get("memory", {}).get("enabled", True):
        memory_store = MemoryStore(base_dir / "memory")

    recent_memories = memory_store.get_recent(agent_cfg.get("memory", {}).get("max_recent", 3)) if memory_store else None
    system_prompt, _ = build_system_prompt(config, skills, base_dir, recent_memories=recent_memories)
    _server_state["system_prompt"] = system_prompt
    _server_state["memory_store"] = memory_store
    _log(f"System prompt built: {len(system_prompt)} chars")

    # LLM client
    _log("Creating LLM client...")
    llm_chat_fn, switch_backend_fn, get_active_model_fn, list_backends_fn = create_llm_chat_fn(config)
    _server_state["llm_chat_fn"] = llm_chat_fn
    _server_state["switch_backend_fn"] = switch_backend_fn
    _server_state["get_active_model_fn"] = get_active_model_fn
    _server_state["list_backends_fn"] = list_backends_fn

    # Tools
    registry = ToolRegistry()
    register_tools(registry, config, base_dir)
    _server_state["registry"] = registry

    # Initialize browser in main thread (Playwright requires main-thread init)
    browser_init_msg = browser_tools.init_browser(base_dir)
    _log(browser_init_msg)

    _log(f"Agent initialized: {len(skills)} skills, {len(registry.names())} tools")


def get_or_create_state() -> StateManager:
    """Get or create a per-session state manager."""
    if _server_state["state"] is None:
        agent_cfg = _server_state["config"].get("agent", {})
        _server_state["state"] = StateManager(
            max_history=agent_cfg.get("max_history", 20),
            max_tokens=agent_cfg.get("max_tokens_estimate", 128000),
        )
        _log("State manager created (new session)")
    return _server_state["state"]


def build_messages(system_prompt: str, state: StateManager, user_input: str, config: dict, req_id: str = "") -> list[dict]:
    """Build the full message list for the LLM API call."""
    state.add_user_message(user_input)

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
                # using dynamic timeout based on context size
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
                _log("LLM error response: {}".format(response[:100]), "ERROR", req_id)
                # Preserve collected partial results instead of discarding them
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

            tool_calls = parse_tool_calls(response)
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
                            _log(
                                "Cycle detected: {}({}) x3, injecting warning".format(
                                    tc.name, first_param_str
                                ),
                                "WARN", req_id,
                            )
                            cycle_warning = (
                                "[SYSTEM] You have called {} with the same parameters 3 times. ".format(tc.name)
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
                    avail = ", ".join(registry.names())
                    err = "[Error] Unknown tool: {}. Available: {}".format(
                        tc.name, avail
                    )
                    _log("Unknown tool: {}".format(tc.name), "WARN", req_id)
                    state.add_tool_result(err)
                    continue

                try:
                    if status_callback:
                        status_callback("status", {
                            "text": "Executing: {}".format(tc.name),
                            "type": "tool",
                            "tool": tc.name,
                        })

                    _log(
                        "Executing tool: {}({})".format(
                            tc.name, str(tc.params)[:100]
                        ),
                        req_id=req_id,
                    )
                    t0_tool = time.time()
                    result = registry.dispatch(tc.name, tc.params)
                    tool_elapsed = time.time() - t0_tool
                    result_str = str(result)
                    _log(
                        "Tool {} done in {:.2f}s: {} chars".format(
                            tc.name, tool_elapsed, len(result_str)
                        ),
                        req_id=req_id,
                    )
                    state.add_tool_result(result_str)
                    if logger:
                        logger.tool_call(tc.name, str(tc.params)[:100], True)
                except Exception as e:
                    error_msg = "[Error] Tool {} failed: {}".format(tc.name, e)
                    _log(
                        "Tool {} failed: {}".format(tc.name, e),
                        "ERROR", req_id,
                    )
                    state.add_tool_result(error_msg)
                    if logger:
                        logger.tool_call(
                            tc.name, str(tc.params)[:100], False, str(e)[:100]
                        )

            messages = state.get_history_for_api(system_prompt)

    finally:
        result = "\n\n".join(p for p in final_parts if p)
        _log(
            "Tool loop complete: {} chars final response, iterations={}".format(
                len(result), iterations
            ),
            req_id=req_id,
        )

    return result


# -- HTTP Request Handler --

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
}


class AgentHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the OfflineAgent web server."""

    def log_message(self, format, *args):
        """Redirect HTTP server logs to our logger."""
        _log(f"HTTP: {format % args}", "HTTP")

    def _send_cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Request-ID")

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

        # Register cancel flag
        with _cancel_lock:
            _cancel_flags[req_id] = False

        # SSE response
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Request-ID", req_id[:8])
        self._send_cors()
        self.end_headers()

        def send_sse(event: str, data: dict):
            """Send an SSE event. Returns False if client disconnected."""
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

            # Handle built-in commands
            if user_input.startswith("/"):
                _log(f"Built-in command: {user_input}", req_id=req_id)
                response = _handle_web_command(user_input, state, req_id)
                if not send_sse("message", {"text": response}):
                    return
                send_sse("done", {})
                return

            # Normal turn
            t0_total = time.time()
            if not send_sse("status", {"text": "正在分析上下文...", "type": "llm"}):
                return

            messages = build_messages(system_prompt, state, user_input, config, req_id)

            # Run tool loop with streaming
            response = run_tool_loop(messages, system_prompt, state, config, registry, logger, req_id, send_sse)
            state.add_assistant_message(response)

            elapsed_total = time.time() - t0_total
            _log(f"Turn complete in {elapsed_total:.1f}s: {len(response)} chars response", req_id=req_id)

            send_sse("message", {"text": response})
            send_sse("done", {})

        except Exception as e:
            _log(f"Chat error: {e}\n{traceback.format_exc()}", "ERROR", req_id)
            try:
                send_sse("error", {"text": str(e)})
            except Exception:
                pass
        finally:
            # Clean up cancel flag
            with _cancel_lock:
                _cancel_flags.pop(req_id, None)

    def _handle_api_cancel(self):
        """Handle POST /api/cancel - cancel the current in-flight LLM request."""
        content_length = int(self.headers.get("Content-Length", 0))
        body = b""
        if content_length > 0:
            body = self.rfile.read(content_length)

        req_id = ""
        try:
            data = _json.loads(body)
            req_id = data.get("request_id", "")
        except Exception:
            pass

        # If no specific request, cancel all
        with _cancel_lock:
            if req_id:
                if req_id in _cancel_flags:
                    _cancel_flags[req_id] = True
                    _log(f"Cancel flag set for request {req_id[:8]}", "INFO")
                else:
                    # Try partial match
                    for key in list(_cancel_flags.keys()):
                        if key.startswith(req_id):
                            _cancel_flags[key] = True
                            _log(f"Cancel flag set for request {key[:8]}", "INFO")
            else:
                for key in _cancel_flags:
                    _cancel_flags[key] = True
                _log(f"Cancel flag set for all {len(_cancel_flags)} active requests", "INFO")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self._send_cors()
        self.end_headers()
        self.wfile.write(_json.dumps({"status": "cancelled"}, ensure_ascii=False).encode("utf-8"))


    def _handle_api_new_chat(self):
        """Handle POST /api/chat/new - create a brand-new conversation session."""
        _log("Creating new conversation session", "INFO")
        old_state = _server_state.get("state")

        # Save old conversation to history before resetting
        saved_id = None
        if old_state and len([m for m in old_state.messages if m["role"] != "system"]) >= 2:
            saved_id = _save_conversation(old_state)
            _log(f"Saved previous conversation: {saved_id}")

        # Also save to memory store for auto-summary
        memory_store = _server_state.get("memory_store")
        if old_state and memory_store:
            non_system = [m for m in old_state.messages if m["role"] != "system"]
            if len(non_system) >= 4:
                try:
                    from Offlineagent.memory_layer.memory_summarizer import summarize_conversation
                    # Offload memory summarization to background thread
                    # so HTTP response returns immediately for large conversations
                    _captured_msgs = list(non_system)
                    _captured_llm = _server_state["llm_chat_fn"]
                    _captured_store = memory_store
                    def _bg_summarize():
                        try:
                            from Offlineagent.memory_layer.memory_summarizer import summarize_conversation
                            _summary = summarize_conversation(_captured_msgs, _captured_llm)
                            if _summary:
                                _captured_store.add(_summary)
                                _log("Saved memory from previous session (bg)")
                        except Exception as e2:
                            _log(f"Memory save skipped (bg): {e2}", "WARN")
                    t = threading.Thread(target=_bg_summarize, daemon=True)
                    t.start()
                except Exception as e:
                    _log(f"Memory save skipped: {e}", "WARN")
        _server_state["state"] = None
        get_or_create_state()
        _log("New conversation session created")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self._send_cors()
        self.end_headers()
        self.wfile.write(_json.dumps({
            "status": "created",
            "message": "New conversation session created.",
            "saved_id": saved_id,
        }, ensure_ascii=False).encode("utf-8"))


    def _handle_api_chat_list(self):
        """Handle GET /api/chat/list - list saved conversations."""
        try:
            convs = _list_conversations()
        except Exception as e:
            _log(f"Failed to list conversations: {e}", "ERROR")
            convs = []
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self._send_cors()
        self.end_headers()
        self.wfile.write(_json.dumps({"conversations": convs}, ensure_ascii=False).encode("utf-8"))

    def _handle_api_chat_switch(self, conv_id: str):
        """Handle POST /api/chat/switch/<id> - switch to a saved conversation."""
        _log(f"Switching to conversation: {conv_id}", "INFO")

        # Save current conversation first
        old_state = _server_state.get("state")
        if old_state and len([m for m in old_state.messages if m["role"] != "system"]) >= 2:
            _save_conversation(old_state)

        # Load the requested conversation
        data = _load_conversation(conv_id)
        if not data:
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self._send_cors()
            self.end_headers()
            self.wfile.write(_json.dumps({"error": "Conversation not found"}, ensure_ascii=False).encode("utf-8"))
            return

        # Restore state
        from Offlineagent.orchestrator.state_manager import StateManager
        new_state = StateManager.from_dict(data["state"])
        _server_state["state"] = new_state
        _log(f"Switched to conversation: {conv_id} ({data['title']})")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self._send_cors()
        self.end_headers()
        self.wfile.write(_json.dumps({
            "status": "switched",
            "id": conv_id,
            "title": data["title"],
            "message_count": data["message_count"],
        }, ensure_ascii=False).encode("utf-8"))

    def _handle_api_status(self):
        """Handle GET /api/status."""
        state = get_or_create_state()
        config = _server_state["config"]
        skills = _server_state["skills"]
        registry = _server_state["registry"]

        status = state.status_summary(_server_state["system_prompt"])
        status["skills_count"] = len(skills)
        status["tools"] = registry.names()
        status["model"] = _get_active_model_name()
        status["llm_url"] = config.get("llm", {}).get("url", "unknown")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self._send_cors()
        self.end_headers()
        self.wfile.write(_json.dumps(status, ensure_ascii=False).encode("utf-8"))

    def _handle_api_files(self, parsed):
        """Handle GET /api/files?path=... or /api/files?read=..."""
        from Offlineagent.tool_layer.file_handler import list_directory, read_file_content
        qs = parse_qs(parsed.query)
        dir_path = qs.get("path", [None])[0]
        read_path = qs.get("read", [None])[0]
        if read_path:
            result = read_file_content(read_path)
            self.send_response(200 if result.get("type") != "error" else 404)
            self.send_header("Content-Type", "application/json")
            self._send_cors()
            self.end_headers()
            self.wfile.write(_json.dumps(result, ensure_ascii=False).encode("utf-8"))
            return
        result = list_directory(dir_path) if dir_path else list_directory(str(_AGENT_DIR))
        self.send_response(200 if "error" not in result else 404)
        self.send_header("Content-Type", "application/json")
        self._send_cors()
        self.end_headers()
        self.wfile.write(_json.dumps(result, ensure_ascii=False).encode("utf-8"))

    def _handle_api_upload(self):
        """Handle POST /api/upload - JSON or multipart file upload."""
        from Offlineagent.tool_layer.file_handler import read_file_content, ALL_SUPPORTED
        import tempfile, re, os as _os

        content_type = self.headers.get("Content-Type", "")

        if "application/json" in content_type:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                data = _json.loads(body)
                file_path = data.get("path", "")
                if not file_path:
                    self._send_json_error(400, "Missing path field")
                    return
                result = read_file_content(file_path)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self._send_cors()
                self.end_headers()
                self.wfile.write(_json.dumps(result, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self._send_json_error(400, str(e))
            return

        if "multipart/form-data" not in content_type:
            self._send_json_error(400, "Expected multipart/form-data or application/json")
            return

        boundary = None
        for part in content_type.split(";"):
            part = part.strip()
            if part.startswith("boundary="):
                boundary = part[9:].strip('"')
                break
        if not boundary:
            self._send_json_error(400, "No boundary in Content-Type")
            return

        content_length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(content_length)
        boundary_bytes = ("--" + boundary).encode("utf-8")

        parts = raw.split(boundary_bytes)[1:]
        for part in parts:
            if part.startswith(b"--"):
                break
            part = part.lstrip(b"\r\n").rstrip(b"\r\n--")
            if not part:
                continue
            header_end = part.find(b"\r\n\r\n")
            if header_end == -1:
                continue
            headers_raw = part[:header_end].decode("utf-8", errors="replace")
            body_bytes = part[header_end + 4:]
            filename = None
            for hline in headers_raw.split("\r\n"):
                if "filename=" in hline:
                    fname_match = re.search(r'filename="([^"]*)"', hline)
                    if fname_match:
                        filename = fname_match.group(1)
                    break
            if not filename or not body_bytes:
                continue
            ext = _os.path.splitext(filename)[1].lower()
            if ext not in ALL_SUPPORTED:
                self._send_json_error(400, f"Unsupported file type: {ext}")
                return
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp.write(body_bytes)
                tmp_path = tmp.name
            try:
                result = read_file_content(tmp_path)
                result["filename"] = filename
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self._send_cors()
                self.end_headers()
                self.wfile.write(_json.dumps(result, ensure_ascii=False).encode("utf-8"))
            finally:
                _os.unlink(tmp_path)
            return
        self._send_json_error(400, "No file found in upload")

    def _handle_api_logs(self):
        """Handle GET /api/logs?lines=50 - return recent log lines."""
        import glob as _glob
        try:
            log_files = sorted(_glob.glob(str(LOG_DIR / "agent_*.log")), reverse=True)
            if not log_files:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self._send_cors()
                self.end_headers()
                self.wfile.write(_json.dumps({"logs": [], "file": None}).encode("utf-8"))
                return

            lines_str = parse_qs(urlparse(self.path).query).get("lines", ["100"])[0]
            max_lines = min(int(lines_str), 500)

            all_lines = []
            for lf in log_files[:3]:
                with open(lf, "r", encoding="utf-8", errors="replace") as f:
                    all_lines.extend(f.readlines())
                if len(all_lines) >= max_lines:
                    break

            recent = [l.strip() for l in all_lines[-max_lines:]]
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._send_cors()
            self.end_headers()
            self.wfile.write(_json.dumps({
                "logs": recent,
                "file": Path(log_files[0]).name if log_files else None,
            }, ensure_ascii=False).encode("utf-8"))
        except Exception as e:
            self._send_json_error(500, str(e))

    def _send_json_error(self, code: int, message: str):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self._send_cors()
        self.end_headers()
        self.wfile.write(_json.dumps({"error": message}, ensure_ascii=False).encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/chat/list":
            self._handle_api_chat_list()
        elif path == "/api/status":
            self._handle_api_status()
        elif path == "/api/files":
            self._handle_api_files(parsed)
        elif path == "/api/logs":
            self._handle_api_logs()
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
            self._handle_api_new_chat()
        elif path == "/api/upload":
            self._handle_api_upload()
        elif path == "/api/cancel":
            self._handle_api_cancel()
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error": "Not Found"}')


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
        from Offlineagent.prompt_layer.skill_loader import get_skill_body
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
            f"Tokens: {status['tokens_estimate']}/{status['max_tokens']} ({status['usage_percent']}%), "
            f"Turns: {status['turns']}/{status['max_history']}, "
            f"Model: {_get_active_model_name()}"
        )

    elif command == "/logs":
        import glob as _glob
        log_files = sorted(_glob.glob(str(LOG_DIR / "agent_*.log")), reverse=True)
        if not log_files:
            return "No log files found in " + str(LOG_DIR)
        with open(log_files[0], "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        recent = [l.strip() for l in lines[-20:]]
        return f"Log file: {Path(log_files[0]).name}\nLast 20 lines:\n" + "\n".join(recent)

    elif command == "/clear":
        state.clear_history()
        _log("Conversation history cleared", req_id=req_id)
        return "Conversation history cleared."

    elif command == "/config":
        llm = _server_state["config"].get("llm", {})
        return f"Model: {_get_active_model_name()}, URL: {llm.get('url')}"

    elif command == "/exit":
        memory_store = _server_state["memory_store"]
        if memory_store:
            non_system = [m for m in state.messages if m["role"] != "system"]
            if len(non_system) >= 4:
                from Offlineagent.memory_layer.memory_summarizer import summarize_conversation
                summary = summarize_conversation(non_system, _server_state["llm_chat_fn"])
                if summary:
                    memory_store.add(summary)
        state.clear_history()
        _log("Session saved and history cleared", req_id=req_id)
        return "Session saved. History cleared."

    else:
        return f"Unknown command: {command}. Type /help for list."


# -- Main entry --

def main():
    import argparse
    import signal

    parser = argparse.ArgumentParser(description="OfflineAgent Web Server")
    parser.add_argument("-p", "--port", type=int, default=None, help="Server port")
    parser.add_argument("-H", "--host", default=None, help="Server host")
    parser.add_argument("-d", "--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    print("OfflineAgent Web Server")
    print("=" * 50)

    _log("=== OfflineAgent Server Starting ===")
    init_agent()

    config = _server_state["config"]
    server_cfg = config.get("server", {})
    host = args.host or server_cfg.get("host", "0.0.0.0")
    port = args.port or server_cfg.get("port", 8999)

    server = ThreadingHTTPServer((host, port), AgentHandler)
    # Set a timeout so serve_forever can be interrupted more quickly
    server.timeout = 0.5

    _log(f"Server running at http://localhost:{port}")
    print(f"\n  Server running at http://localhost:{port}")
    print(f"  Frontend: http://localhost:{port}/")
    print(f"  Logs:     {LOG_DIR}")
    print(f"  Press Ctrl+C to stop.\n")

    # Track shutdown state
    shutdown_requested = False

    def _handle_shutdown(signum, frame):
        nonlocal shutdown_requested
        if shutdown_requested:
            _log("Force shutdown (double Ctrl+C)", "WARN")
            import os as _os
            _os._exit(0)
        shutdown_requested = True
        _log("Server shutdown requested (Ctrl+C) - finishing active requests...")
        print("\n  Shutting down... (press Ctrl+C again to force)")

    signal.signal(signal.SIGINT, _handle_shutdown)
    signal.signal(signal.SIGTERM, _handle_shutdown)

    try:
        while not shutdown_requested:
            server.handle_request()
    except KeyboardInterrupt:
        _log("Server shutdown via KeyboardInterrupt")
    finally:
        _log("Server stopping...")
        try:
            server.server_close()
        except Exception:
            pass
        _log("Server stopped")

    # Flush logger
    if _server_state["logger"]:
        try:
            _server_state["logger"].write_log_file()
        except Exception:
            pass


if __name__ == "__main__":
    main()
