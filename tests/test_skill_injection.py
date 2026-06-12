"""
tests/test_skill_injection.py — Tests for LLM-based skill auto-injection

Covers:
  - Keyword matching from config
  - Single candidate → direct injection
  - Multiple candidates → LLM selection (mocked)
  - No candidates → skip
  - Deduplication
  - No re-injection if already present
  - Frontmatter triggers
  - Fallback on LLM failure
"""

import sys
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # Ai-Fields/ so Offlineagent is a package

from Offlineagent.orchestrator.chat_loop import ChatLoop

_TESTS_RUN = 0
_TESTS_PASSED = 0
_TESTS_FAILED = 0


def _ok(name: str):
    global _TESTS_RUN, _TESTS_PASSED
    _TESTS_RUN += 1
    _TESTS_PASSED += 1
    print(f"  [PASS] {name}")


def _fail(name: str, msg: str = ""):
    global _TESTS_RUN, _TESTS_FAILED
    _TESTS_RUN += 1
    _TESTS_FAILED += 1
    suffix = f" — {msg}" if msg else ""
    print(f"  [FAIL] {name}{suffix}")


def _header(name: str):
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")


# ============================================================================
# Mock objects
# ============================================================================

class FakeSkill:
    def __init__(self, name, description, frontmatter=None):
        self.name = name
        self.description = description
        self.body = f"# {name}\nBody content."
        self.path = Path(f"/fake/{name}/SKILL.md")
        self.source = "local"
        self.use_count = 0
        self.frontmatter = frontmatter or {}

    @property
    def short_desc(self):
        d = self.description.strip().strip("'\"")
        return d[:57] + "..." if len(d) > 60 else d


class FakeState:
    def __init__(self):
        self.messages = []

    def add_assistant_message(self, content):
        self.messages.append({"role": "assistant", "content": content})


class FakeLogger:
    def __init__(self):
        self.injected = []
        self.errors = []

    def skill_injected(self, name, size):
        self.injected.append((name, size))

    def error_recovery(self, component, error, action):
        self.errors.append((component, error, action))


# ============================================================================
# Tests
# ============================================================================

def test_config_keyword_match():
    _header("Config keyword matching")


    config = {
        "agent": {"skill_injection": {"enabled": True, "llm_selection": True}},
        "skill_keywords": {
            "java-code-reading": ["分析代码", ".java", "java"],
            "sql-basic-query": ["sql", "select"],
        }
    }
    skills = [
        FakeSkill("java-code-reading", "Read Java code logic."),
        FakeSkill("sql-basic-query", "Write SQL queries."),
    ]
    state = FakeState()
    logger = FakeLogger()
    
    loop = ChatLoop(
        config=config, base_dir=Path("."), system_prompt="",
        skills=skills, state=state, tools_registry=MagicMock(),
        llm_chat_fn=MagicMock(), logger=logger,
    )
    
    # Test: "分析代码" should match java-code-reading
    state.messages = []
    loop._auto_inject_skill("帮我分析代码")
    assert len(state.messages) == 1, f"Expected 1 message, got {len(state.messages)}"
    assert "java-code-reading" in state.messages[0]["content"], "Should inject java-code-reading"
    assert len(logger.injected) == 1
    _ok("keyword match → single candidate → direct inject")

    # Test: "sql" should match sql-basic-query
    state.messages = []
    logger.injected = []
    loop._auto_inject_skill("写个sql查询")
    assert len(state.messages) == 1
    assert "sql-basic-query" in state.messages[0]["content"]
    _ok("keyword match → sql skill injected")

    # Test: no match → skip
    state.messages = []
    logger.injected = []
    loop._auto_inject_skill("今天天气怎么样")
    assert len(state.messages) == 0
    _ok("no keyword match → skip injection")


def test_no_reinject():
    _header("No re-injection")
    
    config = {
        "agent": {"skill_injection": {"enabled": True, "llm_selection": True}},
        "skill_keywords": {"java-code-reading": ["java"]},
    }
    skills = [FakeSkill("java-code-reading", "Read Java code.")]
    state = FakeState()
    logger = FakeLogger()
    
    # Pre-populate with an injected skill
    state.messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "[Skill Context: java-code-reading]\n\n# Body"},
    ]
    
    loop = ChatLoop(
        config=config, base_dir=Path("."), system_prompt="",
        skills=skills, state=state, tools_registry=MagicMock(),
        llm_chat_fn=MagicMock(), logger=logger,
    )
    
    loop._auto_inject_skill("java code")
    # Should NOT add a new message since skill is already in recent
    assert len(state.messages) == 2, f"Expected 2 messages (no re-inject), got {len(state.messages)}"
    _ok("skill already in context → no re-injection")


def test_dedup():
    _header("Deduplication")
    
    config = {
        "agent": {"skill_injection": {"enabled": True, "llm_selection": True}},
        "skill_keywords": {
            "java-code-reading": ["java", "分析代码", "代码"],
            "java-code-standards": ["java", "规范"],
        }
    }
    skills = [
        FakeSkill("java-code-reading", "Read Java code."),
        FakeSkill("java-code-standards", "Check Java code standards."),
    ]
    state = FakeState()
    logger = FakeLogger()
    
    loop = ChatLoop(
        config=config, base_dir=Path("."), system_prompt="",
        skills=skills, state=state, tools_registry=MagicMock(),
        llm_chat_fn=MagicMock(), logger=logger,
    )
    
    # "java" matches both, but should deduplicate and have two unique candidates
    # With llm_selection=True, will call _llm_pick_skill which uses llm_chat_fn
    # Mock llm_chat_fn to return "java-code-reading"
    loop.llm_chat_fn = MagicMock(return_value="java-code-reading")
    state.messages = []
    loop._auto_inject_skill("java 规范")
    
    assert len(state.messages) == 1
    assert "java-code-reading" in state.messages[0]["content"]
    _ok("multiple matches → deduped → LLM pick → injected")


def test_llm_fallback():
    _header("LLM fallback on failure")
    
    config = {
        "agent": {"skill_injection": {"enabled": True, "llm_selection": True, "llm_selection_timeout": 5}},
        "skill_keywords": {
            "java-code-reading": ["java"],
            "java-code-standards": ["规范"],
        }
    }
    skills = [
        FakeSkill("java-code-reading", "Read Java code."),
        FakeSkill("java-code-standards", "Check Java code standards."),
    ]
    state = FakeState()
    logger = FakeLogger()
    
    loop = ChatLoop(
        config=config, base_dir=Path("."), system_prompt="",
        skills=skills, state=state, tools_registry=MagicMock(),
        llm_chat_fn=MagicMock(), logger=logger,
    )
    
    # Simulate LLM timeout → should fallback to first candidate (java-code-reading)
    loop.llm_chat_fn = MagicMock(return_value="[Timeout] LLM did not respond within 5s.")
    state.messages = []
    loop._auto_inject_skill("java 规范检查")
    
    assert len(state.messages) == 1
    assert "java-code-reading" in state.messages[0]["content"]
    _ok("LLM timeout → fallback to first candidate")


def test_frontmatter_triggers():
    _header("Frontmatter triggers")
    
    config = {
        "agent": {"skill_injection": {"enabled": True, "llm_selection": False}},
        "skill_keywords": {},  # No config keywords, rely on frontmatter triggers
    }
    skills = [
        FakeSkill("diagrams", "Draw diagrams.", frontmatter={
            "triggers": "流程图, 架构图, 画图",
            "applicable": "User asks for diagrams or charts",
            "not_applicable": "Code reading or text analysis",
        }),
    ]
    state = FakeState()
    logger = FakeLogger()
    
    loop = ChatLoop(
        config=config, base_dir=Path("."), system_prompt="",
        skills=skills, state=state, tools_registry=MagicMock(),
        llm_chat_fn=MagicMock(), logger=logger,
    )
    
    # "画个流程图" should match via frontmatter triggers
    state.messages = []
    loop._auto_inject_skill("帮我画个流程图")
    assert len(state.messages) == 1
    assert "diagrams" in state.messages[0]["content"]
    _ok("frontmatter triggers → skill injected")
    
    # "写代码" should NOT match (no trigger)
    state.messages = []
    loop._auto_inject_skill("帮我写代码")
    assert len(state.messages) == 0
    _ok("no frontmatter trigger match → skip")


def test_disabled_injection():
    _header("Injection disabled")
    
    config = {
        "agent": {"skill_injection": {"enabled": False}},
        "skill_keywords": {"java-code-reading": ["java"]},
    }
    skills = [FakeSkill("java-code-reading", "Read Java code.")]
    state = FakeState()
    
    loop = ChatLoop(
        config=config, base_dir=Path("."), system_prompt="",
        skills=skills, state=state, tools_registry=MagicMock(),
        llm_chat_fn=MagicMock(), logger=None,
    )
    
    state.messages = []
    loop._auto_inject_skill("java code")
    assert len(state.messages) == 0
    _ok("disabled → no injection")


def test_llm_returns_none():
    _header("LLM returns 'none'")
    
    config = {
        "agent": {"skill_injection": {"enabled": True, "llm_selection": True}},
        "skill_keywords": {
            "java-code-reading": ["java"],
            "sql-basic-query": ["sql"],
        }
    }
    skills = [
        FakeSkill("java-code-reading", "Read Java code."),
        FakeSkill("sql-basic-query", "Write SQL queries."),
    ]
    state = FakeState()
    
    loop = ChatLoop(
        config=config, base_dir=Path("."), system_prompt="",
        skills=skills, state=state, tools_registry=MagicMock(),
        llm_chat_fn=MagicMock(), logger=None,
    )
    
    # LLM says "none" → no injection
    loop.llm_chat_fn = MagicMock(return_value="none")
    state.messages = []
    loop._auto_inject_skill("java sql something")
    assert len(state.messages) == 0
    _ok("LLM returns 'none' → no injection")


# ============================================================================
# Main
# ============================================================================

def run_all():
    print("\n" + "="*60)
    print("  Skill Injection Test Suite")
    print("="*60)

    test_config_keyword_match()
    test_no_reinject()
    test_dedup()
    test_llm_fallback()
    test_frontmatter_triggers()
    test_disabled_injection()
    test_llm_returns_none()

    print(f"\n{'='*60}")
    print(f"  Results: {_TESTS_PASSED}/{_TESTS_RUN} passed, {_TESTS_FAILED} failed")
    print(f"{'='*60}")
    return _TESTS_FAILED == 0


if __name__ == "__main__":
    ok = run_all()
    sys.exit(0 if ok else 1)
