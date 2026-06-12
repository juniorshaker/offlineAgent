---
name: java-performance-concurrency-suite
description: Use when the user asks for comprehensive Java performance and concurrency analysis covering bottlenecks, thread safety, collections, JVM memory, and SQL audit. Triggers on requests like "性能并发分析", "全面性能检查", "高并发代码审查", "性能+内存+SQL分析", "并发安全+集合优化+SQL审计". This suite combines java-performance-audit, java-concurrency-safety, java-collections-analysis, java-jvm-memory, and java-sql-audit.
---

# Java 性能并发套装

## Overview

面向高性能和并发场景的五合一分析套装。覆盖代码性能瓶颈、多线程安全、集合使用优化、JVM 内存风险、SQL 性能审计五大维度，适合核心链路优化、高并发模块审查。

## Constituent Skills

按以下顺序依次加载并执行每个 skill：

1. **java-performance-audit** — 代码性能瓶颈审计
   - 时间/空间复杂度分析
   - 嵌套循环、字符串拼接、IO 操作优化
   - 集合选型建议

2. **java-concurrency-safety** — 多线程并发安全分析
   - 线程安全、死锁、竞态条件
   - 线程池参数配置审计
   - JUC 工具类使用检查

3. **java-collections-analysis** — Java 集合专项分析
   - 集合选型深度评估
   - 遍历删除、扩容问题
   - 并发集合正确使用

4. **java-jvm-memory** — JVM 内存风险分析
   - 静态变量/ThreadLocal 内存泄漏
   - 全局缓存风险、大对象
   - GC 友好性评估

5. **java-sql-audit** — SQL 全方位安全与性能审计
   - 全表扫描、深分页、JOIN 滥用
   - Explain 执行计划模拟
   - 索引优化与改写 SQL

## Execution Order

1. 先执行 java-performance-audit 识别热点路径
2. 并行执行 java-concurrency-safety + java-jvm-memory（关注不同维度）
3. 执行 java-collections-analysis（对前几步涉及到的集合做专项分析）
4. 最后执行 java-sql-audit（数据库往往是性能瓶颈的最终落脚点）

## Integration Guide

```markdown
# 性能并发分析报告

## 1. 性能热点（java-performance-audit 输出）

## 2. 并发安全（java-concurrency-safety 输出）

## 3. 集合审计（java-collections-analysis 输出）

## 4. 内存风险（java-jvm-memory 输出）

## 5. SQL 审计（java-sql-audit 输出）

## 综合评估
- 整体性能等级：A/B/C/D
- 并发安全等级：A/B/C/D
- 内存健康度：A/B/C/D
- SQL 性能等级：A/B/C/D
- 优先级最高的 3 个修复项
```

## Common Pitfalls

- 集合选型在 performance-audit 和 collections-analysis 中都会涉及，以后者专项分析为准
- 线程池配置同时涉及 performance 和 concurrency，注意结论一致性
- SQL 性能审计需要结合前序分析的热点路径，优先审计高频调用的 SQL
