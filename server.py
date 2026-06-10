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
    """Call LLM with a timeout. Returns error string on timeout.

    Uses a daemon thread so the main thread can detect timeout and
    mark the request as cancelled. This prevents hanging when the
    LLM server is slow or unresponsive.
    """
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
        _log(f"LLM call timed out after {timeout_sec}s", "WARN", req_id)
        with _cancel_lock:
            _cancel_flags.pop(req_id, None)
        return f"[Timeout] LLM did not respond within {timeout_sec} seconds."

    if result_container["error"]:
        _log(f"LLM call failed: {result_container['error']}", "ERROR", req_id)
        return f"[LLM Error] {result_container['error']}"

    return result_container["response"] or ""


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
    llm_chat_fn = create_llm_chat_fn(config)
    _server_state["llm_chat_fn"] = llm_chat_fn

    # Tools
    registry = ToolRegistry()
    register_tools(registry, config, base_dir)
    _server_state["registry"] = registry

    _log(f"Agent initialized: {len(skills)} skills, {len(registry.names())} tools")


def get_or_create_state() -> StateManager:
    """Get or create a per-session state manager."""
    if _server_state["state"] is None:
        agent_cfg = _server_state["config"].get("agent", {})
        _server_state["state"] = StateManager(
            max_history=agent_cfg.get("max_history", 20),
            max_tokens=agent_cfg.get("max_tokens_estimate", 8000),
        )
        _log("State manager created (new session)")
    return _server_state["state"]


def build_messages(system_prompt: str, state: StateManager, user_input: str, config: dict, req_id: str = "") -> list[dict]:
    """Build the full message list for the LLM API call."""
    state.add_user_message(user_input)

    model = config.get("llm", {}).get("model", "")
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
    """Run the tool execution loop, yielding status updates via a callback."""
    llm_fn = _server_state["llm_chat_fn"]
    llm_timeout = config.get("llm", {}).get("timeout", 60)
    max_iterations = 10
    iterations = 0
    final_parts = []
    model = config.get("llm", {}).get("model", "unknown")

    while iterations < max_iterations:
        # Check cancellation
        if _is_cancelled(req_id):
            _log(f"Request cancelled by user at iteration {iterations}", "INFO", req_id)
            return "[Cancelled] Request was cancelled by user."

        iterations += 1
        _log(f"Tool loop iteration {iterations}/{max_iterations}, messages={len(messages)}", req_id=req_id)

        if status_callback:
            status_callback("status", {"text": f"正在调用模型 (第{iterations}轮)...", "type": "llm"})

        t0 = time.time()
        response = _llm_call_with_timeout(llm_fn, messages, llm_timeout, req_id)

        if _is_cancelled(req_id):
            _log(f"Request cancelled during LLM call at iteration {iterations}", "INFO", req_id)
            return "[Cancelled] Request was cancelled by user."

        elapsed = time.time() - t0
        resp_len = len(response) if response else 0
        _log(f"LLM response in {elapsed:.1f}s: {resp_len} chars, has_tool_calls={has_tool_calls(response) if response else False}", req_id=req_id)

        if not response:
            _log("LLM returned empty response", "WARN", req_id)
            return "[Error] No response from LLM."

        if response.startswith("[Timeout]") or response.startswith("[LLM Error]"):
            _log(f"LLM error response: {response[:100]}", "ERROR", req_id)
            return response

        if not has_tool_calls(response):
            _log(f"No tool calls detected, final response: {resp_len} chars", req_id=req_id)
            final_parts.append(response)
            break

        tool_calls = parse_tool_calls(response)
        text_part = extract_text_without_tools(response)
        if text_part:
            final_parts.append(text_part)

        if not tool_calls:
            _log("has_tool_calls=True but parse returned empty, treating as text", req_id=req_id)
            final_parts.append(response)
            break

        _log(f"Parsed {len(tool_calls)} tool call(s): {[tc.name for tc in tool_calls]}", req_id=req_id)

        for tc in tool_calls:
            if _is_cancelled(req_id):
                return "[Cancelled] Request was cancelled by user."

            tool_def = registry.get(tc.name)
            if not tool_def:
                err = f"[Error] Unknown tool: {tc.name}. Available: {', '.join(registry.names())}"
                _log(f"Unknown tool requested: {tc.name}", "WARN", req_id)
                state.add_tool_result(err)
                continue

            try:
                if status_callback:
                    status_callback("status", {"text": f"正在执行: {tc.name}", "type": "tool", "tool": tc.name})

                _log(f"Executing tool: {tc.name}({str(tc.params)[:100]})", req_id=req_id)
                t0_tool = time.time()
                result = registry.dispatch(tc.name, tc.params)
                tool_elapsed = time.time() - t0_tool
                result_str = str(result)
                _log(f"Tool {tc.name} done in {tool_elapsed:.2f}s: {len(result_str)} chars", req_id=req_id)
                state.add_tool_result(result_str)
                if logger:
                    logger.tool_call(tc.name, str(tc.params)[:100], True)
            except Exception as e:
                error_msg = f"[Error] Tool {tc.name} failed: {e}"
                _log(f"Tool {tc.name} failed: {e}", "ERROR", req_id)
                state.add_tool_result(error_msg)
                if logger:
                    logger.tool_call(tc.name, str(tc.params)[:100], False, str(e)[:100])

        # Refresh messages with tool results
        messages = state.get_history_for_api(system_prompt)
    else:
        _log(f"Reached max iterations ({max_iterations}), generating final response", "WARN", req_id)
        if status_callback:
            status_callback("status", {"text": "已达到最大工具调用次数，生成最终回复...", "type": "warn"})
        final_parts.append("[Note: Max tool iterations reached.]")

    result = "\n\n".join(p for p in final_parts if p)
    _log(f"Tool loop complete: {len(result)} chars final response", req_id=req_id)
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
        memory_store = _server_state.get("memory_store")
        if old_state and memory_store:
            non_system = [m for m in old_state.messages if m["role"] != "system"]
            if len(non_system) >= 4:
                try:
                    from Offlineagent.memory_layer.memory_summarizer import summarize_conversation
                    summary = summarize_conversation(non_system, _server_state["llm_chat_fn"])
                    if summary:
                        memory_store.add(summary)
                        _log("Saved memory from previous session")
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
            "message": "New conversation session created."
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
        status["model"] = config.get("llm", {}).get("model", "unknown")
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

        if path == "/api/status":
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
            f"Model: {_server_state['config'].get('llm', {}).get('model', 'unknown')}"
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
        return f"Model: {llm.get('model')}, URL: {llm.get('url')}"

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

    server = HTTPServer((host, port), AgentHandler)
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
