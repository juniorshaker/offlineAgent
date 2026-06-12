---
name: python-code-reading
description: Use when the user asks to analyze, review, read through, or understand Python code logic. Triggers on requests like "分析这段Python代码", "review this Python class", "帮我看看这个方法的逻辑", "梳理调用链路", or any task involving line-by-line Python code comprehension, execution flow mapping, branch analysis, and distinguishing business/utility/framework code.
---

# Python 代码通读与逻辑梳理

## Overview

逐行分析 Python 代码含义，梳理整体执行流程、正常分支、异常分支以及完整调用链路。精准区分业务代码、工具类代码、第三方框架代码，输出结构化逻辑总结。

## Analysis Checklist

按以下顺序逐项分析，每项不得跳过：

### 1. 结构识别
- 识别所有类、函数、装饰器，标注其作用域和类型（数据类/服务类/工具类/配置类/控制器类等）
- 识别所有类属性和实例属性，标注类型注解、默认值、是否类变量
- 识别所有方法/函数，标注参数列表、返回类型、是否静态方法/类方法/属性方法/异步方法

### 2. 逐行解析
- 对每个函数内部代码逐行解读，用自然语言描述每一行代码的用途
- 标注代码中的关键判断点（if/elif/else/match-case）、循环点（for/while）、异常处理点（try-except-finally）
- 标注外部调用点（函数调用、HTTP请求、数据库操作、消息队列、文件IO等）

### 3. 执行流程梳理
- 绘制从入口到出口的完整执行路径，区分主流程和辅助流程
- 列出所有正常执行分支：触发条件 → 执行步骤 → 返回结果
- 列出所有异常执行分支：触发异常类型 → 异常处理逻辑 → 最终状态

### 4. 调用链路分析
- 向上：追溯当前函数/类被谁调用（View → Service → Repository 等全路径）
- 向下：列出当前函数/类内部调用的所有方法和外部依赖
- 使用 Mermaid 流程图呈现完整调用关系

### 5. 代码分类
- 业务代码：包含业务规则、流程判断、领域逻辑的代码
- 工具类代码：通用数据处理、格式转换、字符串操作等无业务含义的代码
- 第三方框架代码：FastAPI、Django、SQLAlchemy、Pydantic 等框架内置的装饰器/类/函数

## Output Format

```markdown
## 结构概览
[表格：类名 | 类型 | 作用域 | 核心职责]

## 执行流程
[Mermaid flowchart 展示主流程]

## 正常分支
| 分支 | 触发条件 | 执行步骤 | 返回结果 |

## 异常分支
| 异常类型 | 触发场景 | 处理方式 | 最终状态 |

## 调用链路
[Mermaid graph 展示上下游依赖]

## 代码分类
- 业务代码：[具体行号与说明]
- 工具类代码：[具体行号与说明]
- 框架代码：[具体行号与说明]
```

## Constraints

- 禁止无意义重构，禁止提出与实际分析无关的优化建议
- 明确标注类、函数、属性的作用域、类型注解以及核心用途
- 对不确定的推断必须标注"[推断]"，不将猜测当结论
- 分析前先完整通读代码，不要边读边给结论

## Common Pitfalls

- 不要把 `@dataclass` / `@property` 生成的属性当成缺失代码
- 不要把依赖注入框架自动注入的对象当成未初始化的空引用
- 不要把装饰器产生的方法调用当成普通调用链分析
- 不要把重载函数的不同参数版本当成重复代码
- Python 的动态特性：注意区分 `__call__`、`__getattr__`、描述符等隐含调用
