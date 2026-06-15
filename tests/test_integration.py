"""
Integration test: DeepSeek API → run_tool_loop → tool dispatch
Uses credentials from tests/testuser.txt
"""
import sys
import json
from pathlib import Path

BASE = Path(r"D:\AiCoding\Ai-Fields\Offlineagent")
sys.path.insert(0, str(BASE.parent))

# Load credentials
cred_path = BASE / "tests" / "testuser.txt"
creds = {}
with open(cred_path) as f:
    for line in f:
        line = line.strip()
        if ':' in line:
            k, v = line.split(':', 1)
            creds[k.strip()] = v.strip()

print(f"API: {creds['url']}")
print(f"Model: {creds['model']}")

# LLM call function
def llm_fn(messages):
    import urllib.request
    import urllib.error
    data = json.dumps({
        "model": creds["model"],
        "messages": messages,
        "stream": False
    }).encode("utf-8")
    req = urllib.request.Request(
        creds["url"] + "/chat/completions",
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {creds['apikey']}"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            content = body["choices"][0]["message"]["content"]
            return content
    except urllib.error.HTTPError as e:
        return f"[LLM Error] HTTP {e.code}: {e.reason}"
    except Exception as e:
        return f"[LLM Error] {e}"

# === Test 1: Basic connectivity ===
print("\n=== Test 1: Basic connectivity ===")
resp = llm_fn([{"role": "user", "content": "Say 'hello' in one word"}])
print(f"Response: {resp[:200]}")
assert "hello" in resp.lower() or "Hello" in resp, f"Expected hello, got: {resp[:100]}"
print("[PASS] Basic LLM call works")

# === Test 2: Tool call dispatch ===
print("\n=== Test 2: Tool call dispatch ===")
resp = llm_fn([{
    "role": "system",
    "content": "You are a coding assistant. You can call tools using <tool_call><name>tool_name</name><param>value</param></tool_call>. Available tools: read_file(path)."
}, {
    "role": "user",
    "content": "Read the file at /test/hello.java"
}])
print(f"Response: {resp[:300]}")
assert "<tool_call>" in resp, f"Expected tool_call in response, got: {resp[:200]}"
assert "read_file" in resp, "Expected read_file tool"
assert "/test/hello.java" in resp or "hello.java" in resp, f"Expected path in response"
print("[PASS] LLM correctly outputs tool_call XML")

# === Test 3: Run through server's tool_parser ===
print("\n=== Test 3: Tool parser integration ===")
from Offlineagent.tool_layer.tool_parser import parse_tool_calls
calls = parse_tool_calls(resp)
print(f"Parsed calls: {[(c.name, c.params) for c in calls]}")
assert len(calls) >= 1, f"Expected at least 1 parsed call, got {len(calls)}"
assert calls[0].name == "read_file", f"Expected read_file, got {calls[0].name}"
# DeepSeek may use <param> or <path> tag - both are valid
has_path = "path" in calls[0].params or "param" in calls[0].params
assert has_path, f"Expected path/param in params, got {calls[0].params}"
print("[PASS] Tool parser extracts correct tool name and params")

# === Test 4: Full run_tool_loop with real LLM ===
print("\n=== Test 4: Full run_tool_loop ===")
from Offlineagent.tool_layer.tool_registry import ToolRegistry
from Offlineagent.orchestrator.state_manager import StateManager

registry = ToolRegistry()
_tool_results = []
def mock_read_file(path: str = ""):
    _tool_results.append(("read_file", path))
    return f"[File content] This is the content of {path}"

def mock_list_dir(path: str = "."):
    _tool_results.append(("list_dir", path))
    return f"[Dir listing] test.java, build/, README.md"

registry.register("read_file", "Read a file", mock_read_file, {"path": "str"})
registry.register("list_dir", "List directory", mock_list_dir, {"path": "str"})

state = StateManager(max_history=20, max_tokens=128000)
config = {"agent": {"tool_budget_ratio": 0.9, "cycle_detection": True, "max_tool_iterations": 50}}

# Build messages
system_prompt = """You are a coding assistant. You can use these tools:
<tool_call><name>tool_name</name><param_name>value</param_name></tool_call>
Available tools (use named XML tags for params):
- read_file: <tool_call><name>read_file</name><path>/some/file</path></tool_call>
- list_dir: <tool_call><name>list_dir</name><path>/some/dir</path></tool_call>
When you need to read a file or list a directory, use the tool. After getting results, give your final answer."""

messages = [
    {"role": "system", "content": system_prompt},
    {"role": "user", "content": "List the directory at /project/src and then tell me what you found."}
]

# Import and patch run_tool_loop
import Offlineagent.server as server_mod
original_llm_fn = server_mod._server_state.get("llm_chat_fn")

# Override the LLM function
class FakeLogger:
    def log(self, msg, level="INFO", req_id=""):
        print(f"  [{level}] {msg}")
    def info(self, msg):
        print(f"  [INFO] {msg}")

logger = FakeLogger()

server_mod._server_state["llm_chat_fn"] = llm_fn

def fake_get_active_model():
    return creds["model"]
def fake_get_active_timeout():
    return 120

server_mod._get_active_model_name = fake_get_active_model
server_mod._get_active_timeout = fake_get_active_timeout

try:
    response = server_mod.run_tool_loop(
        messages, system_prompt, state, config, registry, logger, req_id="test"
    )
    print(f"\nFinal response: {response[:500]}")
    
    # Verify tools were actually called
    print(f"\nTool calls made: {_tool_results}")
    assert len(_tool_results) >= 1, f"Expected at least 1 tool call, got {len(_tool_results)}: {_tool_results}"
    print("[PASS] run_tool_loop dispatched tools via real LLM")
    
    # Verify the final response is not an error
    assert not response.startswith("[LLM Error]"), f"Got LLM error: {response[:200]}"
    assert not response.startswith("[Timeout]"), f"Got timeout: {response[:200]}"
    print("[PASS] Final response is valid (not error/timeout)")
    
finally:
    # Restore original
    if original_llm_fn is not None:
        server_mod._server_state["llm_chat_fn"] = original_llm_fn

print(f"\n{'='*60}")
print("  ALL INTEGRATION TESTS PASSED")
print(f"{'='*60}")
