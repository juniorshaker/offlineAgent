---
name: sql-execution-analysis
description: Use when the user asks to analyze SQL execution flow, join logic, index usage, lock/transaction behavior, or hidden risks in complex SQL. Triggers on requests like "分析这条SQL的执行链路", "这个SQL会锁表吗", "这个JOIN的执行顺序是什么", "存储过程逻辑梳理", "CTE执行分析", "触发器影响范围", "SQL执行流程". Supports single/multi-table queries, CTE, stored procedures, triggers, and complex subqueries.
---

# SQL 全链路执行分析

## Overview

全面解读单表/多表查询、联表、子查询、CTE、存储过程、触发器等各类 SQL 代码。梳理完整执行链路、表关联逻辑、条件过滤层级、聚合计算规则。分析索引使用倾向、锁机制、事务影响。识别隐藏逻辑分支、数据范围风险、语法特殊点。

## Scope

- 单表查询 / 多表联表查询
- 子查询（标量/派生表/相关子查询/EXISTS/NOT EXISTS）
- CTE（WITH 递归 / 非递归）
- 存储过程（参数/变量/游标/条件分支/循环/异常处理）
- 函数（标量函数/表值函数）
- 触发器（BEFORE/AFTER/INSTEAD OF，INSERT/UPDATE/DELETE）
- UNION/INTERSECT/EXCEPT 集合操作
- 视图（普通视图/物化视图）

## Analysis Checklist

### 1. 执行链路梳理
- 按 MySQL 优化器实际执行顺序还原完整链路
- 对多表 JOIN 标注驱动表选择与嵌套循环顺序（NLJ / BNL / hash join）
- 对子查询标注物化（materialization）或半连接（semi-join）转换
- 对 CTE 标注是否被物化（MySQL 8.0+ 默认物化）还是合并到主查询
- 对 UNION 标注各分支的执行顺序和去重时机
- 使用 Mermaid 流程图展示完整执行链路

### 2. 表关联逻辑解析
- 每个 JOIN 的语义（INNER JOIN 取交集 / LEFT JOIN 保留左表全部 / CROSS JOIN 笛卡尔积）
- 多表 JOIN 的关联链路（A → B → C 的连接顺序）
- JOIN 条件的完备性：是否所有 JOIN 都有 ON 条件
- 自关联场景的特殊处理
- JOIN 条件中 AND 和 OR 的优先级影响
- 多对多关联导致的重复行风险

### 3. 条件过滤层级
- 标注每一层过滤的发生时机和影响范围：
  - JOIN ON 条件 → 在 JOIN 时过滤（影响参与 JOIN 的行）
  - WHERE 条件 → 在 JOIN 后过滤（影响最终结果集）
  - HAVING 条件 → 在 GROUP BY 后过滤（影响分组结果）
  - 子查询内部 WHERE → 在子查询执行时过滤
- 标注过滤条件的下推（predicate pushdown）可能性
- 标注可能被优化器重排序的条件

### 4. 索引使用倾向分析
- 基于 SQL 结构预判优化器可能选择的索引
- 标注可能触发索引的场景（覆盖索引/索引条件下推 ICP/MRR）
- 标注可能不走索引的场景（函数包裹/隐式转换/前导模糊）
- 多列索引的最左前缀匹配情况
- 排序是否可以利用索引避免 filesort

### 5. 锁机制与事务影响
- DML 操作（INSERT/UPDATE/DELETE）的锁范围分析
- SELECT ... FOR UPDATE / LOCK IN SHARE MODE 的加锁行为
- 间隙锁（Gap Lock）和临键锁（Next-Key Lock）的触发条件
- 死锁风险：多表操作的不同顺序
- 事务隔离级别对查询结果的影响（可重复读 vs 读已提交）
- 长事务对 undo log 和锁持有时间的影响
- 存储过程中显式事务（START TRANSACTION/COMMIT/ROLLBACK）的分析

### 6. 隐藏逻辑与数据范围风险
- 隐式类型转换导致的索引失效或结果偏差
- NULL 在三值逻辑中的特殊行为（NULL = NULL 为 UNKNOWN）
- NOT IN + 子查询返回 NULL 导致结果为空（经典陷阱）
- LIMIT 无 ORDER BY 导致的非确定性结果
- GROUP BY 的 ONLY_FULL_GROUP_BY 模式影响
- 触发器中的隐藏副作用（级联更新/审计日志插入）
- 存储过程中的异常处理是否完整（DECLARE HANDLER）
- 字符集/排序规则不一致导致的 JOIN 问题
- 大事务中的自动提交设置

## Output Format

```markdown
## 执行链路图
[Mermaid flowchart 展示完整执行流程]

## 表关联解析
| 步骤 | 表 | 别名 | JOIN 类型 | 关联条件 | 数据量预估 |

## 条件过滤层级
| 层级 | 过滤条件 | 过滤时机 | 影响范围 | 过滤后预估行数 |

## 索引使用倾向
| 表 | 可能使用的索引 | 访问类型 | 扫描行数预估 | 风险 |

## 锁与事务分析
| 操作 | 锁类型 | 锁范围 | 持有时间 | 风险 |

## 隐藏逻辑与风险
| 风险类型 | 位置 | 具体表现 | 触发条件 | 影响 |

## 使用注意事项
1. [注意点 1]
2. [注意点 2]
...
```

## Common Pitfalls

- 执行链路分析基于 MySQL 优化器行为，不同版本（5.7/8.0）差异较大
- 索引使用倾向是预判而非确定（实际取决于统计信息和优化器决策）
- 存储过程的逻辑分支需要在运行时才能确定，静态分析只能列出可能路径
- 没有表结构信息时，索引预判基于字段命名规范做合理推断，标注 "[推断]"
- 不要把执行链路分析当成 EXPLAIN 替代品（无实际统计信息）
