---
name: java-deep-source-suite
description: Use when the user asks for deep source code analysis covering call chains, OOP design patterns, annotations/AOP, SpringBoot mechanisms, MyBatis/MyBatis-Plus code, and SQL audit. Triggers on requests like "深度源码分析", "架构分析", "设计模式分析", "Spring+MyBatis+SQL全链路分析". This suite combines java-call-chain, java-oop-patterns, java-annotation-aop, java-springboot-analysis, java-mybatis-analysis, and java-sql-audit.
---

# Java 深度源码套装

## Overview

面向源码级深度分析的六合一套装。覆盖调用链路、设计模式、注解 AOP、SpringBoot 机制、MyBatis 映射、SQL 审计六大维度，适合架构评审、技术债务评估和复杂业务模块的源码级分析。

## Constituent Skills

按以下顺序依次加载并执行每个 skill：

1. **java-call-chain** — 全链路调用依赖分析
   - 向上追溯调用方、向下拆解依赖
   - 识别循环依赖、冗余代码、耦合度评估

2. **java-oop-patterns** — 面向对象与设计模式识别
   - 继承/多态/封装分析
   - 识别 20+ 设计模式、SOLID 评估

3. **java-annotation-aop** — 注解与 AOP 反射分析
   - 自定义注解工作链路
   - AOP 切面拦截规则、失效诊断

4. **java-springboot-analysis** — SpringBoot 源码业务分析
   - Bean 生命周期、依赖注入、循环依赖
   - @Transactional 事务传播、分层架构

5. **java-mybatis-analysis** — MyBatis & MP 代码分析
   - Mapper 映射审计、分页配置
   - N+1 查询、动态 SQL 逻辑

6. **java-sql-audit** — SQL 全方位安全与性能审计
   - Explain 执行计划模拟
   - 索引/性能/注入/事务锁审计
   - 输出可直接上线的改写 SQL 与建索引语句

## Execution Order

1. 先执行 java-call-chain 绘制整体依赖拓扑
2. 并行执行 java-oop-patterns + java-annotation-aop（基于调用链上下文）
3. 执行 java-springboot-analysis（分析框架使用）
4. 执行 java-mybatis-analysis（分析数据层映射）
5. 最后执行 java-sql-audit（基于前序分析结果，深度审计实际 SQL）

## Integration Guide

```markdown
# 深度源码分析报告

## 1. 调用拓扑（java-call-chain 输出）

## 2. 设计评估（java-oop-patterns 输出）

## 3. AOP/注解分析（java-annotation-aop 输出）

## 4. SpringBoot 审计（java-springboot-analysis 输出）

## 5. 数据层分析（java-mybatis-analysis 输出）

## 6. SQL 审计（java-sql-audit 输出）

## 架构总评
- 调用链复杂度评分
- 耦合度评分
- 设计模式覆盖率
- 框架使用规范性
- 数据层安全与性能评分
```

## Common Pitfalls

- 如果项目不涉及 SpringBoot 或 MyBatis，对应的 skill 跳过并注明
- 调用链分析和设计模式分析会相互交叉引用，注意信息一致性
- java-mybatis-analysis 关注映射层，java-sql-audit 关注 SQL 层，两者互补不重复
