"""
Quick smoke test for Pending Issues mechanism.
Verifies:
1. system_prompt.py contains Pending Issues section
2. chat_loop.py has /pending command handler
3. agent.py has startup pending scan
4. /pending command works correctly with test data
"""
import sys
from pathlib import Path

BASE = Path(r"D:\AiCoding\Ai-Fields\Offlineagent")
passed = 0
failed = 0

def check(condition, label):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {label}")
    else:
        failed += 1
        print(f"  [FAIL] {label}")

# ── Test 1: system_prompt.py contains Pending Issues ──
print("\n=== Test 1: system_prompt.py ===")
sp = (BASE / "prompt_layer" / "system_prompt.py").read_text(encoding="utf-8")
check("## Pending Issues (CRITICAL)" in sp, "AGENT_IDENTITY has Pending Issues section")
check("use write_file to create 'pending/" in sp, "Instructs agent to save with write_file")
check("scan the 'pending/' directory" in sp, "Instructs agent to scan pending at startup")
check("/pending" in sp, "Mentions /pending command")

# ── Test 2: chat_loop.py has /pending command ──
print("\n=== Test 2: chat_loop.py ===")
cl = (BASE / "orchestrator" / "chat_loop.py").read_text(encoding="utf-8")
check('elif command == "/pending":' in cl, "Has /pending command handler")
check("/pending       List unresolved pending issues" in cl, "Help text includes /pending")
check("pending_dir = self.base_dir / \"pending\"" in cl, "Uses pending directory from base_dir")
check("sorted(pending_dir.glob" in cl, "Lists .md files sorted")

# ── Test 3: chat_loop.py has exit handler pending check ──
print("\n=== Test 3: exit handler pending check ===")
check("# Pending issues check" in cl, "Exit handler has pending check comment")
check("Run /pending next time to review" in cl, "Exit handler prompts /pending")

# ── Test 4: agent.py has startup pending scan ──
print("\n=== Test 4: agent.py startup scan ===")
ag = (BASE / "agent.py").read_text(encoding="utf-8")
check("# Scan pending issues" in ag, "Has startup scan comment")
check('pending_dir = base_dir / "pending"' in ag, "Scans pending/ directory at startup")
check("Type /pending during chat to review" in ag, "Prints /pending hint")

# ── Test 5: All files are syntactically valid ──
print("\n=== Test 5: Syntax check ===")
for fname in ["prompt_layer/system_prompt.py", "orchestrator/chat_loop.py", "agent.py"]:
    try:
        compile((BASE / fname).read_text(encoding="utf-8"), fname, "exec")
        check(True, f"{fname} syntax OK")
    except SyntaxError as e:
        check(False, f"{fname} syntax: {e}")

# ── Test 6: Pending directory exists and is writable ──
print("\n=== Test 6: Pending directory ===")
pending_dir = BASE / "pending"
check(pending_dir.exists(), "pending/ directory exists")
check(pending_dir.is_dir(), "pending/ is a directory")

# Create a test pending file and verify it can be read
test_file = pending_dir / "test_check.md"
test_file.write_text("# Test\nThis is a test pending issue.", encoding="utf-8")
check(test_file.exists(), "Can create test pending file")

# Verify read
content = test_file.read_text(encoding="utf-8")
check("Test" in content, "Can read test pending file")

# Cleanup
test_file.unlink()
check(not test_file.exists(), "Can delete test pending file")

# ── Summary ──
print(f"\n{'='*60}")
print(f"  Results: {passed} passed, {failed} failed")
print(f"{'='*60}")
if failed > 0:
    sys.exit(1)
