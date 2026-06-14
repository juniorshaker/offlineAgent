#!/usr/bin/env python3
"""
agent.py - OfflineAgent CLI Entry Point

Usage:
    python agent.py              # Interactive mode
    python agent.py -c my.yaml   # Custom config
    python agent.py -p .\\python\\python.exe  # Use portable Python
"""

import sys
import os
from pathlib import Path

# -- Path setup --
# Ensure the parent of Offlineagent/ is on sys.path so package imports work.
_THIS_FILE = Path(__file__).resolve()
_AGENT_DIR = _THIS_FILE.parent          # .../Offlineagent/
_PARENT_DIR = _AGENT_DIR.parent         # .../Ai-Fields/

if str(_PARENT_DIR) not in sys.path:
    sys.path.insert(0, str(_PARENT_DIR))

# -- Basic Python version check --
if sys.version_info < (3, 8):
    print("OfflineAgent requires Python 3.8+")
    sys.exit(1)

# -- Imports --
import argparse
import json as _json

# Vendor: urllib-based requests compat layer (zero pip)
from Offlineagent.vendor import requests

# Prompt layer
from Offlineagent.prompt_layer.skill_loader import load_all_skills
from Offlineagent.prompt_layer.system_prompt import build_system_prompt

# Orchestrator
from Offlineagent.orchestrator.state_manager import StateManager
from Offlineagent.orchestrator.chat_loop import ChatLoop

# Tool layer
from Offlineagent.tool_layer.tool_registry import ToolRegistry
from Offlineagent.tool_layer import file_tools
from Offlineagent.tool_layer import shell_tools
from Offlineagent.tool_layer import document_tools
from Offlineagent.tool_layer import browser_tools
from Offlineagent.tool_layer import db_tools

# Memory layer
from Offlineagent.memory_layer.memory_store import MemoryStore

# Metrics
from Offlineagent.metrics.logger import AgentLogger

# Evaluation
from Offlineagent.evaluation.config_validator import run_self_check


# -- Config loading --

def load_config(config_path: Path) -> dict:
    """Load YAML config with basic parsing (no PyYAML dependency)."""
    if not config_path.exists():
        print(f"[ERROR] Config file not found: {config_path}")
        sys.exit(1)

    raw = config_path.read_text(encoding="utf-8")
    return _parse_simple_yaml(raw)


def _parse_simple_yaml(raw: str) -> dict:
    """Parse a simple YAML structure into a nested dict.

    Supports:
    - Top-level scalar keys: key: value
    - Nested dicts via indentation (2-space)
    - Lists via [a, b] or indented - a
    - Comments starting with #
    """
    result = {}
    lines = raw.split("\n")

    # First pass: find top-level keys and their line ranges
    top_keys = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # Top-level key: no leading whitespace, has colon
        if not line.startswith((" ", "\t")) and ":" in stripped:
            key = stripped.split(":", 1)[0].strip()
            top_keys.append((key, i))

    # Parse each top-level section
    for idx, (key, start_line) in enumerate(top_keys):
        end_line = top_keys[idx + 1][1] if idx + 1 < len(top_keys) else len(lines)
        section_lines = lines[start_line:end_line]

        first = section_lines[0].strip()
        after_colon = first.split(":", 1)[1].strip()

        if after_colon:
            # Scalar value at top level
            result[key] = _parse_scalar(after_colon)
        else:
            # Nested section
            sub_lines = []
            for sl in section_lines[1:]:
                if sl.strip() and not sl.strip().startswith("#"):
                    sub_lines.append(sl)
            if sub_lines:
                result[key] = _parse_nested(sub_lines)

    return result


def _parse_scalar(val: str):
    """Parse a YAML scalar value."""
    val = val.strip()
    # Strip inline comments (e.g. "value  # comment" -> "value")
    ci = val.find("  #")
    if ci != -1:
        val = val[:ci].strip()
    if val == "true":
        return True
    if val == "false":
        return False
    if val == "{}" or val == "":
        return {}
    if val == "[]":
        return []
    if val.startswith("[") and val.endswith("]"):
        inner = val[1:-1]
        return [v.strip().strip("'\"") for v in inner.split(",") if v.strip()]
    try:
        return int(val)
    except ValueError:
        pass
    try:
        return float(val)
    except ValueError:
        pass
    return val.strip("'\"")


def _detect_base_indent(lines: list) -> int:
    """Detect the base indent level from non-empty, non-comment lines."""
    for line in lines:
        s = line.rstrip("\n")
        if s.strip() and not s.strip().startswith("#"):
            return len(s) - len(s.lstrip())
    return 0


def _parse_value_lines(lines: list) -> object:
    """Parse a list of indented lines into a dict, list, or scalar.

    The lines should all be at a deeper indent than the parent key.
    """
    if not lines:
        return {}

    base_indent = _detect_base_indent(lines)

    # Check if this is purely a list (all non-empty lines start with '- ')
    all_list = all(
        not line.strip() or line.strip().startswith("#") or
        (len(line) - len(line.lstrip()) == base_indent and line.lstrip().startswith("- "))
        for line in lines
    )

    if all_list:
        items = []
        for line in lines:
            s = line.strip()
            if s.startswith("- "):
                items.append(_parse_scalar(s[2:].strip()))
        return items

    # Check if there are sub-keys at base_indent level
    # A sub-key looks like: "    keyname: value" at the base_indent
    sub_keys = []
    for j, line in enumerate(lines):
        cur_indent = len(line) - len(line.lstrip())
        s = line.strip()
        if cur_indent == base_indent and s and not s.startswith(("#", "-")) and ":" in s.split("#")[0]:
            key_part = s.split(":", 1)[0].strip()
            if key_part:
                sub_keys.append((key_part, j))

    # If no clear sub-keys, try parsing as list or scalar
    if not sub_keys:
        # Could be a compact list or single value
        return {}

    result = {}
    for idx, (sub_key, start) in enumerate(sub_keys):
        end = sub_keys[idx + 1][1] if idx + 1 < len(sub_keys) else len(lines)

        # Get the first line of this sub_key
        first_line = lines[start].strip()
        after_colon = first_line.split(":", 1)[1].strip()

        if after_colon:
            result[sub_key] = _parse_scalar(after_colon)
        else:
            # Collect deeper lines for this sub_key
            deeper = []
            for si in range(start + 1, end):
                dl = lines[si]
                cur_indent = len(dl) - len(dl.lstrip())
                if cur_indent > base_indent and dl.strip() and not dl.strip().startswith("#"):
                    deeper.append(dl)

            if deeper:
                result[sub_key] = _parse_value_lines(deeper)
            else:
                result[sub_key] = {}

    return result


def _parse_nested(lines: list) -> dict:
    """Parse indented YAML lines into a nested dict.

    This is a wrapper that delegates to _parse_value_lines after detecting
    the base indent.
    """
    if not lines:
        return {}

    result = _parse_value_lines(lines)
    if isinstance(result, dict):
        return result
    # If it returned a list or other, wrap it
    return {"_value": result}


# -- LLM Client --


def parse_llm_response_body(body: dict, logger=None) -> str:
    """Parse an LLM API response body into a text string.

    Handles five scenarios:
    A. Normal content string -> returned as-is
    B. OpenAI-style tool_calls array (content is null) -> convert to XML
    C. Thinking/reasoning models (reasoning_content present)
    D. Empty content with finish_reason -> diagnostic error
    E. Delta content (streaming aggregation)

    Guaranteed to never return an empty string or None.
    """
    import json as _json_lib

    if not isinstance(body, dict):
        return str(body) if body else "[LLM Error] Non-dict response body"

    if "choices" in body and len(body["choices"]) > 0:
        choice = body["choices"][0]
        msg = choice.get("message", {})
        result_text = msg.get("content") or ""

        # --- Scenario B: tool_calls array ---
        tool_calls_arr = msg.get("tool_calls", [])
        if (not result_text) and tool_calls_arr:
            xml_parts = []
            for tc in tool_calls_arr:
                fn = tc.get("function", {})
                name = fn.get("name", "unknown")
                args_str = fn.get("arguments", "{}")
                try:
                    args = _json_lib.loads(args_str) if isinstance(args_str, str) else args_str
                except Exception:
                    args = {}
                params_xml = "".join(
                    f'<param name="{k}">{v}</param>' for k, v in args.items()
                )
                xml_parts.append(f"<tool_call><name>{name}</name>{params_xml}</tool_call>")
            result_text = "\n".join(xml_parts)

        # --- Scenario C: reasoning_content ---
        if (not result_text) and msg.get("reasoning_content"):
            result_text = str(msg["reasoning_content"])

        # --- Scenario E: delta.content ---
        if (not result_text) and msg.get("delta"):
            delta_content = msg["delta"].get("content")
            if delta_content:
                result_text = str(delta_content)

        # --- Scenario D: empty content diagnostics ---
        if not result_text:
            finish_reason = choice.get("finish_reason", "unknown")
            if finish_reason == "length":
                result_text = "[LLM Error] Response truncated: max_tokens limit reached."
            elif finish_reason == "content_filter":
                result_text = "[LLM Error] Response blocked by content filter."
            elif finish_reason == "stop":
                result_text = "[LLM Error] Empty content with finish_reason=stop. Body: " + str(body)[:300]
            else:
                result_text = "[LLM Error] Empty content (finish_reason=" + str(finish_reason) + "). Body: " + str(body)[:300]

        return result_text or "[LLM Error] parse_llm_response_body produced empty result"

    elif "response" in body:
        val = body["response"]
        return val if val else "[LLM Error] Empty 'response' field in API response"

    elif "content" in body:
        val = body["content"]
        return val if val else "[LLM Error] Empty 'content' field in API response"

    elif "error" in body:
        err = body["error"]
        if isinstance(err, dict):
            return "[LLM Error] " + err.get("message", str(err))
        return "[LLM Error] " + str(err)

    else:
        dumped = _json_lib.dumps(body, ensure_ascii=False)
        return dumped if len(dumped) > 2 else "[LLM Error] Unrecognized response: " + dumped


def create_llm_chat_fn(config: dict, logger=None, token_tracker=None):
    """Create a closure that calls the configured LLM API.

    Supports two config formats:
    1. Multi-backend: llm.primary / llm.secondary with llm.active
    2. Legacy flat: llm.url / llm.model (auto-converted to default backend)

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
                    "timeout": be.get("timeout", 60),
                    "api_key": be.get("api_key", ""),
                }
        active = llm_cfg.get("active", "primary")
        if active not in backends:
            print(f"[WARN] active backend '{active}' not found, using first available")
            active = next(iter(backends.keys()))
    else:
        # Legacy flat format -- auto-convert
        backends = {
            "default": {
                "url": llm_cfg.get("url", ""),
                "model": llm_cfg.get("model", "Qwen3"),
                "timeout": llm_cfg.get("timeout", 60),
                "api_key": llm_cfg.get("api_key", ""),
            }
        }
        active = "default"
        # Update config in-place so downstream code sees consistent structure
        config["llm"] = {
            "active": "default",
            "default": backends["default"],
        }

    # -- Validate we have at least one backend --
    if not backends:
        print("[WARN] No LLM backends configured. Using echo mode.")
        def _echo(messages):
            if not messages:
                return "[Echo mode] No messages received."
            last_msg = messages[-1]
            last = last_msg.get("content", str(last_msg)) if isinstance(last_msg, dict) else str(last_msg)
            return f"[Echo mode] Received {len(messages)} messages. Last: {last[:200]}"
        return _echo, lambda name: "No backends configured", lambda: "echo", lambda: "No backends"

    # -- Connection test on startup against the active backend --
    be = backends[active]
    url = be["url"]
    model = be["model"]
    api_key = be["api_key"]
    timeout = be["timeout"]

    if url:
        print(f"[INFO] Testing LLM connection: {url} (backend={active}, model={model})...")
        try:
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            test_data = {"model": model, "messages": [{"role": "user", "content": "hi"}]}
            test_resp = requests.post(url, headers=headers,
                                    json=test_data, timeout=min(timeout, 15))
            if test_resp.status_code == 200:
                print(f"[INFO] LLM connection OK (status={test_resp.status_code})")
            else:
                print(f"[WARN] LLM responded with status={test_resp.status_code}")
                body_preview = test_resp.text()[:200] if callable(test_resp.text) else test_resp.text[:200]
                print(f"[WARN] Response preview: {body_preview}")
        except requests.ConnectionError as e:
            print(f"[FAIL] Cannot connect to LLM: {e}")
            print(f"[FAIL] URL: {url}")
            print(f"[FAIL] Check: (1) network/VPN (2) firewall (3) config.yaml llm.{active}.url")
        except Exception as e:
            print(f"[FAIL] LLM connection test failed: {e}")
    else:
        print(f"[WARN] Backend '{active}' has no URL. Using echo mode.")

    # -- Mutable state for active backend --
    _active = active

    def _get_active_model():
        return backends[_active]["model"]

    def _switch_backend(name: str) -> str:
        nonlocal _active
        if name not in backends:
            return f"Unknown backend: {name}. Available: {', '.join(backends.keys())}"
        _active = name
        be = backends[name]
        return f"Switched to backend: {name} ({be['model']} @ {be['url']})"

    def _list_backends() -> str:
        lines = []
        for name, be in backends.items():
            marker = " <- active" if name == _active else ""
            lines.append(f"  {name}: {be['model']} @ {be['url']}{marker}")
        return "\n".join(lines)

    def _llm_chat(messages: list[dict]) -> str:
        """Send messages to LLM and return response text."""
        be = backends[_active]
        url = be["url"]
        model = be["model"]
        api_key = be["api_key"]
        timeout = be["timeout"]

        if not url:
            return f"[Echo mode] Backend '{_active}' has no URL. Received {len(messages)} messages."

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        data = {"model": model, "messages": messages}

        try:
            resp = requests.post(url, headers=headers, json=data, timeout=timeout)
            # Try to parse JSON; handle empty/malformed responses
            try:
                body = resp.json()
            except Exception as json_err:
                raw_text = resp.text()[:500] if callable(resp.text) else (resp.text[:500] if resp.text else "(empty response)")
                return f"[LLM Error] JSON decode failed (HTTP {resp.status_code}): {json_err}. Raw: {raw_text}"

            # Handle non-200 status codes
            if resp.status_code != 200:
                err_detail = body if isinstance(body, str) else str(body)[:300]
                return f"[LLM Error] HTTP {resp.status_code}: {err_detail}"

            # Parse response using centralized parser (handles tool_calls, reasoning, etc.)
            result_text = parse_llm_response_body(body, logger)

            # Capture token usage from API response
            if token_tracker and "usage" in body:
                try:
                    usage = body["usage"]
                    token_tracker.record(
                        backend=_active,
                        model=model,
                        prompt_tokens=usage.get("prompt_tokens", 0),
                        completion_tokens=usage.get("completion_tokens", 0),
                        total_tokens=usage.get("total_tokens", 0),
                    )
                except Exception:
                    pass  # Token tracking failure must not affect chat

            return result_text

        except requests.ConnectionError as e:
            return f"[LLM Error] Connection failed: {e}"
        except Exception as e:
            return f"[LLM Error] {e}"

    # Attach helpers for external access
    _llm_chat.switch_backend = _switch_backend
    _llm_chat.list_backends = _list_backends
    _llm_chat.get_active_model = _get_active_model
    _llm_chat.get_active = lambda: _active

    return _llm_chat, _switch_backend, _get_active_model, _list_backends


# -- Tool registration --

def register_tools(registry: ToolRegistry, config: dict, base_dir: Path):
    """Register all enabled tools with appropriate closures."""
    enabled = config.get("tools", {}).get("enabled", [])

    # Set file base for safety
    file_tools.set_file_base(base_dir)

    # Get shell whitelist
    shell_cfg = config.get("tools", {}).get("shell", {})
    if isinstance(shell_cfg, list):
        shell_allowed = shell_cfg
    else:
        shell_allowed = shell_cfg.get("allowed", [])

    tool_map = {
        "read_file": (
            "Read the contents of a file",
            lambda path: file_tools.read_file(path),
            {"path": "File path to read"},
        ),
        "write_file": (
            "Create or overwrite a file (requires confirmation)",
            lambda path, content: file_tools.write_file(path, content),
            {"path": "File path", "content": "Content to write"},
        ),
        "list_dir": (
            "List files and subdirectories",
            lambda path: file_tools.list_dir(path),
            {"path": "Directory path"},
        ),
        "search_code": (
            "Search for a pattern in files under a path",
            lambda pattern, path: file_tools.search_code(pattern, path),
            {"pattern": "Search pattern", "path": "Search root path"},
        ),
        "find_files": (
            "Recursively find files matching a name pattern like '*.yml' or 'Dockerfile'",
            lambda pattern, path: file_tools.find_files(pattern, path),
            {"pattern": "Glob pattern (e.g. '*.yml', 'application*.properties')", "path": "Search root path"},
        ),
        "shell": (
            "Execute a shell command (whitelist enforced)",
            lambda command: shell_tools.shell(command, allowed_commands=shell_allowed),
            {"command": "Shell command to run"},
        ),
        "read_template": (
            "Read a template file from templates/",
            lambda path: document_tools.read_template(path, base_dir),
            {"path": "Template file name or path"},
        ),
        "write_output": (
            "Write generated content to output/ directory",
            lambda path, content: document_tools.write_output(path, content, base_dir),
            {"path": "Output file name or path", "content": "Content to write"},
        ),
        "web_fetch": (
        "Make an HTTP GET or POST request",
        lambda url, method="GET", body="", headers="", timeout=30:
            browser_tools.web_fetch(url, method, body, headers, timeout),
        {"url": "Target URL", "method": "HTTP method (GET/POST)",
         "body": "Request body for POST", "headers": "Optional JSON headers",
         "timeout": "Timeout in seconds"},
        ),
        "browser_navigate": (
        "Navigate the browser to a URL",
        lambda url: browser_tools.browser_navigate(url, base_dir),
        {"url": "URL to navigate to"},
        ),
        "browser_screenshot": (
        "Take a screenshot and save to output/",
        lambda name="screenshot": browser_tools.browser_screenshot(name, base_dir),
        {"name": "Screenshot file name (without extension)"},
        ),
        "browser_click": (
        "Click an element by CSS selector",
        lambda selector: browser_tools.browser_click(selector, base_dir),
        {"selector": "CSS selector of the element"},
        ),
        "browser_type": (
        "Type text into an input element",
        lambda selector, text: browser_tools.browser_type(selector, text, base_dir),
        {"selector": "CSS selector of the input", "text": "Text to type"},
        ),
        "browser_get_content": (
        "Get text content of the current page",
        lambda selector="", max_length=8000:
            browser_tools.browser_get_content(selector, max_length, base_dir),
        {"selector": "Optional CSS selector", "max_length": "Max chars to return"},
        ),
        "browser_get_html": (
        "Get HTML of the current page",
        lambda selector="": browser_tools.browser_get_html(selector, base_dir),
        {"selector": "Optional CSS selector"},
        ),
        "browser_exec": (
        "Execute JavaScript in the browser",
        lambda js: browser_tools.browser_exec(js, base_dir),
        {"js": "JavaScript code to execute"},
        ),
        "browser_status": (
            "Check if browser automation is available",
            lambda: browser_tools.browser_status(base_dir),
            {},
        ),
        "write_docx": (
            "Fill a Word (.docx) template with field values and save",
            lambda path, fields, template_path: document_tools.write_docx(path, fields, template_path, base_dir),
            {"path": "Output .docx path", "fields": "JSON string of key-value pairs", "template_path": "Template .docx file path"},
        ),
        "write_xlsx": (
            "Fill an Excel (.xlsx) template with field values and save",
            lambda path, fields, template_path: document_tools.write_xlsx(path, fields, template_path, base_dir),
            {"path": "Output .xlsx path", "fields": "JSON string of key-value pairs", "template_path": "Template .xlsx file path"},
        ),
        "write_pptx": (
            "Fill a PowerPoint (.pptx) template with field values and save",
            lambda path, fields, template_path: document_tools.write_pptx(path, fields, template_path, base_dir),
            {"path": "Output .pptx path", "fields": "JSON string of key-value pairs", "template_path": "Template .pptx file path"},
        ),

        "db_connect": (
            "Connect to a database (MySQL/TDSQL/GBase/Oracle/GCDW)",
            lambda engine, host, port, user, password, database: db_tools.db_connect(engine, host, port, user, password, database),
            {"engine": "mysql|tdsql|gbase|oracle|gcdw", "host": "IP or hostname", "port": "Port", "user": "Username", "password": "Password", "database": "Database name"},
        ),
        "db_list_procedures": (
            "List stored procedures in the connected database",
            lambda filter="": db_tools.db_list_procedures(filter),
            {"filter": "Optional name filter"},
        ),
        "db_get_procedure": (
            "Get full definition of a stored procedure",
            lambda name: db_tools.db_get_procedure(name),
            {"name": "Procedure name"},
        ),
        "db_list_tables": (
            "List tables and views in the connected database",
            lambda filter="": db_tools.db_list_tables(filter),
            {"filter": "Optional name filter"},
        ),
        "db_query": (
            "Run a read-only SELECT query (safely limited)",
            lambda sql, limit=100: db_tools.db_query(sql, limit),
            {"sql": "SELECT query", "limit": "Max rows (default 100)"},
        ),
        "db_status": (
            "Show database connection status",
            lambda: db_tools.db_status(),
            {},
        ),
        "db_disconnect": (
            "Close all database connections",
            lambda: db_tools.db_disconnect(),
            {},
        ),
    }

    for tool_name in enabled:
        if tool_name in tool_map:
            desc, func, params = tool_map[tool_name]
            registry.register(tool_name, desc, func, params)


# -- Main entry --

def main():
    parser = argparse.ArgumentParser(description="OfflineAgent - Portable AI Assistant")
    parser.add_argument("-c", "--config", default="config.yaml", help="Config file path")
    parser.add_argument("-p", "--python", help="Portable Python path (for setup info)")
    args = parser.parse_args()

    base_dir = _AGENT_DIR
    config_path = base_dir / args.config

    # Load config
    print(f"  Loading config: {config_path}")
    config = load_config(config_path)

    # Validate config
    issues = run_self_check(config, base_dir)
    if issues:
        print("\n  [Config Warnings]:")
        for issue in issues:
            print(f"    - {issue}")
        print()

    # Initialize logger
    log_dir = base_dir / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = AgentLogger(log_dir)
    # logger is initialized via constructor

    # Load skills
    print("  Loading skills...")
    skills = load_all_skills(config, base_dir)
    print(f"  Loaded {len(skills)} skills.")

    # Build system prompt
    print("  Building system prompt...")
    system_prompt, cache_hit = build_system_prompt(config, skills, base_dir)
    if cache_hit:
        print("  (Using cached prompt)")

    # Create LLM client
    llm_chat_fn, switch_backend_fn, get_active_model_fn, list_backends_fn = create_llm_chat_fn(config, logger)

    # Initialize state
    agent_cfg = config.get("agent", {})
    state = StateManager(
        max_history=agent_cfg.get("max_history", 20),
        max_tokens=agent_cfg.get("max_tokens_estimate", 128000),
    )

    # Initialize memory
    memory_store = None
    if agent_cfg.get("memory", {}).get("enabled", True):
        memory_store = MemoryStore(base_dir / "memory")
        recent = memory_store.get_recent(agent_cfg.get("memory", {}).get("max_recent", 3))
        if recent:
            # Rebuild prompt with memories
            system_prompt, _ = build_system_prompt(
                config, skills, base_dir, recent_memories=recent, force_rebuild=True
            )

    # Register tools
    registry = ToolRegistry()
    register_tools(registry, config, base_dir)


    # Scan pending issues
    pending_dir = base_dir / "pending"
    if pending_dir.exists():
        items = sorted(pending_dir.glob("*.md"))
        if items:
            print(f"\n  [Pending] You have {len(items)} unresolved issue(s):")
            for f in items:
                print(f"    - {f.stem.replace("_", " ")}")
            print("  Type /pending during chat to review.\n")
    # Start chat loop

    # Initialize browser (non-blocking if Playwright not available)
    browser_init_msg = browser_tools.init_browser(base_dir)
    print(f"  {browser_init_msg}")
    chat = ChatLoop(
        config=config,
        base_dir=base_dir,
        system_prompt=system_prompt,
        skills=skills,
        state=state,
        tools_registry=registry,
        llm_chat_fn=llm_chat_fn,
        switch_backend_fn=switch_backend_fn,
        get_active_model_fn=get_active_model_fn,
        list_backends_fn=list_backends_fn,
        memory_store=memory_store,
        logger=logger,
    )

    try:
        chat.run()
    except KeyboardInterrupt:
        pass
    finally:
        logger.write_log_file()

    return 0


if __name__ == "__main__":
    sys.exit(main())
