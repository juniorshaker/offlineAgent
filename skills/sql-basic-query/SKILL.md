---
name: sql-basic-query
description: Use when the user asks to write basic MySQL SQL statements including CRUD, filtering, sorting, grouping, and pagination. Follows Alibaba SQL development standards. Triggers on requests like "写个查询SQL", "建一个增删改查", "分页查询怎么写", or any basic SQL writing task.
---

# 基础业务 SQL 编写

## Overview

作为专业数据库开发工程师，根据业务需求、表结构、字段说明编写标准 MySQL SQL 语句。严格遵循阿里 SQL 开发规范，优先考虑索引命中与执行效率。

## 编写规范

### 必须遵守
- **禁止 `SELECT *`**：必须明确列出所需字段
- **禁止不当隐式转换**：WHERE 条件中字段类型与值类型必须匹配
- **禁止滥用函数索引**：WHERE 条件中对索引字段使用函数会导致索引失效
- **字段命名**：使用 `snake_case`，避免关键字，加必要表别名
- **注释清晰**：每条 SQL 前加业务含义注释，复杂逻辑加行内注释

### 格式要求
```sql
-- [业务含义] 查询某条件下的数据
SELECT t.id,
       t.name,
       t.status
FROM table_name t
WHERE t.status = 1
  AND t.deleted = 0
ORDER BY t.id DESC
LIMIT 20;
```
- 关键字大写（SELECT/FROM/WHERE/JOIN/ORDER BY/GROUP BY/HAVING/INSERT/UPDATE/DELETE）
- 字段名小写，逗号前置换行
- 每个 AND/OR 条件独立一行
- JOIN 显式声明，不用隐式逗号连接

## 场景模板

### 1. 普通查询
- 分析 WHERE 条件中的字段是否建立了索引
- 避免 `LIKE '%xxx%'` 前导模糊查询（无法使用索引）
- 使用 `LIMIT` 限制返回行数

```sql
-- [场景] 根据用户ID查询最近订单
SELECT o.id,
       o.order_no,
       o.amount,
       o.status,
       o.created_at
FROM orders o
WHERE o.user_id = ?
  AND o.deleted = 0
ORDER BY o.created_at DESC
LIMIT 20;
```

### 2. 条件筛选
- 多条件组合查询时，将高选择性条件放在前面
- 动态条件场景使用 `<if>` 标签（MyBatis）或应用层拼接

### 3. 排序查询
- ORDER BY 字段尽量在索引中
- 多字段排序明确指定每个字段的排序方向
- 分页查询必须带 ORDER BY，否则数据顺序不稳定

### 4. 分组聚合
- GROUP BY 字段建议建索引
- HAVING 只用于聚合后过滤，聚合前过滤用 WHERE
- 聚合查询注意 NULL 值处理（COUNT 不统计 NULL）

```sql
-- [场景] 按状态统计近30天订单数量
SELECT o.status,
       COUNT(o.id) AS order_count,
       SUM(o.amount) AS total_amount
FROM orders o
WHERE o.created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)
  AND o.deleted = 0
GROUP BY o.status
HAVING order_count > 0
ORDER BY order_count DESC;
```

### 5. 分页查询
- 必须带 ORDER BY，确保翻页数据不重复
- 大数据量分页使用游标分页（`WHERE id > last_id`）而非 OFFSET

```sql
-- [场景] 游标分页查询（推荐，避免大OFFSET性能问题）
SELECT t.id,
       t.name,
       t.created_at
FROM table_name t
WHERE t.id > ?
  AND t.deleted = 0
ORDER BY t.id ASC
LIMIT 20;
```

### 6. 批量操作
- INSERT 批量使用 `VALUES (...), (...), (...)`，单次建议不超过 500 条
- UPDATE 批量使用 `WHERE id IN (...)`，建议不超过 1000 条
- 大批量操作考虑分批提交，避免长事务

```sql
-- [场景] 批量更新状态
UPDATE table_name
SET status = ?,
    updated_at = NOW()
WHERE id IN (?, ?, ?, ?, ?)
  AND deleted = 0;
```

## 输出格式

每次输出包含：

```markdown
## 需求分析
[简要描述业务需求和数据操作目标]

## SQL 语句
\`\`\`sql
-- 完整 SQL，带注释
\`\`\`

## 使用说明
- 参数说明：各占位符的业务含义
- 执行前提：需要哪些表/索引存在
- 适用场景：描述适用和不适用的情况

## 注意事项
- 索引建议：建议 WHERE/JOIN 字段建哪些索引
- 性能提示：预估数据量级下的性能表现
- 风险提示：可能的问题和规避方式
```

## Constraints

- 严禁使用 `SELECT *`
- 严禁在 WHERE 中对索引字段使用函数
- 严禁隐式类型转换（如字符串字段与数字比较）
- 须注明索引建议，说明当前 SQL 会命中哪些索引
- 对不确定的表结构或字段，标注"[需确认]"

## Common Pitfalls

- `WHERE status = 0 OR status = 1` → 应写成 `WHERE status IN (0, 1)`
- `WHERE DATE(create_time) = '2024-01-01'` → 导致索引失效，应写成范围查询
- `LIMIT 1000, 20` 大偏移 → 应改为游标分页
- `LEFT JOIN` 后 WHERE 条件写右表字段 → 变成 INNER JOIN 效果
- 字符串字段与数字直接比较 → 隐式转换导致全表扫描
