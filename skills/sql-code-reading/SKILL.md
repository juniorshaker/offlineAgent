---
name: sql-code-reading
description: Use when the user asks to read through, explain, or understand SQL statements piece by piece. Triggers on requests like "解释这条SQL", "这段SQL是什么意思", "拆解SQL逻辑", "这个查询做了什么", "SQL通读", "帮我理解这个SQL". Supports native SQL, MyBatis XML SQL, and dynamic SQL. Focuses on syntax parsing, business intent, and execution order—not performance audit.
---

# SQL 代码通读与逻辑梳理

## Overview

以专业数据库工程师视角，逐段拆解 SQL 语法含义、执行顺序、查询条件、关联关系、聚合逻辑与分页规则。梳理整体业务意图、数据筛选范围与结果输出规则。用通俗语言总结核心功能，同时指出语句中的特殊语法与执行特点。

## Input Formats Supported

- 原生 SQL（SELECT/INSERT/UPDATE/DELETE/DDL）
- MyBatis XML `<select>/<insert>/<update>/<delete>` 片段（含 `<if>/<choose>/<foreach>` 等动态标签）
- 存储过程 / 函数 / 触发器 / CTE（WITH 子句）
- 混合场景

## Analysis Checklist

### 1. SQL 语句分段识别
- 识别 SQL 的核心操作类型：查询 / 写入 / 更新 / 删除 / DDL
- 将复杂 SQL 按子句拆解为独立段：
  - WITH（CTE 定义）
  - SELECT（投影列）
  - FROM（主表与 JOIN）
  - WHERE（过滤条件）
  - GROUP BY（分组维度）
  - HAVING（分组后过滤）
  - ORDER BY（排序规则）
  - LIMIT/OFFSET（分页规则）
  - UNION/INTERSECT/EXCEPT（集合操作）

### 2. 逐段语法解析
- **投影列（SELECT）**：
  - 列出所有返回字段及来源（表字段 / 表达式 / 函数 / 子查询 / 常量）
  - 标注别名（alias）及含义
  - 标注聚合函数（COUNT/SUM/AVG/MAX/MIN/GROUP_CONCAT）及其计算范围
  - 标注窗口函数（ROW_NUMBER/RANK/DENSE_RANK/LEAD/LAG）及 OVER 子句
  - 标注 DISTINCT 的去重范围
- **数据来源（FROM/JOIN）**：
  - 主表（驱动表）识别及业务含义
  - 每种 JOIN 类型的语义说明（INNER/LEFT/RIGHT/CROSS/FULL）
  - JOIN 条件及表关联逻辑
  - 子查询作为数据源的作用
- **过滤条件（WHERE）**：
  - 逐条列出每个条件的业务含义
  - AND/OR 组合逻辑的优先级
  - 范围条件（BETWEEN/IN/LIKE/>/</>=）的数据筛选意图
  - NULL 处理条件（IS NULL/IS NOT NULL/COALESCE/IFNULL）
- **分组聚合（GROUP BY/HAVING）**：
  - 分组维度的业务含义（按什么维度统计）
  - HAVING 与 WHERE 的分工（分组前过滤 vs 分组后过滤）
  - 聚合函数结果与分组维度的对应关系
- **排序与分页（ORDER BY/LIMIT）**：
  - 排序字段和方向
  - 分页的起始位置和页大小
  - 排序与分页的业务场景（Top N / 分页浏览 / 排行榜）
- **集合操作（UNION 等）**：
  - UNION vs UNION ALL 的语义差异
  - 各子查询的职责分工

### 3. 执行顺序梳理
按 SQL 逻辑执行顺序（非书写顺序）梳理：

```
FROM → JOIN → WHERE → GROUP BY → HAVING → SELECT → DISTINCT → ORDER BY → LIMIT
```

对每步说明：输入数据是什么 → 做了什么操作 → 输出数据是什么

### 4. 业务意图总结
- 用 1-3 句通俗语言描述"这条 SQL 在做什么"
- 标注数据筛选范围（查询哪个时间范围、哪些状态、哪些类型）
- 标注结果输出规则（返回什么字段、按什么排序、多少条）
- 如果是写入/更新/删除，说明影响范围

### 5. 特殊语法与执行特点
- 标注 MySQL 特有的语法（如 `ON DUPLICATE KEY UPDATE`、`REPLACE INTO`）
- 标注窗口函数、CTE、LATERAL JOIN 等高级特性
- 标注可能导致意外行为的语法（如 LEFT JOIN + WHERE 右表条件的退化）
- 标注动态 SQL（MyBatis `<if>/<choose>`）的分支组合
- 标注子查询的相关性（关联子查询 vs 非关联子查询）

## Output Format

```markdown
## SQL 基本信息
- 操作类型：[SELECT/INSERT/UPDATE/DELETE/DDL]
- 涉及表：[表名列表]
- 复杂度评估：[简单/中等/复杂]（依据：JOIN 数量、子查询层级、聚合层级）

## 逐段拆解

### SELECT 投影列
| 字段/表达式 | 来源 | 业务含义 |

### FROM / JOIN 数据源
| 表/子查询 | 别名 | 角色 | JOIN 类型 | JOIN 条件 |

### WHERE 过滤条件
| 条件 | 业务含义 | 数据范围 |

### GROUP BY / HAVING
- 分组维度：
- 聚合计算：

### ORDER BY / LIMIT
- 排序规则：
- 分页规则：

## 执行顺序流程
1. FROM: [描述]
2. JOIN: [描述]
3. WHERE: [描述]
...
N. LIMIT: [描述]

## 业务意图
[1-3 句核心功能描述]

## 特殊语法与注意事项
- [特殊点 1]
- [特殊点 2]
```

## Common Pitfalls

- 不要把 SQL 语法解析和性能分析混淆，本 skill 不做 Explain/索引建议（那是 sql-code-audit 的工作）
- MyBatis 动态 SQL 的 `<if>` 分支可能导致实际执行的 SQL 有多种形态，逐一标注
- LEFT JOIN 的 WHERE 条件写在 ON 还是 WHERE 中语义完全不同
- 子查询在 SELECT 中与在 FROM 中的执行方式不同（标量子查询 vs 派生表）
