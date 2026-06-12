---
name: java-sql-audit
description: Use when the user asks to audit MySQL/MariaDB SQL statements, analyze SQL performance, optimize slow queries, or review database access code. Triggers on requests like "SQL审计", "SQL优化", "这条SQL有什么问题", "Explain分析", "索引缺失检查", "全表扫描", "慢查询分析", "隐式转换", "深分页优化", "JOIN滥用". Supports native SQL, MyBatis XML, and MyBatis-Plus LambdaQueryWrapper/QueryWrapper.
---

# Java SQL 审计与优化

## Overview

以资深 DBA + 后端架构师视角，全方位审计 MySQL/MariaDB SQL 语句。支持纯原生 SQL、MyBatis XML SQL、MyBatis-Plus 条件构造器。覆盖语法、索引、性能、安全四大维度，模拟 Explain 执行计划，输出分级问题报告与可直接上线的优化方案。

## Input Formats Supported

- 纯原生 SQL（SELECT/INSERT/UPDATE/DELETE/DDL）
- MyBatis XML `<select>/<insert>/<update>/<delete>` 片段
- MyBatis-Plus `LambdaQueryWrapper` / `QueryWrapper` 链式调用
- 混合场景（XML + Wrapper + 原生 SQL 拼接）

## Analysis Checklist

### 1. 语法与字段审计
- SQL 语法错误：关键字拼写、缺少空格/逗号、括号不匹配
- 表名/字段名是否存在（根据已知 Schema 或命名规范推断）
- 字段类型与比较值类型是否匹配
- 函数使用正确性（DATE_FORMAT/IFNULL/GROUP_CONCAT 等）
- 别名（alias）冲突或缺失
- 子查询的返回列数与外层引用匹配

### 2. 索引审计
- **索引缺失**：WHERE/JOIN/ORDER BY/GROUP BY 列上无索引
- **联合索引顺序**：是否遵循最左前缀原则
- **索引失效**（全表扫描场景）：
  - WHERE 中对索引列使用函数：`WHERE DATE(create_time) = '2024-01-01'`
  - WHERE 中对索引列做运算：`WHERE id + 1 = 100`
  - 前导模糊查询：`WHERE name LIKE '%xxx'`
  - 隐式类型转换：`WHERE phone = 13800138000`（phone 为 varchar）
  - 字符集不一致导致的索引失效
  - OR 条件中部分列无索引
  - NOT IN / != / <> 在部分场景下索引失效
  - IS NULL / IS NOT NULL 不一定失效（取决于数据分布）
- **无效冗余索引**：
  - 被更宽联合索引前缀覆盖的单列索引
  - 重复索引（两个完全相同的索引）
  - 从未使用的索引

### 3. 查询性能审计
- **全表扫描**：无 WHERE 条件的 SELECT / WHERE 列无索引
- **超大 IN 集合**：IN 中元素超过 1000（MySQL 限制 + 性能衰减）
- **超深分页**：`LIMIT 100000, 20` → 建议改为游标分页或子查询定位
- **笛卡尔积**：多表查询缺少 JOIN 条件
- **JOIN 滥用**：
  - JOIN 表数量超过 5 张（复杂度警告）
  - JOIN 列类型不一致（隐式转换）
  - JOIN 列无索引
  - LEFT JOIN 中 WHERE 条件写错位置（将右表条件写在 WHERE 中导致退化为 INNER JOIN）
- **SELECT \* 滥用**：
  - 返回不需要的字段（网络开销、无法使用覆盖索引）
  - 大字段（TEXT/BLOB）被无差别查询
- **无 LIMIT 的查询**：SELECT 未限制返回行数
- **COUNT 使用**：
  - `COUNT(*)` vs `COUNT(col)` 语义区别
  - 大表 COUNT 优化（使用近似值或计数器表）
- **排序与分组**：
  - ORDER BY 使用文件排序（filesort）
  - GROUP BY 产生的临时表
  - DISTINCT 与 GROUP BY 的等价性和性能差异
- **子查询优化**：
  - 相关子查询（每行执行一次子查询）→ 改为 JOIN 或 EXISTS
  - 派生表（FROM 子句中的子查询）是否必要
  - NOT IN vs NOT EXISTS vs LEFT JOIN ... IS NULL 的性能差别

### 4. SQL 注入与安全
- 字符串拼接的 SQL（如 JDBC Statement / MyBatis ${}）
- 动态 ORDER BY / GROUP BY / 表名 未做白名单校验
- 存储过程/函数中的动态 SQL 注入
- SQL 注释注入（如 `--` 注释绕过后续条件）

### 5. 事务与锁审计
- **长事务风险**：未及时提交的事务持有锁
- **未防止锁表**：
  - DDL 操作（ALTER TABLE）未检查是否有未提交事务
  - SELECT ... FOR UPDATE 的范围过大
- **死锁隐患**：
  - 多表操作顺序不一致
  - 间隙锁（Gap Lock）导致的插入死锁
- **事务隔离级别**与业务场景的匹配
- 批量更新/删除未分批（一次更新百万行导致锁表）

### 6. Explain 执行计划模拟
对每条 SQL 模拟分析 Explain 输出，关注以下核心指标：

| 指标 | 含义 | 关注点 |
|------|------|--------|
| **type** | 访问类型 | system > const > eq_ref > ref > range > index > **ALL** |
| **key** | 使用的索引 | NULL 表示未使用索引 |
| **key_len** | 索引使用长度 | 越短说明使用的索引列越少 |
| **rows** | 扫描行数 | 预估扫描行数，越大越慢 |
| **Extra** | 额外信息 | Using filesort/Using temporary/Using where/Using index |
| **possible_keys** | 可用索引 | 与 key 对比，若 possible_keys 有值但 key 为 NULL 说明索引失效 |

## 严重等级定义

| 等级 | 标签 | 定义 |
|------|------|------|
| 🔴 严重 | Critical | SQL 注入、语法错误、笛卡尔积（线上数据灾难） |
| 🟠 高 | High | 全表扫描千万级表、无 LIMIT 查询大表、锁表风险 |
| 🟡 警告 | Warning | 索引缺失、文件排序、SELECT *、深分页、隐式转换 |
| 🔵 建议 | Suggestion | 冗余索引、可用覆盖索引优化、JOIN 可拆分 |

## Output Format

```markdown
## SQL 审计报告

### 基本信息
- SQL 来源：[原生 SQL / MyBatis XML / MyBatis-Plus Wrapper]
- 涉及表：[表名列表]
- 操作类型：[SELECT / INSERT / UPDATE / DELETE / DDL]

### 问题清单（按严重等级排序）

| 等级 | 行号/位置 | 问题类型 | 问题描述 |
|------|-----------|----------|----------|

### 问题详解

#### [等级] 问题 N：问题标题
- **当前 SQL**：[问题代码片段]
- **问题成因**：[技术原理解释]
- **线上危害**：[线上实际风险]
- **优化后 SQL**：
  ```sql
  [可直接上线的改写 SQL]
  ```
- **索引建议**：
  ```sql
  [CREATE INDEX 语句]
  ```

### 模拟 Explain
| table | type | possible_keys | key | key_len | rows | Extra |
|-------|------|---------------|-----|---------|------|-------|

### 索引变更汇总
```sql
-- 建议新增
CREATE INDEX idx_xxx ON table_name(column1, column2);
-- 建议删除（冗余）
DROP INDEX idx_yyy ON table_name;
```

### 统计摘要
- 🔴 严重: X 项
- 🟠 高: X 项
- 🟡 警告: X 项
- 🔵 建议: X 项
```

## MyBatis / MyBatis-Plus 专项

### MyBatis XML 审计补充
- `<if>/<choose>/<when>` 动态 SQL 的全组合分析
- `<foreach>` 的 IN 列表大小是否有上限
- `<include>` 引用的 SQL 片段本身是否有问题
- 参数类型（parameterType）与实际传参是否匹配

### MyBatis-Plus Wrapper 审计补充
- `.in()` 方法的集合大小检查
- `.last("LIMIT 100")` 等字符串拼接是否有注入风险
- `.apply()` 中直接拼接 SQL 片段的安全性
- 分页插件是否生效（Page 对象的正确使用）

## Common Pitfalls

- 没有表结构信息时，基于字段命名规范做合理推断，但要注明 "[基于命名推断]"
- 小表（< 1000 行）的全表扫描有时比索引回表更快，不要一刀切
- 覆盖索引虽然性能最优，但维护成本也需要考量
- MySQL 8.0 与 5.7 的优化器行为差异（如 DESC 索引、不可见索引等）
- 不要建议给所有字段都建索引，索引也有写入和维护开销
