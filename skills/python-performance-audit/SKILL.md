---
name: python-performance-audit
description: Use when the user asks to audit Python application performance, check for bottlenecks, optimize slow Python code, or profile CPU/memory usage.
---

# Python 性能审计

## Overview

系统化审计 Python 应用性能，使用 profiling 工具定位瓶颈，针对 CPU、内存、IO 提供优化方案。

## Audit Checklist

### 1. CPU 性能
- 识别热点函数（cProfile / py-spy / line_profiler）
- 检查不必要的重计算（缺少缓存、重复调用）
- 循环优化：减少内层操作、使用局部变量绑定、预计算
- 字符串拼接：`join()` 替代 `+`，f-string 替代 `format()`
- 数据结构选择：`set`/`dict` 替代 `list` 用于查找，`deque` 替代 `list` 用于队列

### 2. 内存性能
- 对象创建开销：使用 `__slots__` 减少类实例内存
- 大列表/字典 → `array` / `numpy` / generator
- 闭包/装饰器中的循环引用 → `weakref`
- 内存泄漏检测：`tracemalloc` / `objgraph` / `memory_profiler`
- 大文件处理：分块读取（`chunk_size`），不用 `read()` 一次读入

### 3. IO 性能
- 数据库查询：N+1 问题、缺少索引、未使用批量操作
- 网络请求：`asyncio` + `aiohttp` 并发替代同步 requests
- 文件 IO：`mmap` 用于大文件、`io.BufferedReader` 缓冲
- 序列化：`orjson` / `msgspec` 替代标准 json

### 4. 并发优化
- CPU 密集型 → `multiprocessing.Pool` / `concurrent.futures.ProcessPoolExecutor`
- IO 密集型 → `asyncio` / `concurrent.futures.ThreadPoolExecutor`
- celery / rq 处理异步任务队列

## Output Format

```markdown
## 性能画像
| 函数 | 调用次数 | 总耗时 | 平均耗时 | 占比 |

## 瓶颈分析
| 问题 | 位置 | 严重程度 | 预期收益 |

## 优化方案
[Before/After 代码对比 + 性能估算]

## 风险评估
- [优化可能引入的风险]
```

## Constraints

- 先确认实际瓶颈再优化，不凭直觉做"伪优化"
- 优化后必须验证功能不受影响
- 不牺牲可读性换取微小性能提升
- 引用 profiling 数据说明优化依据
