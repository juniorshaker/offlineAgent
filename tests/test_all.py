"""
tests/test_all.py — OfflineAgent Complete Test Suite

Covers all critical modules:
  YAML parser, Tool parser, Token estimator, Error recovery,
  Skill loader, Tool registry, State manager, File tools,
  Shell tools, Memory store, Topic guard, Context compressor.

Usage:
  cd Offlineagent/
  python -m pytest tests/test_all.py -v
  or
  python tests/test_all.py
"""

import sys
import os
import json
import tempfile
from pathlib import Path
from io import StringIO

# Path setup
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# ============================================================================
# Test Helpers
# ============================================================================

_TESTS_RUN = 0
_TESTS_PASSED = 0
_TESTS_FAILED = 0
_CURRENT_MODULE = ""


def _header(name: str):
    global _CURRENT_MODULE
    _CURRENT_MODULE = name
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")


def _ok(name: str):
    global _TESTS_RUN, _TESTS_PASSED
    _TESTS_RUN += 1
    _TESTS_PASSED += 1
    print(f"  [PASS] {name}")


def _fail(name: str, msg: str = ""):
    global _TESTS_RUN, _TESTS_FAILED
    _TESTS_RUN += 1
    _TESTS_FAILED += 1
    suffix = f"  —  {msg}" if msg else ""
    print(f"  [FAIL] {name}{suffix}")


def assert_eq(a, b, name: str = ""):
    if a == b:
        _ok(name or f"assert_eq")
    else:
        _fail(name or f"assert_eq", f"expected {repr(b)}, got {repr(a)}")


def assert_true(cond, name: str = ""):
    if cond:
        _ok(name or f"assert_true")
    else:
        _fail(name or f"assert_true", "condition is False")


def assert_in(item, container, name: str = ""):
    if item in container:
        _ok(name or f"assert_in")
    else:
        _fail(name or f"assert_in", f"{repr(item)} not found")


def assert_not_in(item, container, name: str = ""):
    if item not in container:
        _ok(name or f"assert_not_in")
    else:
        _fail(name or f"assert_not_in", f"{repr(item)} unexpectedly found")


# ============================================================================
# 1. YAML Config Parser
# ============================================================================

def test_yaml_parser():
    _header("1. YAML Config Parser")
    from Offlineagent.agent import load_config, _parse_simple_yaml, _parse_scalar

    # 1.1 Scalar values
    assert_eq(_parse_scalar("true"), True, "bool true")
    assert_eq(_parse_scalar("false"), False, "bool false")
    assert_eq(_parse_scalar("42"), 42, "int")
    assert_eq(_parse_scalar("3.14"), 3.14, "float")
    assert_eq(_parse_scalar("hello"), "hello", "string")
    assert_eq(_parse_scalar("[a, b, c]"), ["a", "b", "c"], "inline list")
    assert_eq(_parse_scalar("{}"), {}, "empty dict")
    assert_eq(_parse_scalar("[]"), [], "empty list")

    # 1.2 Nested dict with list
    yaml = """
tools:
  enabled:
    - read_file
    - write_file
  shell:
    allowed:
      - mvn
      - git
    require_confirm: true
"""
    result = _parse_simple_yaml(yaml)
    tools = result.get("tools", {})
    assert_eq(tools.get("enabled"), ["read_file", "write_file"], "tools.enabled list")
    shell = tools.get("shell", {})
    assert_eq(shell.get("allowed"), ["mvn", "git"], "shell.allowed list")
    assert_eq(shell.get("require_confirm"), True, "shell.require_confirm")

    # 1.3 Multi-level nesting
    yaml2 = """
agent:
  compression:
    enabled: true
    trigger_ratio: 0.7
    keep_recent: 2
  memory:
    enabled: false
    max_recent: 5
"""
    result = _parse_simple_yaml(yaml2)
    agent = result.get("agent", {})
    comp = agent.get("compression", {})
    assert_eq(comp.get("enabled"), True, "compression.enabled")
    assert_eq(comp.get("trigger_ratio"), 0.7, "compression.trigger_ratio")
    assert_eq(comp.get("keep_recent"), 2, "compression.keep_recent")
    mem = agent.get("memory", {})
    assert_eq(mem.get("enabled"), False, "memory.enabled")
    assert_eq(mem.get("max_recent"), 5, "memory.max_recent")

    # 1.4 Comments
    yaml3 = """
# This is a comment
key: value  # inline comment
"""
    result = _parse_simple_yaml(yaml3)
    assert_eq(result.get("key"), "value", "comment handling")

    # 1.5 Load real config.yaml
    cfg = load_config(Path(__file__).resolve().parent.parent / "config.yaml")
    assert_true(isinstance(cfg, dict), "real config is dict")
    assert_true("llm" in cfg, "real config has llm")
    assert_true("tools" in cfg, "real config has tools")
    assert_true("agent" in cfg, "real config has agent")
    assert_eq(cfg.get("llm", {}).get("model"), "Qwen3", "real config model")


# ============================================================================
# 2. XML Tool Parser
# ============================================================================

def test_tool_parser():
    _header("2. XML Tool Parser")
    from Offlineagent.tool_layer.tool_parser import (
        parse_tool_calls, has_tool_calls, extract_text_without_tools
    )

    # 2.1 Single tool call
    text = """Let me read that file.

<tool_call>
<name>read_file</name>
<path>src/Main.java</path>
</tool_call>

Done."""
    assert_true(has_tool_calls(text), "detect tool call")
    calls = parse_tool_calls(text)
    assert_eq(len(calls), 1, "single tool call")
    assert_eq(calls[0].name, "read_file", "tool name")
    assert_eq(calls[0].params.get("path"), "src/Main.java", "tool param")

    # 2.2 Multiple tool calls
    text2 = """<tool_call>
<name>list_dir</name>
<path>.</path>
</tool_call>
<tool_call>
<name>read_file</name>
<path>README.md</path>
</tool_call>"""
    calls = parse_tool_calls(text2)
    assert_eq(len(calls), 2, "multiple tool calls")
    assert_eq(calls[0].name, "list_dir", "first tool")
    assert_eq(calls[1].name, "read_file", "second tool")

    # 2.3 No tool calls
    text3 = "Just a normal response without any tools."
    assert_true(not has_tool_calls(text3), "no tool call detection")
    calls = parse_tool_calls(text3)
    assert_eq(len(calls), 0, "no tool calls parsed")

    # 2.4 Text extraction
    text_without = extract_text_without_tools(text)
    assert_in("Let me read that file.", text_without, "text before tool")
    assert_in("Done.", text_without, "text after tool")
    assert_not_in("<tool_call>", text_without, "no xml in extracted text")

    # 2.5 Malformed tool call (missing closing tag)
    text4 = """<tool_call>
<name>shell</name>
<command>dir</command>
"""
    calls = parse_tool_calls(text4)
    assert_eq(len(calls), 0, "malformed tool call returns empty")


# ============================================================================
# 3. Token Estimator
# ============================================================================

def test_token_estimator():
    _header("3. Token Estimator")
    from Offlineagent.orchestrator.state_manager import TokenEstimator

    # 3.1 Empty / edge
    assert_eq(TokenEstimator.estimate(""), 0, "empty string")
    assert_eq(TokenEstimator.estimate(None), 0, "None input")

    # 3.2 English text (~4 chars/token)
    en = "Hello world, this is a test."
    tokens_en = TokenEstimator.estimate(en)
    assert_true(tokens_en > 0, "english > 0")
    assert_true(tokens_en < len(en), "english tokens < chars")

    # 3.3 Chinese text (~1.5 chars/token)
    cn = "你好世界这是一个测试"
    tokens_cn = TokenEstimator.estimate(cn)
    assert_true(tokens_cn > 0, "chinese > 0")
    assert_true(tokens_cn < len(cn), "chinese tokens < chars")

    # 3.4 Mixed
    mixed = "Hello 你好 World 世界"
    tokens_mixed = TokenEstimator.estimate(mixed)
    assert_true(tokens_mixed > 0, "mixed > 0")

    # 3.5 Messages estimation
    msgs = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there! How can I help?"},
    ]
    total = TokenEstimator.estimate_messages(msgs)
    assert_true(total > 0, "messages estimation > 0")

    # 3.6 Multi-modal content
    msgs2 = [
        {"role": "user", "content": [
            {"type": "text", "text": "What is this?"},
            {"type": "image_url", "image_url": {"url": "..."}},
        ]},
    ]
    total2 = TokenEstimator.estimate_messages(msgs2)
    assert_true(total2 > 0, "multimodal estimation > 0")


# ============================================================================
# 4. Error Recovery
# ============================================================================

def test_error_recovery():
    _header("4. Error Recovery")
    from Offlineagent.orchestrator.error_recovery import (
        observe_error, check_before_send, repair_after_error,
        _infer_unsupported_type, _load_capabilities, _strip_unsupported,
    )

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)

        # 4.1 Infer unsupported type from error message
        assert_eq(_infer_unsupported_type("model does not support image input"), "image", "infer image")
        assert_eq(_infer_unsupported_type("multimodal content not allowed"), "image", "infer multimodal->image")
        assert_eq(_infer_unsupported_type("video processing failed"), "video", "infer video")
        assert_eq(_infer_unsupported_type("audio format not supported"), "audio", "infer audio")
        assert_eq(_infer_unsupported_type("screenshot upload rejected"), "image", "infer screenshot->image")
        assert_eq(_infer_unsupported_type("unknown error"), None, "no inference for unknown")

        # 4.2 Observe and learn
        msgs = [
            {"role": "user", "content": [
                {"type": "text", "text": "Describe this image"},
                {"type": "image_url", "image_url": {"url": "..."}},
            ]},
        ]
        observe_error("deepseek-chat", "model does not support image input", msgs, base)
        caps = _load_capabilities(base)
        assert_true("deepseek-chat" in caps, "model recorded")
        assert_in("image", caps["deepseek-chat"].get("unsupported", []), "image in unsupported")

        # 4.3 Pre-check before send (prevents future errors)
        stripped = check_before_send("deepseek-chat", msgs, base)
        assert_true(stripped is not None, "pre-check returns modified messages")
        # The image block should be replaced
        user_content = stripped[0].get("content", [])
        has_image = any(
            isinstance(b, dict) and b.get("type") == "image_url"
            for b in user_content
        )
        assert_true(not has_image, "image stripped proactively")

        # 4.4 Model without known issues passes through
        clean_msgs = [{"role": "user", "content": "Hello"}]
        result = check_before_send("unknown-model", clean_msgs, base)
        assert_eq(result, None, "unknown model returns None")

        # 4.5 Repair after error
        repaired = repair_after_error("qwen-vl", "picture is not supported", msgs, base)
        user_rc = repaired[0].get("content", [])
        has_image2 = any(
            isinstance(b, dict) and b.get("type") == "image_url"
            for b in user_rc
        )
        assert_true(not has_image2, "image stripped after repair")

        # 4.6 Error count increments
        caps = _load_capabilities(base)
        assert_eq(caps.get("deepseek-chat", {}).get("error_count"), 1, "error_count=1")
        # Add another error
        observe_error("deepseek-chat", "image not supported again", msgs, base)
        caps = _load_capabilities(base)
        assert_eq(caps.get("deepseek-chat", {}).get("error_count"), 2, "error_count=2")

        # 4.7 Multiple unsupported types
        observe_error("old-model", "audio and video not supported", [], base)
        caps = _load_capabilities(base)
        old_caps = caps.get("old-model", {})
        unsupported = old_caps.get("unsupported", [])
        # Should have inferred at least audio
        assert_true(len(unsupported) >= 1, "multiple unsupported types recorded")


# ============================================================================
# 5. Skill Loader
# ============================================================================

def test_skill_loader():
    _header("5. Skill Loader")
    from Offlineagent.prompt_layer.skill_loader import (
        Skill, load_all_skills, _parse_frontmatter, _skill_matches_platform,
    )

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        skills_dir = base / "skills"
        skills_dir.mkdir()

        # 5.1 Create a test SKILL.md
        skill_dir = skills_dir / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("""---
name: Test Skill
description: A test skill for unit testing.
platforms: [windows, linux]
---

# Test Skill Body

This is the body content.
""", encoding="utf-8")

        # 5.2 Frontmatter parsing
        content = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        fm, body = _parse_frontmatter(content)
        assert_eq(fm.get("name"), "Test Skill", "frontmatter name")
        assert_eq(fm.get("description"), "A test skill for unit testing.", "frontmatter desc")
        assert_in("Test Skill Body", body, "body preserved")
        assert_not_in("---", body, "no frontmatter in body")

        # 5.3 Platform matching
        assert_true(_skill_matches_platform({"platforms": "[windows, linux]"}), "windows match")
        assert_true(_skill_matches_platform({}), "no platforms = all match")

        # 5.4 Load skills
        config = {"skills": {"paths": [str(skills_dir)]}}
        skills = load_all_skills(config, base)
        assert_eq(len(skills), 1, "one skill loaded")
        assert_eq(skills[0].name, "Test Skill", "skill name")
        assert_eq(skills[0].source, "local", "skill source")
        assert_eq(skills[0].use_count, 0, "initial use_count=0")

        # 5.5 Skill short description truncation
        skill = skills[0]
        assert_true(len(skill.short_desc) <= 60, "short_desc <= 60 chars")

        # 5.6 Skills from non-existent path (no crash)
        config2 = {"skills": {"paths": [str(base / "nonexistent")]}}
        skills2 = load_all_skills(config2, base)
        assert_eq(len(skills2), 0, "non-existent path returns empty")


# ============================================================================
# 6. Tool Registry
# ============================================================================

def test_tool_registry():
    _header("6. Tool Registry")
    from Offlineagent.tool_layer.tool_registry import ToolRegistry

    registry = ToolRegistry()

    # 6.1 Register and dispatch
    def mock_read(path: str) -> str:
        return f"Content of {path}"

    registry.register("read_file", "Read a file", mock_read, {"path": "File path"})
    assert_eq(registry.names(), ["read_file"], "registered tool name")

    # 6.2 Valid dispatch
    result = registry.dispatch("read_file", {"path": "test.txt"})
    assert_eq(result, "Content of test.txt", "dispatch result")

    # 6.3 Unknown tool
    result = registry.dispatch("nonexistent", {})
    assert_in("Error", result, "unknown tool error")
    assert_in("nonexistent", result, "tool name in error")

    # 6.4 Invalid params (missing required)
    result = registry.dispatch("read_file", {})
    assert_in("Error", result, "missing param error")

    # 6.5 Get tool definition
    tool = registry.get("read_file")
    assert_true(tool is not None, "get existing tool")
    assert_eq(tool.name, "read_file", "tool name match")
    tool2 = registry.get("nonexistent")
    assert_true(tool2 is None, "get nonexistent returns None")

    # 6.6 Multiple tools
    registry.register("list_dir", "List directory", lambda path: f"Dir: {path}", {"path": "Path"})
    assert_eq(len(registry.names()), 2, "two tools registered")
    assert_in("read_file", registry.names(), "read_file in names")
    assert_in("list_dir", registry.names(), "list_dir in names")


# ============================================================================
# 7. State Manager
# ============================================================================

def test_state_manager():
    _header("7. State Manager")
    from Offlineagent.orchestrator.state_manager import StateManager

    state = StateManager(max_history=5, max_tokens=4000)

    # 7.1 Message history
    state.add_user_message("Hello")
    state.add_assistant_message("Hi there!")
    assert_eq(len(state.messages), 2, "message count")
    assert_eq(state.get_last_user_message(), "Hello", "last user msg")
    assert_eq(state.get_last_assistant_message(), "Hi there!", "last assistant msg")

    # 7.2 Tool results
    state.add_tool_result("File contents: ...")
    assert_eq(len(state.messages), 3, "after tool result")
    assert_in("[Tool Result]", state.messages[-1]["content"], "tool result format")

    # 7.3 History for API
    msgs = state.get_history_for_api("System prompt here")
    assert_eq(msgs[0]["role"], "system", "first msg is system")
    assert_eq(msgs[0]["content"], "System prompt here", "system prompt content")

    # 7.4 Token estimation
    tokens = state.estimate_total_tokens()
    assert_true(tokens > 0, "token estimation > 0")

    # 7.5 Usage ratio
    ratio = state.usage_ratio()
    assert_true(0 < ratio < 1, f"usage ratio in range: {ratio}")

    # 7.6 Compression trigger
    # With default trigger 0.7, small conversation shouldn't trigger
    assert_true(not state.needs_compression(0.7), "no compression for small convo")
    assert_true(state.needs_compression(0.001), "compression with low trigger")

    # 7.7 Clear history
    state.clear_history()
    assert_eq(len(state.messages), 0, "all msgs cleared after clear")

    # 7.8 Status summary
    status = state.status_summary("Test system prompt")
    assert_in("tokens_estimate", status, "status has tokens")
    assert_in("turns", status, "status has turns")
    assert_in("usage_percent", status, "status has percent")

    # 7.9 Max history enforcement
    state2 = StateManager(max_history=2, max_tokens=100000)
    for i in range(10):
        state2.add_user_message(f"msg {i}")
        state2.add_assistant_message(f"resp {i}")
    api_msgs = state2.get_history_for_api("system")
    user_assistant = [m for m in api_msgs if m["role"] in ("user", "assistant")]
    assert_true(len(user_assistant) <= 4, f"max_history enforced: {len(user_assistant)} <= 4")


# ============================================================================
# 8. File Tools
# ============================================================================

def test_file_tools():
    _header("8. File Tools")
    from Offlineagent.tool_layer import file_tools

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        file_tools.set_file_base(base)

        # 8.1 Write file
        result = file_tools.write_file("test.txt", "Hello, World!")
        assert_in("OK", result, "write success")
        assert_in("test.txt", result, "filename in result")
        assert_true((base / "test.txt").exists(), "file actually created")
        assert_eq((base / "test.txt").read_text(), "Hello, World!", "file content")

        # 8.2 Read file
        content = file_tools.read_file("test.txt")
        assert_eq(content, "Hello, World!", "read content")
        assert_in("Hello", content, "read contains content")

        # 8.3 Read non-existent file
        result = file_tools.read_file("nonexistent.txt")
        assert_in("Error", result, "read nonexistent returns error")
        assert_in("not found", result.lower(), "not found message")

        # 8.4 List directory
        (base / "subdir").mkdir()
        (base / "subdir" / "file.txt").write_text("sub")
        listing = file_tools.list_dir(".")
        assert_in("test.txt", listing, "test.txt in listing")
        assert_in("subdir", listing, "subdir in listing")

        # 8.5 List non-existent directory
        result = file_tools.list_dir("nonexistent")
        assert_in("Error", result, "list nonexistent returns error")

        # 8.6 Search code
        (base / "code.py").write_text("def hello():\n    print('hello world')\n    return 42\n", encoding="utf-8")
        search_result = file_tools.search_code("hello", ".")
        assert_in("hello", search_result.lower(), "search finds hello")

        # 8.7 Search with no matches
        no_match = file_tools.search_code("xyznonexistent_12345", ".")
        assert_in("No matches", no_match, "no matches message")


# ============================================================================
# 9. Shell Tools
# ============================================================================

def test_shell_tools():
    _header("9. Shell Tools")
    from Offlineagent.tool_layer import shell_tools

    # 9.1 Simple command
    result = shell_tools.shell("echo hello")
    assert_in("hello", result, "echo output")

    # 9.2 Command with allowed whitelist
    result = shell_tools.shell("echo test123", allowed_commands=["echo", "python"])
    assert_in("test123", result, "allowed command works")

    # 9.3 Blocked command
    result = shell_tools.shell("del file.txt", allowed_commands=["echo", "git"])
    assert_in("Blocked", result, "blocked command message")
    assert_in("del", result, "blocked command name")

    # 9.4 Empty command
    result = shell_tools.shell("")
    assert_in("Error", result, "empty command error")

    # 9.5 Nonexistent command (Windows may route through cmd.exe)
    result = shell_tools.shell("nonexistent_cmd_12345")
    # On Windows with shell=True, cmd.exe handles this differently
    assert_true(len(result) > 0, "nonexistent command produces output")

    # 9.6 Command with exit code
    result = shell_tools.shell("python -c \"import sys; print('err msg', file=sys.stderr); sys.exit(1)\"")
    assert_in("Exit code", result, "exit code in result")


# ============================================================================
# 10. Memory Store
# ============================================================================

def test_memory_store():
    _header("10. Memory Store")
    from Offlineagent.memory_layer.memory_store import MemoryStore

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        store = MemoryStore(base / "memory")

        # 10.1 Initial state
        assert_eq(store.count(), 0, "initial count=0")
        memories = store.list_all()
        assert_eq(len(memories), 0, "initial list empty")

        # 10.2 Add memory
        mem_id = store.add("This is a summary of a session about Python testing.", tags=["python", "testing"])
        assert_true(mem_id is not None, "memory id returned")
        assert_true(len(mem_id) > 0, "memory id nonempty")
        assert_eq(store.count(), 1, "count=1 after add")

        # 10.3 Add more memories
        store.add("Second memory about Java development.", tags=["java"])
        store.add("Third memory about Docker deployment.", tags=["docker"])
        store.add("Fourth memory about CI/CD pipelines.")
        assert_eq(store.count(), 4, "count=4")

        # 10.4 Get recent
        recent = store.get_recent(3)
        assert_eq(len(recent), 3, "recent returns 3")
        assert_in("CI/CD", recent[2], "most recent first")

        # 10.5 Get by ID
        full = store.get(mem_id)
        assert_true(full is not None, "get by id returns content")
        assert_true(len(full) > 0, "content non-empty")

        # 10.6 Get nonexistent ID
        no_mem = store.get("nonexistent_id")
        assert_true(no_mem is None, "nonexistent returns None")

        # 10.7 List all (newest first)
        all_mem = store.list_all()
        assert_eq(len(all_mem), 4, "list_all returns 4")
        assert_eq(all_mem[0]["summary"], "Fourth memory about CI/CD pipelines.", "newest first")

        # 10.8 Persistence (reload)
        store2 = MemoryStore(base / "memory")
        assert_eq(store2.count(), 4, "persistence: count preserved")
        recent2 = store2.get_recent(2)
        assert_eq(len(recent2), 2, "persistence: recent works")


# ============================================================================
# 11. Topic Guard
# ============================================================================

def test_topic_guard():
    _header("11. Topic Guard")
    from Offlineagent.orchestrator.topic_guard import detect_topic_shift, TOPIC_CHECK_PROMPT

    # 11.1 TOPIC_CHECK_PROMPT contains the right structure
    assert_in("SAME", TOPIC_CHECK_PROMPT, "prompt asks for SAME/DIFFERENT")
    assert_in("{context}", TOPIC_CHECK_PROMPT, "prompt has context placeholder")
    assert_in("{user_input}", TOPIC_CHECK_PROMPT, "prompt has user_input placeholder")

    # 11.2 detect_topic_shift with no history returns SAME
    from Offlineagent.orchestrator.state_manager import StateManager
    state = StateManager(max_history=5, max_tokens=4000)
    result = detect_topic_shift(state, "Hello", lambda msgs: "SAME")
    assert_eq(result, "SAME", "no history = SAME")

    # 11.3 detect_topic_shift with LLM returning DIFFERENT
    state.add_user_message("Let's write Java unit tests")
    state.add_assistant_message("Sure, what testing framework?")
    result = detect_topic_shift(state, "What should I eat for dinner?", lambda msgs: "DIFFERENT")
    assert_eq(result, "DIFFERENT", "LLM says DIFFERENT")

    # 11.4 detect_topic_shift with LLM returning SAME
    result = detect_topic_shift(state, "Should we use JUnit 5 or TestNG?", lambda msgs: "SAME")
    assert_eq(result, "SAME", "LLM says SAME")

    # 11.5 detect_topic_shift with LLM failure defaults to SAME
    result = detect_topic_shift(state, "anything", lambda msgs: (_ for _ in ()).throw(Exception("boom")))
    assert_eq(result, "SAME", "LLM failure defaults to SAME")


# ============================================================================
# 12. Context Compressor
# ============================================================================

def test_context_compressor():
    _header("12. Context Compressor")
    from Offlineagent.orchestrator.context_compressor import (
        _build_compression_prompt, compress_history,
    )
    from Offlineagent.orchestrator.state_manager import StateManager

    # 12.1 _build_compression_prompt produces valid prompt
    old_msgs = [
        {"role": "user", "content": "How do I write a Java test?"},
        {"role": "assistant", "content": "Use JUnit 5 with @Test annotation."},
    ]
    prompt = _build_compression_prompt(old_msgs)
    assert_in("Summarize", prompt, "prompt contains Summarize")
    assert_in("JUnit", prompt, "prompt contains original content")

    # 12.2 compress_history with too few turns returns False
    state = StateManager(max_history=20, max_tokens=10000)
    state.add_user_message("Hello")
    state.add_assistant_message("Hi!")
    result = compress_history(state, "sys prompt", lambda msgs: "summary", keep_recent=2)
    assert_eq(result, False, "too few turns, no compression")

    # 12.3 compress_history with enough turns
    for i in range(6):
        state.add_user_message(f"Question {i}")
        state.add_assistant_message(f"Answer {i}")
    result = compress_history(state, "sys prompt", lambda msgs: "compressed summary", keep_recent=2)
    assert_eq(result, True, "compression performed")
    # Verify compressed content
    has_summary = any("compressed summary" in str(m.get("content", "")) for m in state.messages)
    assert_true(has_summary, "compressed summary in messages")


# ============================================================================
# Main
# ============================================================================

def run_all():
    print("\n" + "=" * 60)
    print("  OfflineAgent — Complete Test Suite")
    print("=" * 60)

    tests = [
        test_yaml_parser,
        test_tool_parser,
        test_token_estimator,
        test_error_recovery,
        test_skill_loader,
        test_tool_registry,
        test_state_manager,
        test_file_tools,
        test_shell_tools,
        test_memory_store,
        test_topic_guard,
        test_context_compressor,
    ]

    for test_fn in tests:
        try:
            test_fn()
        except Exception as e:
            global _TESTS_FAILED, _TESTS_RUN
            _TESTS_RUN += 1
            _TESTS_FAILED += 1
            import traceback
            print(f"  [CRASH] {test_fn.__name__}: {e}")
            traceback.print_exc()

    # Summary
    print(f"\n{'='*60}")
    print(f"  Results: {_TESTS_PASSED}/{_TESTS_RUN} passed, {_TESTS_FAILED} failed")
    if _TESTS_FAILED == 0:
        print(f"  Status: ALL TESTS PASSED")
    else:
        print(f"  Status: {_TESTS_FAILED} FAILURES")
    print(f"{'='*60}\n")

    return _TESTS_FAILED


if __name__ == "__main__":
    failures = run_all()
    sys.exit(1 if failures > 0 else 0)
