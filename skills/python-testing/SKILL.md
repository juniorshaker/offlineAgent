---
name: python-testing
description: Use when the user asks to write Python tests, improve test coverage, review test quality, set up pytest, or implement unit/integration/e2e testing in Python.
---

# Python 测试

## Overview

编写和维护高质量 Python 测试代码，覆盖单元测试、集成测试、端到端测试，使用 pytest 最佳实践。

## Testing Workflow

### 1. 测试策略
- 测试金字塔：单元测试(70%) > 集成测试(20%) > E2E(10%)
- 测试什么：边界条件、异常路径、状态转换、副作用
- 不测试什么：框架代码、简单 getter/setter、外部库行为

### 2. pytest 最佳实践
- fixture：`conftest.py` 管理共享 fixture，使用 scope 控制生命周期
- 参数化：`@pytest.mark.parametrize` 覆盖边界条件
- mock：`unittest.mock` / `pytest-mock`，mock 外部依赖不 mock 自身代码
- 异常测试：`pytest.raises(Exception, match="pattern")`
- 临时文件：`tmp_path` / `tmpdir` fixture

### 3. 测试模式
```python
# AAA 模式：Arrange → Act → Assert
def test_something():
    # Arrange
    obj = MyClass(param=1)
    # Act
    result = obj.do_something()
    # Assert
    assert result == expected
```

### 4. 测试覆盖率
- 行覆盖（基础） + 分支覆盖（重要）
- 关键业务逻辑 100%，工具代码 80%+
- 覆盖报告：`pytest --cov=src --cov-report=html`

### 5. 常见反模式
- 测试之间共享可变状态
- 测试外部依赖而不是 mock
- 过于复杂的测试 setup
- 测试实现细节而非行为
- 没有断言的测试

## Output Format

```markdown
## 测试缺口分析
| 模块 | 当前覆盖率 | 缺失场景 |

## 测试用例
[具体 test_ 函数代码]

## Mock 策略
[哪些需要 mock + 原因]
```

## Constraints

- 测试代码也要干净、可维护
- 每个 test 只测一件事
- 测试命名：`test_<功能>_<场景>_<期望结果>`
