#!/usr/bin/env python3
"""
server.py - OfflineAgent Web Server

Starts an HTTP server on http://localhost:8999 (default) that serves:
  - Static frontend (index.html, style.css, app.js)
  - POST /api/chat  - Send message, get SSE streaming response
  - GET  /api/status - Current agent status
  - POST /api/config - Reload config (TODO)

Zero external dependencies: uses only Python stdlib.
"""

import sys
import os
import json as _json
import time
from pathlib import Path
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


def init_agent():
    """Initialize the agent for web serving."""
    base_dir = _AGENT_DIR
    config_path = base_dir / "config.yaml"

    config = load_config(config_path)
    _server_state["config"] = config

    # Logger
    log_dir = base_dir / "memory"
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = AgentLogger(log_dir)
    # logger is initialized via constructor
    _server_state["logger"] = logger

    # Skills
    skills = load_all_skills(config, base_dir)
    _server_state["skills"] = skills

    # System prompt
    agent_cfg = config.get("agent", {})
    memory_store = None
    if agent_cfg.get("memory", {}).get("enabled", True):
        memory_store = MemoryStore(base_dir / "memory")

    recent_memories = memory_store.get_recent(agent_cfg.get("memory", {}).get("max_recent", 3)) if memory_store else None
    system_prompt, _ = build_system_prompt(config, skills, base_dir, recent_memories=recent_memories)
    _server_state["system_prompt"] = system_prompt
    _server_state["memory_store"] = memory_store

    # LLM client
    llm_chat_fn = create_llm_chat_fn(config)
    _server_state["llm_chat_fn"] = llm_chat_fn

    # Tools
    registry = ToolRegistry()
    register_tools(registry, config, base_dir)
    _server_state["registry"] = registry

    print(f"  Agent initialized: {len(skills)} skills, {len(registry.names())} tools")


def get_or_create_state() -> StateManager:
    """Get or create a per-session state manager."""
    if _server_state["state"] is None:
        agent_cfg = _server_state["config"].get("agent", {})
        _server_state["state"] = StateManager(
            max_history=agent_cfg.get("max_history", 20),
            max_tokens=agent_cfg.get("max_tokens_estimate", 8000),
        )
    return _server_state["state"]


def build_messages(system_prompt: str, state: StateManager, user_input: str, config: dict) -> list[dict]:
    """Build the full message list for the LLM API call."""
    state.add_user_message(user_input)

    model = config.get("llm", {}).get("model", "")
    messages = state.get_history_for_api(system_prompt)

    # Pre-check for unsupported content
    stripped = check_before_send(model, [m for m in messages if m["role"] != "system"], _AGENT_DIR / "memory")
    if stripped:
        non_system = [m for m in state.messages if m["role"] != "system"]
        state.messages = [m for m in state.messages if m["role"] == "system"] + stripped
        messages = state.get_history_for_api(system_prompt)

    # Compression check
    agent_cfg = config.get("agent", {})
    compression_cfg = agent_cfg.get("compression", {})
    if compression_cfg.get("enabled", True):
        if state.needs_compression(compression_cfg.get("trigger_ratio", 0.7)):
            compress_history(
                state, system_prompt, _server_state["llm_chat_fn"],
                keep_recent=compression_cfg.get("keep_recent", 2),
            )
            messages = state.get_history_for_api(system_prompt)

    return messages


def run_tool_loop(messages: list[dict], system_prompt: str, state: StateManager,
                  config: dict, registry: ToolRegistry, logger, status_callback=None) -> str:
    """Run the tool execution loop, yielding status updates via a callback.

    This is a simplified version for web streaming. It runs synchronously
    but can be wrapped for SSE output.
    """
    llm_fn = _server_state["llm_chat_fn"]
    max_iterations = 10
    iterations = 0
    final_parts = []
    tools_cfg = config.get("tools", {})

    while iterations < max_iterations:
        iterations += 1

        if status_callback:
            status_callback("status", {"text": f"正在调用模型 (第{iterations}轮)...", "type": "llm"})

        response = llm_fn(messages)
        if not response:
            return "[Error] No response from LLM."

        if not has_tool_calls(response):
            final_parts.append(response)
            break

        tool_calls = parse_tool_calls(response)
        text_part = extract_text_without_tools(response)
        if text_part:
            final_parts.append(text_part)

        if not tool_calls:
            final_parts.append(response)
            break

        for tc in tool_calls:
            tool_def = registry.get(tc.name)
            if not tool_def:
                state.add_tool_result(
                    f"[Error] Unknown tool: {tc.name}. Available: {', '.join(registry.names())}"
                )
                continue

            # Web mode: skip confirmation dialogs, auto-approve safe tools
            try:
                if status_callback:
                    status_callback("status", {"text": f"正在执行: {tc.name}", "type": "tool", "tool": tc.name})

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

        # Refresh messages with tool results
        messages = state.get_history_for_api(system_prompt)
    else:
        if status_callback:
            status_callback("status", {"text": "已达到最大工具调用次数，生成最终回复...", "type": "warn"})
        final_parts.append("[Note: Max tool iterations reached.]")

    return "\n\n".join(p for p in final_parts if p)


# -- HTTP Request Handler --

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


class AgentHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the OfflineAgent web server."""

    def log_message(self, format, *args):
        """Suppress default stderr logging."""
        pass

    def _send_cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _serve_static(self, path: str):
        """Serve a static file from frontend/."""
        if path == "/" or path == "":
            path = "/index.html"

        # Map URL paths to frontend/ directory
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

        # SSE response
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self._send_cors()
        self.end_headers()

        def send_sse(event: str, data: str):
            """Send an SSE event."""
            msg = f"event: {event}\ndata: {_json.dumps(data, ensure_ascii=False)}\n\n"
            try:
                self.wfile.write(msg.encode("utf-8"))
                self.wfile.flush()
            except Exception:
                pass

        try:
            state = get_or_create_state()
            config = _server_state["config"]
            system_prompt = _server_state["system_prompt"]
            registry = _server_state["registry"]
            logger = _server_state["logger"]

            # Handle built-in commands
            if user_input.startswith("/"):
                response = _handle_web_command(user_input, state)
                send_sse("message", {"text": response})
                send_sse("done", {})
                return

            # Normal turn
            send_sse("status", {"text": "正在分析上下文...", "type": "llm"})
            messages = build_messages(system_prompt, state, user_input, config)

            # Run tool loop with streaming
            response = run_tool_loop(messages, system_prompt, state, config, registry, logger, send_sse)
            state.add_assistant_message(response)

            send_sse("message", {"text": response})
            send_sse("done", {})

        except Exception as e:
            send_sse("error", {"text": str(e)})

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

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self._send_cors()
        self.end_headers()
        self.wfile.write(_json.dumps(status, ensure_ascii=False).encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/status":
            self._handle_api_status()
        else:
            self._serve_static(path)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/chat":
            self._handle_api_chat()
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error": "Not Found"}')


def _handle_web_command(cmd: str, state: StateManager) -> str:
    """Handle built-in commands for the web interface."""
    parts = cmd.split(maxsplit=1)
    command = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if command == "/help":
        return """Commands: /help /skills /skill <name> /tools /status /memory /clear /config /exit"""

    elif command == "/skills":
        skills = _server_state["skills"]
        if not skills:
            return "No skills loaded."
        lines = []
        for s in skills:
            lines.append(f"[{s.source}] {s.name}: {s.short_desc}")
        return "\n".join(lines)

    elif command == "/tools":
        tools = _server_state["registry"]
        return f"Available tools: {', '.join(tools.names())}"

    elif command == "/status":
        status = state.status_summary(_server_state["system_prompt"])
        return f"Tokens: {status['tokens_estimate']}/{status['max_tokens']} ({status['usage_percent']}%), Turns: {status['turns']}/{status['max_history']}"

    elif command == "/clear":
        state.clear_history()
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
        return "Session saved. History cleared."

    else:
        return f"Unknown command: {command}. Type /help for list."


# -- Main entry --

def main():
    import argparse

    parser = argparse.ArgumentParser(description="OfflineAgent Web Server")
    parser.add_argument("-p", "--port", type=int, default=None, help="Server port")
    parser.add_argument("-H", "--host", default=None, help="Server host")
    args = parser.parse_args()

    # Init agent first
    print("OfflineAgent Web Server")
    print("=" * 50)
    init_agent()

    config = _server_state["config"]
    server_cfg = config.get("server", {})
    host = args.host or server_cfg.get("host", "0.0.0.0")
    port = args.port or server_cfg.get("port", 8999)

    server = HTTPServer((host, port), AgentHandler)
    print(f"\n  Server running at http://localhost:{port}")
    print(f"  Frontend: http://localhost:{port}/")
    print(f"  Press Ctrl+C to stop.\n")

    try:
        server.serve_forever(poll_interval=0.1)
    except KeyboardInterrupt:
        print("\n  Shutting down...")
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
