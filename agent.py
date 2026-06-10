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

def create_llm_chat_fn(config: dict):
    """Create a closure that calls the configured LLM API.

    Returns a function: messages -> response_text
    """
    llm_cfg = config.get("llm", {})
    url = llm_cfg.get("url", "")
    model = llm_cfg.get("model", "Qwen3")
    timeout = llm_cfg.get("timeout", 60)
    extra_headers = llm_cfg.get("extra_headers", {})

    if not url:
        print("[WARN] LLM URL not configured. Using echo mode.")

        def _echo(messages):
            last = messages[-1]["content"] if messages else ""
            return f"[Echo mode] Received {len(messages)} messages. Last: {last[:200]}"
        return _echo

    def _llm_chat(messages: list[dict]) -> str:
        """Send messages to LLM and return response text."""
        headers = {
            "Content-Type": "application/json",
            **extra_headers,
        }
        data = {
            "model": model,
            "messages": messages,
        }

        try:
            resp = requests.post(url, headers=headers, json=data, timeout=timeout)
            body = resp.json()

            # Handle common API response formats
            if "choices" in body and len(body["choices"]) > 0:
                choice = body["choices"][0]
                msg = choice.get("message", {})
                return msg.get("content", "")
            elif "response" in body:
                return body["response"]
            elif "content" in body:
                return body["content"]
            else:
                return _json.dumps(body, ensure_ascii=False)

        except requests.ConnectionError as e:
            return f"[LLM Error] Connection failed: {e}"
        except Exception as e:
            return f"[LLM Error] {e}"

    return _llm_chat


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
            lambda url, method="GET": browser_tools.web_fetch(url, method),
            {"url": "Target URL", "method": "HTTP method (GET/POST)"},
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
    log_dir = base_dir / "memory"
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
    llm_chat_fn = create_llm_chat_fn(config)

    # Initialize state
    agent_cfg = config.get("agent", {})
    state = StateManager(
        max_history=agent_cfg.get("max_history", 20),
        max_tokens=agent_cfg.get("max_tokens_estimate", 8000),
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

    # Start chat loop
    chat = ChatLoop(
        config=config,
        base_dir=base_dir,
        system_prompt=system_prompt,
        skills=skills,
        state=state,
        tools_registry=registry,
        llm_chat_fn=llm_chat_fn,
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
