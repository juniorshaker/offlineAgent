---
name: python-exception-debugging
description: Use when the user provides a Python traceback/exception, encounters a runtime error, or asks to debug a Python bug. Triggers on stack traces, "报错", "异常", "Traceback", "Error", or similar debugging requests.
---

# Python 异常调试

## Overview

系统化分析 Python traceback 和运行时异常，定位根因并给出修复方案。

## Debugging Workflow

### 1. Traceback 解析
- 从下往上读取 traceback（最后一行是实际出错位置）
- 识别异常类型（`TypeError`、`ValueError`、`AttributeError`、`KeyError`、`ImportError` 等）
- 定位：哪个文件、哪个函数、哪一行

### 2. 常见异常诊断

| 异常类型 | 常见原因 | 诊断重点 |
|---------|---------|--------|
| `TypeError` | 类型不匹配、参数数量不对 | 检查类型注解、参数传递 |
| `ValueError` | 值不合法 | 检查输入范围、格式 |
| `AttributeError` | 属性/方法不存在 | 检查对象类型、None值 |
| `KeyError` | 字典键不存在 | 检查键名拼写、`dict.get()` |
| `IndexError` | 列表索引越界 | 检查列表长度 |
| `ImportError` | 模块导入失败 | 检查环境、循环导入 |
| `NameError` | 变量未定义 | 检查作用域、拼写 |
| `RecursionError` | 递归溢出 | 检查终止条件 |
| `MemoryError` | 内存耗尽 | 检查大数据集、生成器 |

### 3. 根因分析
- 追踪错误发生的完整调用链
- 检查状态变化：什么操作导致对象进入异常状态
- 边界条件：None、空列表、0值、空字符串
- 并发问题：竞态条件、GIL 相关

### 4. 修复策略
1. 最小修复：使错误不再触发
2. 防御性编程：添加输入验证、类型检查
3. 错误处理：合适的 try-except 包装
4. 日志增强：关键路径添加日志便于下次排查

## Output Format

```markdown
## 异常概要
- 类型：[ExceptionClass]
- 位置：[file:line]
- 信息：[error message]

## 调用链
[从入口到异常的完整路径]

## 根因分析
[为什么发生 + 如何触发]

## 修复方案
[代码修改 + 说明]

## 预防措施
[避免同类问题的建议]
```

## Constraints

- 不猜测，基于 traceback 中的确切信息分析
- 如果 traceback 不完整，明确标注缺失部分
- 修复方案必须包含代码示例
