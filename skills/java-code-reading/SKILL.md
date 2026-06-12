---
name: java-code-reading
description: Use when the user asks to analyze, review, read through, or understand Java code logic. Triggers on requests like "分析这段Java代码", "review this Java class", "帮我看看这个方法的逻辑", "梳理调用链路", or any task involving line-by-line Java code comprehension, execution flow mapping, branch analysis, and distinguishing business/utility/framework code.
triggers: "分析代码, 梳理逻辑, 看看代码, 代码做了什么, .java, 看代码, 这个方法, 这个类"
applicable: "User provides a Java file path or asks about the behavior/logic of specific Java code"
not_applicable: "General Java questions without code context, Spring/MyBatis config questions, SQL queries, build/deploy issues, performance tuning"
---

# Java 代码通读与逻辑梳理

## Overview

逐行解析 Java 代码含义，梳理整体执行流程、正常分支、异常分支以及完整调用链路。精准区分业务代码、工具类代码、第三方框架代码，输出结构化逻辑总结。

## Analysis Checklist

按以下顺序逐项分析，每项不得跳过：

### 1. 结构识别
- 识别所有类、接口、枚举，标注其访问权限（public/protected/package-private/private）和类型（实体类/服务类/工具类/配置类/控制器类等）
- 识别所有成员变量，标注作用域、类型、是否 final/static/volatile
- 识别所有方法，标注访问权限、返回类型、参数列表、是否静态/抽象/重写/重载

### 2. 逐行解析
- 对每个方法内部代码逐行解读，用自然语言描述每一行代码的用途
- 标注代码中的关键判断点（if/switch）、循环点（for/while）、异常处理点（try-catch-finally）
- 标注外部调用点（方法调用、RPC、HTTP、数据库操作、消息队列等）

### 3. 执行流程梳理
- 绘制从入口到出口的完整执行路径，区分主流程和辅助流程
- 列出所有正常执行分支：触发条件 → 执行步骤 → 返回结果
- 列出所有异常执行分支：触发异常类型 → 异常处理逻辑 → 最终状态

### 4. 调用链路分析
- 向上：追溯当前方法/类被谁调用（Controller → Service → Mapper 等全路径）
- 向下：列出当前方法/类内部调用的所有方法和外部依赖
- 使用 Mermaid 流程图呈现完整调用关系

### 5. 代码分类
- 业务代码：包含业务规则、流程判断、领域逻辑的代码
- 工具类代码：通用数据处理、格式转换、字符串操作等无业务含义的代码
- 第三方框架代码：Spring、MyBatis、Hibernate、Apache Commons 等框架内置的注解/类/方法

## Output Format

```markdown
## 结构概览
[表格：类名 | 类型 | 访问权限 | 核心职责]

## 执行流程
[Mermaid flowchart 展示主流程]

## 正常分支
| 分支 | 触发条件 | 执行步骤 | 返回结果 |

## 异常分支
| 异常类型 | 触发场景 | 处理方式 | 最终状态 |

## 调用链路
[Mermaid graph 展示上下游依赖]

## 代码分类
- 业务代码：[具体行号和说明]
- 工具类代码：[具体行号和说明]
- 框架代码：[具体行号和说明]
```

## Constraints

- 禁止无意义重构，禁止提出与实际分析无关的优化建议
- 明确标注类、方法、成员变量的作用域、访问权限以及核心用途
- 对不确定的推断必须标注 "[推断]"，不将猜测当结论
- 分析前先完整通读代码，不要边读边给结论

## Common Pitfalls

- 不要把 Lombok 生成的 getter/setter/构造器当成缺失代码
- 不要把框架自动注入的 Bean 当成未初始化的空引用
- 不要把 AOP 代理产生的方法调用当成普通调用链分析
- 不要把重载方法的不同参数版本当成重复代码
