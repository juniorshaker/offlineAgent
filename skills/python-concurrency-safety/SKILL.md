---
name: python-concurrency-safety
description: Use when the user asks to analyze Python concurrency safety, review async/await code, threading/multiprocessing issues, race conditions, deadlocks, or GIL-related problems.
---

# Python 并发安全分析

## Overview

分析 Python 并发代码的安全性，检测竞态条件、死锁、GIL 瓶颈、协程使用不当等问题。

## Analysis Checklist

### 1. 线程安全
- 共享状态：是否用 `threading.Lock` / `RLock` 保护
- GIL 边界：IO 操作释放 GIL，CPU 密集操作持有 GIL
- 线程局部存储：`threading.local()` 正确使用
- Queue 使用：`queue.Queue` 线程安全的传递

### 2. 协程安全（asyncio）
- `async/await` 一致性：所有异步调用链是否完整
- 阻塞操作：`time.sleep()` → `asyncio.sleep()`，`requests` → `aiohttp`
- 事件循环阻塞：长时间同步操作放在 `loop.run_in_executor()`
- 协程泄漏：未 await 的协程
- 取消处理：`CancelledError` 的正确 catch 和清理

### 3. 多进程安全
- `fork` vs `spawn` 模式差异（Windows 只有 spawn）
- 共享内存：`multiprocessing.Value` / `Array` / `Manager`
- 进程池：`Pool.map` vs `Pool.imap_unordered`

### 4. 死锁检测
- 锁的获取顺序是否一致
- `RLock` 重入是否正确
- `Condition.wait()` 的超时设置
- `asyncio.gather()` 中的相互等待

# Output Format

```markdown
## 并发模型概览
[当前使用的并发方式 + 数据流图]

## 问题清单
| 位置 | 问题类型 | 严重程度 | 触发条件 |

## 修复方案
[代码修改 + 说明]

## 并发测试建议
- [如何复现和验证修复]
```

## Constraints

- 不推荐"换成另一种并发模型"的重构
- 修复方案保持与现有并发模型一致
- GIL 相关问题明确标注"受 GIL 限制"
