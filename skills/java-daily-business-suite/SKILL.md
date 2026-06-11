---
name: java-daily-business-suite
description: Use when the user asks for a comprehensive daily Java code review covering code reading, standards, branch analysis, null safety, and exception debugging in one pass. Triggers on requests like "日常代码审查", "全面代码检查", "帮我review一下代码", "完整分析这段Java代码". This suite combines java-code-reading, java-code-standards, java-branch-analysis, java-null-safety, and java-exception-debugging.
---

# Java 日常业务套装

## Overview

日常业务开发中最常用的五合一分析套装。覆盖从代码逻辑通读到异常排错的全流程，适合日常 Code Review 和新代码提交前的自查。

## Constituent Skills

按以下顺序依次加载并执行每个 skill：

1. **java-code-reading** — 代码通读与逻辑梳理
   - 逐行解析、执行流程、调用链路
   - 区分业务代码、工具类代码、框架代码

2. **java-code-standards** — 编码规范与语法检测
   - 阿里巴巴 Java 开发手册规约扫描
   - 按错误/警告/建议三级分类

3. **java-branch-analysis** — 复杂分支逻辑拆解
   - if-else/switch/循环/递归全分支枚举
   - 条件覆盖、逻辑冲突、边界极端场景

4. **java-null-safety** — 空指针与边界风险扫描
   - 入参/对象/集合/返回值非空校验
   - 自动拆箱 NPE、参数边界检查

5. **java-exception-debugging** — 异常堆栈精准排错
   - 针对已有异常堆栈进行诊断（如有）
   - 预判潜在异常风险点

## Execution Order

1. 先执行 java-code-reading 获取整体理解
2. 并行执行 java-code-standards + java-null-safety（两者互不依赖）
3. 执行 java-branch-analysis（依赖步骤 1 的理解）
4. 最后执行 java-exception-debugging（如提供异常堆栈则诊断，否则预判风险）

## Integration Guide

将所有 skill 的输出合并为统一报告：

```markdown
# 日常业务分析报告

## 1. 代码概览（java-code-reading 输出摘要）

## 2. 规范检查（java-code-standards 输出）

## 3. 分支风险（java-branch-analysis 输出）

## 4. 空指针/边界（java-null-safety 输出）

## 5. 异常分析（java-exception-debugging 输出）

## 总结
- 发现问题总数：X
- 必须修复（Error 级）：X
- 建议修复（Warning 级）：X
- 可选优化（Suggestion 级）：X
```

## Common Pitfalls

- 各 skill 可能对同一行代码产生不同维度的发现，不要当成重复
- 如果用户只提供了特定类/方法的代码片段，完整调用链分析会受限
- 建议先确认待分析代码的边界范围（单个文件/模块/全项目）
