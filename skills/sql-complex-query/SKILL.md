---
name: sql-complex-query
description: Use when the user asks for complex SQL development, multi-table JOINs, subqueries, window functions, CASE WHEN, row-column conversion, or execution plan analysis. Triggers on requests like "多表联查", "写个复杂SQL", "窗口函数怎么用", "执行计划分析", or any advanced SQL optimization task.
---

# 复杂 SQL 开发与优化

## Overview

接收业务统计、多表联查、多层子查询、数据汇总类需求，编写高性能复杂 SQL。支持 JOIN 联表、EXISTS/IN、CASE WHEN、窗口函数、分组统计、行列转换等语法。合理规划表关联顺序，规避笛卡尔积、全表扫描问题。

## 分析流程

按以下顺序逐项分析，每项不得跳过：

### 1. 需求解析
- 明确查询目标：统计维度、筛选条件、排序规则、分页需求
- 识别涉及的表和关联关系（外键、逻辑关联）
- 确定数据量级（小表 < 1万 / 中表 < 100万 / 大表 > 100万）

### 2. 表关联规划
- 确定驱动表（小表驱动大表）
- JOIN 顺序：先 JOIN 能最大程度过滤数据的表
- JOIN 类型选择：`INNER JOIN`（必须匹配）vs `LEFT JOIN`（允许空）vs `EXISTS`（只判断存在性）

### 3. 索引分析
- 列出 JOIN 字段和 WHERE 字段的索引情况
- 如果缺失关键索引，在输出中给出建索引建议
- 检查是否触发了索引失效的情况（函数、隐式转换、前导模糊）

### 4. 性能预估
- 估算扫描行数
- 判断是否存在全表扫描或笛卡尔积风险
- 给出执行计划解读要点

## 语法模式

### JOIN 联表
```sql
-- [场景] 三表联查：订单-用户-商品
SELECT o.order_no,
       u.name AS user_name,
       p.product_name,
       o.amount,
       o.created_at
FROM orders o
INNER JOIN users u ON o.user_id = u.id
INNER JOIN products p ON o.product_id = p.id
WHERE o.created_at >= ?
  AND o.deleted = 0
ORDER BY o.created_at DESC
LIMIT 50;
```

### EXISTS / IN
- `EXISTS` 适用于外表小、子表大的场景（子表有索引时高效）
- `IN` 适用于子查询结果集小的场景
- `NOT EXISTS` 优于 `NOT IN`（NOT IN 遇 NULL 会返回空）

```sql
-- [场景] EXISTS 替代 IN，利用索引
SELECT u.id, u.name
FROM users u
WHERE EXISTS (
    SELECT 1 FROM orders o
    WHERE o.user_id = u.id
      AND o.amount > 1000
)
  AND u.deleted = 0;
```

### CASE WHEN
```sql
-- [场景] 条件分类统计
SELECT t.category_id,
       COUNT(*) AS total,
       SUM(CASE WHEN t.status = 1 THEN 1 ELSE 0 END) AS active_count,
       SUM(CASE WHEN t.status = 0 THEN 1 ELSE 0 END) AS inactive_count,
       ROUND(SUM(CASE WHEN t.status = 1 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS active_rate
FROM tasks t
WHERE t.deleted = 0
GROUP BY t.category_id;
```

### 窗口函数
```sql
-- [场景] 按部门内排名
SELECT e.name,
       e.department_id,
       e.salary,
       ROW_NUMBER() OVER (PARTITION BY e.department_id ORDER BY e.salary DESC) AS rank_in_dept,
       RANK() OVER (PARTITION BY e.department_id ORDER BY e.salary DESC) AS rank_dense,
       AVG(e.salary) OVER (PARTITION BY e.department_id) AS dept_avg_salary
FROM employees e
WHERE e.deleted = 0;
```

### 行列转换
```sql
-- [场景] 行转列：按月份汇总各状态数量
SELECT DATE_FORMAT(created_at, '%Y-%m') AS month,
       SUM(CASE WHEN status = 1 THEN 1 ELSE 0 END) AS status_1,
       SUM(CASE WHEN status = 2 THEN 1 ELSE 0 END) AS status_2,
       SUM(CASE WHEN status = 3 THEN 1 ELSE 0 END) AS status_3
FROM orders
WHERE created_at >= ?
GROUP BY DATE_FORMAT(created_at, '%Y-%m')
ORDER BY month;
```

### 子查询优化
- 能用 JOIN 替代的子查询，优先用 JOIN
- 子查询结果集大时，考虑改为临时表或 JOIN
- 避免多层嵌套（>3 层），降低可读性和优化器难度

## 输出格式

```markdown
## 需求分析
[业务需求拆解，涉及表与关联关系]

## SQL 语句
\`\`\`sql
-- 完整 SQL，带注释
\`\`\`

## 执行思路说明
1. 驱动表选择：[原因]
2. JOIN 顺序：[原因]
3. 关键过滤条件：[说明]

## 索引建议
| 表 | 建议索引 | 原因 |

## 执行计划解读
- 关键节点说明
- 扫描类型（ALL/index/range/ref/eq_ref）
- 预估行数与实际偏差风险

## 风险提示
- 数据量级增长后的性能瓶颈
- 可能的锁冲突场景
```

## Constraints

- 必须规避笛卡尔积（CROSS JOIN 需有充分理由）
- 必须规避全表扫描（大数据量表至少要有 range 级别扫描）
- JOIN 字段类型必须一致，避免隐式转换
- LEFT JOIN 后 WHERE 条件写右表字段时必须注明变为 INNER JOIN 的行为
- 窗口函数必须加 ORDER BY（除不需要排序的场景）
- 对不确定的表结构注明"[需确认]"

## Common Pitfalls

- 大表 JOIN 大表未用索引 → 笛卡尔积风险
- LEFT JOIN 右表条件写在 WHERE → 退化为 INNER JOIN
- `NOT IN` 子查询含 NULL → 结果为空
- `GROUP BY` 与 `SELECT` 不一致（非聚合字段未在 GROUP BY 中）
- 窗口函数 `RANK()` vs `ROW_NUMBER()` 混用
- 子查询未加别名 → 语法错误
