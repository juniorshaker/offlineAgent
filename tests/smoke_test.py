"""
Smoke test for OfflineAgent core capabilities.
Run: python D:\AiCoding\Ai-Fields\Offlineagent\tests\smoke_test.py
"""
import sys, os, json, tempfile, shutil
from pathlib import Path

BASE = Path(r"D:\AiCoding\Ai-Fields\Offlineagent")
sys.path.insert(0, str(BASE.parent))
sys.path.insert(0, str(BASE))

from Offlineagent.tool_layer import file_tools, shell_tools, document_tools, db_tools, browser_tools
from Offlineagent.tool_layer.tool_registry import ToolRegistry
from Offlineagent.prompt_layer.skill_loader import load_all_skills, Skill
from Offlineagent.orchestrator.state_manager import StateManager

PASS, FAIL = 0, 0

def test(name, result, expect_ok=True):
    global PASS, FAIL
    ok = bool(result) if expect_ok else not bool(result)
    if ok:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}: {str(result)[:100]}")

def main():
    global PASS, FAIL
    print("=" * 60)
    print("OfflineAgent Smoke Tests")
    print("=" * 60)

    # === Load minimal config ===
    config = {
        "skills": {"paths": ["./skills"]},
        "tools": {
            "enabled": [
                "read_file", "write_file", "list_dir", "search_code",
                "shell", "read_template", "write_output",
                "write_docx", "write_xlsx", "write_pptx",
                "web_fetch",
                "db_connect", "db_list_tables", "db_list_procedures",
                "db_get_procedure", "db_query", "db_status", "db_disconnect",
                "browser_status",
            ],
            "shell": {"allowed": ["echo", "dir", "ls", "python", "git", "mvn"]},
            "file_write": {"require_confirm": False},
            "browser": {"enabled": False, "engine": "playwright"},
        },
        "agent": {"max_tokens_estimate": 128000, "compression": {"enabled": False}},
    }

    file_tools.set_file_base(BASE)

    # ====================================================================
    # 1. FILE TOOLS
    # ====================================================================
    print("\n--- 1. File Tools ---")

    # read_file
    r = file_tools.read_file(str(BASE / "config.yaml"))
    test("read_file (config.yaml)", r and "llm:" in r)

    r = file_tools.read_file(str(BASE / "nonexistent.xyz"))
    test("read_file (nonexistent)", "Error" in r or "not found" in r.lower())

    # list_dir
    r = file_tools.list_dir(str(BASE))
    test("list_dir (base)", "server.py" in r or "agent.py" in r)

    r = file_tools.list_dir(str(BASE / "nonexistent"))
    test("list_dir (nonexistent)", "Error" in r or "not found" in r.lower())

    # search_code
    r = file_tools.search_code("def shutdown_handler", str(BASE / "server.py"))
    test("search_code (shutdown_handler)", r and "shutdown_handler" in r)

    r = file_tools.search_code("ZZZ_NO_MATCH_PATTERN_999", str(BASE / "server.py"))
    test("search_code (no match)", r == "" or "No matches" in str(r))

    # write_file (temp)
    tmp = BASE / "tests" / "_smoke_test_tmp.txt"
    r = file_tools.write_file(str(tmp), "hello smoke test")
    test("write_file", r and "OK" in r.upper() if r else False)
    if tmp.exists():
        tmp.unlink()

    # ====================================================================
    # 2. SHELL TOOLS
    # ====================================================================
    print("\n--- 2. Shell Tools ---")

    r = shell_tools.shell("echo hello", allowed_commands=["echo"])
    test("shell (echo)", r and "hello" in r)

    r = shell_tools.shell("dir", allowed_commands=["echo", "dir", "ls"])
    test("shell (dir)", r and len(r) > 10)

    # Blocked command
    r = shell_tools.shell("format C:", allowed_commands=["echo"])
    test("shell (blocked)", "blocked" in str(r).lower())

    # ====================================================================
    # 3. DOCUMENT TOOLS
    # ====================================================================
    print("\n--- 3. Document Tools ---")

    # read_template (.md)
    md_tpl = BASE / "templates"
    md_tpl.mkdir(parents=True, exist_ok=True)
    tpl_path = md_tpl / "_smoke_test_tpl.md"
    tpl_path.write_text("# {{TITLE}}\n\n{{BODY}}", encoding="utf-8")
    r = document_tools.read_template(str(tpl_path), BASE)
    test("read_template (md)", r and "{{TITLE}}" in str(r))
    tpl_path.unlink()

    # write_output
    out_path = BASE / "tests" / "_smoke_output.txt"
    r = document_tools.write_output("_smoke_output.txt", "test content", BASE / "tests")
    test("write_output", r and ("OK" in str(r).upper() or out_path.exists()))
    if out_path.exists():
        out_path.unlink()

    # write_docx (no template, should fail gracefully)
    r = document_tools.write_docx("_smoke.docx", {"KEY": "VAL"}, "", BASE / "tests")
    test("write_docx (no template)", isinstance(r, str))

    # write_xlsx (no template)
    r = document_tools.write_xlsx("_smoke.xlsx", {"KEY": "VAL"}, "", BASE / "tests")
    test("write_xlsx (no template)", isinstance(r, str))

    # write_pptx (no template)
    r = document_tools.write_pptx("_smoke.pptx", {"KEY": "VAL"}, "", BASE / "tests")
    test("write_pptx (no template)", isinstance(r, str))

    # ====================================================================
    # 4. WEB TOOLS
    # ====================================================================
    print("\n--- 4. Web Tools ---")

    r = browser_tools.web_fetch("http://localhost:1", timeout=2)
    test("web_fetch (unreachable)", r and ("Error" in r or "fail" in r.lower() or "refused" in r.lower()))

    r = browser_tools.browser_status(BASE)
    test("browser_status", isinstance(r, str))

    # ====================================================================
    # 5. DATABASE TOOLS
    # ====================================================================
    print("\n--- 5. Database Tools ---")

    # Disconnect any existing connection
    db_tools.db_disconnect()

    # db_status before connect
    r = db_tools.db_status()
    test("db_status (no conn)", isinstance(r, str) and len(r) > 10)

    # Try local MySQL - will likely fail (no server) but should not crash
    r = db_tools.db_connect("mysql", "localhost", 3306, "user1", "user1@2025", "testflowable")
    test("db_connect (localhost)", isinstance(r, str))

    # db_status after attempt
    r = db_tools.db_status()
    test("db_status (after attempt)", isinstance(r, str))

    # Try db_list_tables - may fail if not connected
    r = db_tools.db_list_tables()
    test("db_list_tables", isinstance(r, str))

    # db_query should fail gracefully
    r = db_tools.db_query("SELECT 1")
    test("db_query", isinstance(r, str))

    r = db_tools.db_list_procedures()
    test("db_list_procedures", isinstance(r, str))

    r = db_tools.db_get_procedure("nonexistent_sp")
    test("db_get_procedure", isinstance(r, str))

    db_tools.db_disconnect()
    r = db_tools.db_status()
    test("db_status (disconnected)", isinstance(r, str))

    # ====================================================================
    # 6. TOOL REGISTRY
    # ====================================================================
    print("\n--- 6. Tool Registry ---")

    registry = ToolRegistry()
    registry.register("echo", lambda **kw: f"echo: {kw}")
    test("registry.register", "echo" in registry.names())
    r = registry.dispatch("echo", {"msg": "hi"})
    test("registry.dispatch", r and "hi" in str(r))
    test("registry.names", len(registry.names()) == 1)

    # ====================================================================
    # 7. SKILL LOADER
    # ====================================================================
    print("\n--- 7. Skill Loader ---")

    skills = load_all_skills(config, BASE)
    test("load_all_skills returns list", isinstance(skills, list))
    test("load_all_skills has items", len(skills) > 0)
    print(f"       Loaded {len(skills)} skills")

    # Match skills
    from Offlineagent.prompt_layer.skill_loader import match_skills, get_skill_body
    matched = match_skills("分析这个Java项目的代码逻辑", skills, max_skills=3)
    test("match_skills (java)", isinstance(matched, list))
    print(f"       Matched {len(matched)} skills for Java query")

    # Get skill body
    if matched:
        body = get_skill_body(matched[0])
        test("get_skill_body", body and len(body) > 20)

    # ====================================================================
    # 8. STATE MANAGER
    # ====================================================================
    print("\n--- 8. State Manager ---")

    state = StateManager(max_tokens=128000)
    test("StateManager init", state.messages is not None)
    state.add_user_message("hello")
    test("StateManager add_user_message", len(state.messages) == 1)
    state.add_assistant_message("hi there")
    test("StateManager add_assistant_message", len(state.messages) == 2)

    usage = state.usage_ratio()
    test("StateManager usage_ratio", isinstance(usage, float) and 0 <= usage <= 1)

    est = state.estimate_total_tokens()
    test("StateManager estimate_total_tokens", isinstance(est, int) and est > 0)

    # ====================================================================
    # SUMMARY
    # ====================================================================
    print("\n" + "=" * 60)
    total = PASS + FAIL
    print(f"Results: {PASS}/{total} passed, {FAIL} failed")
    if FAIL == 0:
        print("ALL TESTS PASSED")
    else:
        print(f"{FAIL} TEST(S) FAILED")
    print("=" * 60)
    return FAIL == 0

if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
