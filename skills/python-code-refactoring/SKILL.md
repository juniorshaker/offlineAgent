---
name: python-code-refactoring
description: Use when the user asks to refactor Python code, improve code structure, eliminate code smells, apply design patterns, or restructure legacy Python code.
---

# Python 代码重构

## Overview

系统化重构 Python 代码，识别代码坏味道，应用合适的设计模式和 Python 惯用法（Pythonic patterns），保持功能不变的前提下改善代码结构。

## Refactoring Workflow

### 1. 代码坏味道识别
- 过长函数（>50行考虑拆分）
- 过多参数（>5个考虑封装为数据类）
- 重复代码（DRY 原则）
- 过大类（单一职责原则）
- 过度耦合（依赖注入解耦）
- 魔法数字/字符串（提取为常量/枚举）
- 深层嵌套（Guard Clause / 提前返回）

### 2. Python 惯用法应用
- 列表推导式 / 生成器表达式替代显式循环
- `contextlib.contextmanager` 替代 try-finally 模式
- `dataclass` / `NamedTuple` 替代手写 __init__
- `@property` 替代 getter/setter
- `enumerate()` 替代 range(len())
- `zip()` 替代并行索引
- `collections.defaultdict` / `Counter` 替代手动字典处理
- `functools.lru_cache` 缓存计算结果
- `pathlib.Path` 替代 os.path
- 类型注解提高可读性

### 3. 设计模式适用场景
- 策略模式 → 消除 if-elif 链
- 工厂模式 → 对象创建解耦
- 装饰器模式 → 横切关注点（日志/计时/权限）
- 观察者模式 → 事件驱动架构
- 单例模式 → 配置/连接池（慎用）
- 适配器模式 → 接口兼容
- 模板方法 → 算法骨架

### 4. 重构步骤
1. 确保现有测试覆盖
2. 识别重构目标（一次只做一种重构）
3. 小步修改，每次修改后运行测试
4. 保留原有接口兼容性（或明确标注 breaking change）
5. 更新文档和类型注解

## Output Format

```markdown
## 坏味道清单
| 位置 | 问题类型 | 严重程度 | 说明 |

## 重构方案
[Before/After 代码对比]

## Pythonic 改进点
| 原代码 | 改进后 | 收益 |

## 影响范围
- 修改文件：[列表]
- 接口变化：[有/无]
- 测试状态：[全部通过/需要更新]
```

## Constraints

- 禁止改变原有功能行为
- 一次只做一种重构，保持每次修改原子化
- Python 3.8+ 语法特性优先
- 保持与项目现有代码风格一致
