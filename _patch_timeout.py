"""Patch all LLM + shell timeouts to 3600s (1 hour)"""
import sys, re

paths = [
    'config.yaml',
    'server.py',
    'agent.py',
    'orchestrator/chat_loop.py',
    'tool_layer/tool_executor.py',
    'tool_layer/shell_tools.py',
]

for path in paths:
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    original = content

    # LLM timeouts: 60, 120, 300 → 3600
    content = re.sub(r'"timeout":\s*60\b', '"timeout": 3600', content)
    content = re.sub(r'"timeout":\s*120\b', '"timeout": 3600', content)
    content = re.sub(r'"timeout":\s*300\b', '"timeout": 3600', content)
    content = re.sub(r'\.get\("timeout",\s*60\)', '.get("timeout", 3600)', content)
    content = re.sub(r'\.get\("timeout",\s*120\)', '.get("timeout", 3600)', content)
    content = re.sub(r'\.get\("timeout",\s*300\)', '.get("timeout", 3600)', content)
    content = re.sub(r'\.get\("timeout",\s*60\b', '.get("timeout", 3600', content)

    # Dynamic timeout max: 180 → 3600
    content = re.sub(r'min\(base_timeout \+ extra,\s*180\)', 'min(base_timeout + extra, 3600)', content)

    # SHELL_TIMEOUT
    content = re.sub(r'SHELL_TIMEOUT\s*=\s*60\b', 'SHELL_TIMEOUT = 3600', content)

    if content != original:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f'[OK] {path}')
    else:
        print(f'[--] {path} (no change)')

# Update tests that check specific timeout values
test_path = 'tests/test_all.py'
with open(test_path, 'r', encoding='utf-8') as f:
    content = f.read()
original = content
content = content.replace('"timeout": 300', '"timeout": 3600')
content = content.replace('"timeout": 120', '"timeout": 3600')
content = content.replace('"timeout": 60', '"timeout": 3600')
with open(test_path, 'w', encoding='utf-8') as f:
    f.write(content)
print(f'[OK] {test_path} (test expectations updated)')

# Update test_server_fixes.py
fix_path = 'tests/test_server_fixes.py'
with open(fix_path, 'r', encoding='utf-8') as f:
    content = f.read()
content = content.replace('min(base_timeout + extra, 180)', 'min(base_timeout + extra, 3600)')
with open(fix_path, 'w', encoding='utf-8') as f:
    f.write(content)
print(f'[OK] {fix_path} (dynamic timeout test updated)')
