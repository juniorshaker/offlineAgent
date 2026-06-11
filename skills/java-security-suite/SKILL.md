---
name: java-security-suite
description: Use when the user asks for a comprehensive Java security audit covering code standards, vulnerability scanning, crypto analysis, and null safety. Triggers on requests like "安全审计套装", "全面安全检查", "代码安全+加密审计", "安全规范+漏洞扫描". This suite combines java-code-standards, java-security-audit, java-crypto-audit, and java-null-safety.
---

# Java 安全审计套装

## Overview

面向代码安全的四合一分析套装。覆盖编码规范、安全漏洞、加解密审计、空指针扫描四大维度，适合安全评审、上线前安全检查、合规审计。

## Constituent Skills

按以下顺序依次加载并执行每个 skill：

1. **java-code-standards** — 编码规范与语法检测
   - 阿里巴巴 Java 开发手册安全相关规约
   - 异常处理、并发处理规范

2. **java-security-audit** — 代码安全漏洞审计
   - SQL 注入、XSS、越权
   - 敏感信息泄露、文件操作安全
   - OWASP Top 10 违反检测

3. **java-crypto-audit** — 加解密工具类深度审计
   - 算法选型（AES/RSA/SM4）
   - 密钥硬编码、弱加密
   - 编码转换一致性

4. **java-null-safety** — 空指针与边界风险扫描
   - 入参/对象/集合非空校验
   - 参数边界检查
   - 自动拆箱 NPE 风险

## Execution Order

1. 先执行 java-code-standards 获取整体规范基线
2. 并行执行 java-security-audit + java-crypto-audit（安全维度，有交叉但侧重不同）
3. 最后执行 java-null-safety（非安全问题但常与安全漏洞同行）

## Integration Guide

```markdown
# 安全审计报告

## 1. 规范基线（java-code-standards 输出中安全相关部分）

## 2. 安全漏洞（java-security-audit 输出）

## 3. 加密审计（java-crypto-audit 输出）

## 4. 空指针/边界（java-null-safety 输出）

## 安全总评
- 安全等级：Critical / High / Medium / Low
- Critical 漏洞数：X
- High 风险数：X
- 优先修复 Top 5
- 合规状态：通过 / 待整改
```

## Common Pitfalls

- java-security-audit 和 java-crypto-audit 都涉及加密相关检查，以后者专项分析为准
- java-code-standards 中的安全相关规约（如 SQL 注入检测）与 java-security-audit 可能重叠
- 安全审计的发现可能涉及业务逻辑层面的判断，需要开发人员确认
