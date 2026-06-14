"""
Tests for Autoskill v1 — error clustering, root cause analysis, and orchestration.
"""
import sys
import json
from pathlib import Path

BASE = Path(r"D:\AiCoding\Ai-Fields\Offlineagent")
sys.path.insert(0, str(BASE.parent))

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

# ── 1. Error Clusterer ──
print("\n=== 1. Error Clusterer ===")
from Offlineagent.memory_layer.error_clusterer import (
    _classify_error, _extract_keywords, record_error,
    get_all_clusters, get_pending_clusters, mark_cluster_generated,
)
import tempfile, shutil

tmp = Path(tempfile.mkdtemp())

# Test error classification
check(_classify_error("image not supported") == "image", "classify image error")
check(_classify_error("connection refused") == "connection", "classify connection error")
check(_classify_error("HTTP 401 Unauthorized") == "auth", "classify auth error")
check(_classify_error("Timeout: did not respond within 60s") == "timeout", "classify timeout error")
check(_classify_error("some random unknown thing") == "unknown", "classify unknown error")

# Test keyword extraction
check(len(_extract_keywords("image_url not supported")) > 0, "extract image keywords")
check("image" in _extract_keywords("multimodal image not supported"), "extract multimodal")

# Test recording below threshold
r = record_error("deepseek-v3", "image not supported", "messages...", tmp, threshold=3)
check(r is None, "below threshold returns None")

r = record_error("deepseek-v3", "image not supported", "messages 2...", tmp, threshold=3)
check(r is None, "still below threshold")

# Third time triggers
r = record_error("deepseek-v3", "image not supported", "messages 3...", tmp, threshold=3)
check(r is not None, "threshold reached returns cluster")
check(r["count"] == 3, "cluster count is 3")
check(r["error_type"] == "image", "cluster error type is image")

# Verify persistence
clusters = get_all_clusters(tmp)
check(len(clusters) == 1, "1 cluster persisted")
check(clusters[0]["count"] == 3, "persisted count is 3")

# Different error doesn't affect existing cluster
r2 = record_error("deepseek-v3", "connection timeout", "other msg", tmp, threshold=3)
check(r2 is None, "different error below threshold")

clusters = get_all_clusters(tmp)
check(len(clusters) == 2, "2 clusters now")

# Mark generated
mark_cluster_generated(tmp, r["cluster_id"], "skills/_autogen/test/SKILL.md")
clusters = get_all_clusters(tmp)
img_cluster = [c for c in clusters if c["error_type"] == "image"][0]
check(img_cluster["status"] == "auto_skill_generated", "status updated to generated")

# Pending clusters
pending = get_pending_clusters(tmp)
check(len(pending) == 1, "1 pending cluster (the connection one)")

shutil.rmtree(tmp, ignore_errors=True)

# ── 2. Root Cause Analysis ──
print("\n=== 2. Root Cause Analysis ===")
from Offlineagent.memory_layer.root_cause import (
    build_root_cause_prompt, parse_root_cause_response,
)

cluster = {
    "cluster_id": "test__image__image",
    "model": "deepseek-v3",
    "error_type": "image",
    "count": 3,
    "samples": [
        {"timestamp": "2026-01-01T00:00:00", "messages_snippet": "user sent a screenshot"},
        {"timestamp": "2026-01-02T00:00:00", "messages_snippet": "user pasted image"},
        {"timestamp": "2026-01-03T00:00:00", "messages_snippet": "image_url in content"},
    ],
}

prompt = build_root_cause_prompt(cluster)
check("deepseek-v3" in prompt, "prompt contains model")
check("image" in prompt, "prompt contains error type")
check("screenshot" in prompt, "prompt contains first sample")
check("3" in prompt, "prompt contains count")

# Test JSON parsing
good_response = '''
Some text before...
{
  "root_cause": "DeepSeek does not support image inputs",
  "solution_type": "strip_content",
  "skill_name": "deepseek-image-strip",
  "skill_content": "---\\nname: deepseek-image-strip\\n---\\n\\n# Strip images before sending",
  "confidence": "high"
}
Some text after...
'''
result = parse_root_cause_response(good_response)
check(result is not None, "parsed good response")
check(result["root_cause"] == "DeepSeek does not support image inputs", "root_cause correct")
check(result["solution_type"] == "strip_content", "solution_type strip_content")
check(result["confidence"] == "high", "confidence high")

# Test skill_needed
skill_response = '{"root_cause": "Missing workflow", "solution_type": "skill_needed", "skill_name": "java-review", "skill_content": "## Instructions...", "confidence": "medium"}'
result = parse_root_cause_response(skill_response)
check(result is not None, "parsed skill_needed response")
check(result["solution_type"] == "skill_needed", "solution_type is skill_needed")

# Test bad response
check(parse_root_cause_response("") is None, "empty response returns None")
check(parse_root_cause_response("no json here") is None, "non-json returns None")
check(parse_root_cause_response('{"root_cause": "test"}') is None, "missing required fields returns None")

# Test ignore
ignore_response = '{"root_cause": "external network issue", "solution_type": "ignore", "confidence": "high"}'
result = parse_root_cause_response(ignore_response)
check(result["solution_type"] == "ignore", "ignore type works")

# ── 3. Autoskill Integration Points ──
print("\n=== 3. Integration Points ===")

# Check chat_loop.py has autoskill import
cl = (BASE / "orchestrator" / "chat_loop.py").read_text(encoding="utf-8")
check("from ..memory_layer.autoskill import on_error" in cl, "chat_loop imports autoskill")
check("_autoskill_on_error(" in cl, "chat_loop calls _autoskill_on_error")

# Check agent.py has startup scan
ag = (BASE / "agent.py").read_text(encoding="utf-8")
check("from Offlineagent.memory_layer.autoskill import check_generated_skills" in ag, "agent imports check_generated_skills")
check("check_generated_skills(base_dir, logger)" in ag, "agent calls check_generated_skills")

# Check logger has log method
lg = (BASE / "metrics" / "logger.py").read_text(encoding="utf-8")
check("def log(self, category: str, event: str, detail: str" in lg, "logger has log() method")

# ── 4. Syntax Checks ──
print("\n=== 4. Syntax Checks ===")
for fname in [
    "memory_layer/error_clusterer.py",
    "memory_layer/root_cause.py",
    "memory_layer/autoskill.py",
    "orchestrator/chat_loop.py",
    "agent.py",
    "metrics/logger.py",
]:
    try:
        compile((BASE / fname).read_text(encoding="utf-8"), fname, "exec")
        check(True, f"{fname} OK")
    except SyntaxError as e:
        check(False, f"{fname}: {e}")

# ── 5. Import Chain ──
print("\n=== 5. Import Chain ===")
try:
    from Offlineagent.memory_layer.error_clusterer import record_error
    check(True, "import error_clusterer")
except Exception as e:
    check(False, f"import error_clusterer: {e}")

try:
    from Offlineagent.memory_layer.root_cause import analyze_root_cause
    check(True, "import root_cause")
except Exception as e:
    check(False, f"import root_cause: {e}")

try:
    from Offlineagent.memory_layer.autoskill import on_error, check_generated_skills
    check(True, "import autoskill")
except Exception as e:
    check(False, f"import autoskill: {e}")

# ── Summary ──
print(f"\n{'='*60}")
print(f"  Results: {passed} passed, {failed} failed")
print(f"{'='*60}")
if failed > 0:
    sys.exit(1)
