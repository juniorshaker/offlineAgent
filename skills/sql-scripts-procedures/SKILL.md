---
name: sql-scripts-procedures
description: Use when the user asks to write DDL scripts, index statements, data initialization scripts, migration scripts, stored procedures, or custom functions.
triggers: "建表, create table, 索引, index, 存储过程, stored procedure, function, 触发器, trigger, 迁移, migration, ddl"
applicable: "DDL operations, database schema design, stored procedures, migration scripts, index creation"
not_applicable: "Simple CRUD queries, SELECT/INSERT/UPDATE/DELETE statements, query optimization, SQL writing without schema changes, transaction in Spring context"
---

# 数据库脚本与存储过程编写

## Overview

根据需求编写建表语句、索引语句、数据初始化脚本、更新迁移脚本、存储过程、自定义函数。字段类型、长度、约束、主键、外键、默认值设计符合 MySQL 最佳实践。脚本兼容线上环境，增加事务控制、异常捕获、重复执行判断。

## 编写规范

### DDL 建表规范

```sql
-- ====================================
-- 表名: table_name
-- 说明: [业务含义]
-- 创建时间: YYYY-MM-DD
-- ====================================
CREATE TABLE IF NOT EXISTS table_name (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    name VARCHAR(100) NOT NULL DEFAULT '' COMMENT '名称',
    status TINYINT NOT NULL DEFAULT 0 COMMENT '状态: 0-禁用 1-启用',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    deleted TINYINT NOT NULL DEFAULT 0 COMMENT '逻辑删除: 0-未删除 1-已删除',
    PRIMARY KEY (id),
    INDEX idx_status_deleted (status, deleted),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='表注释';
```

**字段设计规则**：
- 主键：`BIGINT UNSIGNED NOT NULL AUTO_INCREMENT`
- 状态字段：`TINYINT NOT NULL DEFAULT 0`，COMMENT 中标注枚举含义
- 时间字段：`DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP`
- 逻辑删除：`TINYINT NOT NULL DEFAULT 0 COMMENT '逻辑删除: 0-未删除 1-已删除'`
- 金额字段：`DECIMAL(18,2)` 或 `BIGINT`（分），避免 `FLOAT`/`DOUBLE`
- 文本字段：可变长度用 `VARCHAR(N)`，长文本用 `TEXT`，大文本用 `MEDIUMTEXT`
- 必须指定 `COMMENT`，表级 `COMMENT` 也必须写
- 引擎默认 `InnoDB`，字符集默认 `utf8mb4`

**索引设计规则**：
- 高选择性字段优先建索引
- 联合索引遵循最左前缀原则，高选择性字段放前面
- 控制单表索引数量（建议 ≤ 5 个）
- 唯一约束用 `UNIQUE INDEX`
- 外键生产环境不建议使用物理外键，用逻辑外键 + 应用层保证

### 数据初始化脚本

```sql
-- ====================================
-- 数据初始化: 表名
-- 说明: [初始化数据说明]
-- ====================================
START TRANSACTION;

INSERT INTO table_name (id, name, status) VALUES
(1, '默认值1', 1),
(2, '默认值2', 1)
ON DUPLICATE KEY UPDATE
    name = VALUES(name),
    status = VALUES(status);

COMMIT;
```

### 数据迁移脚本

```sql
-- ====================================
-- 迁移脚本: 版本 v1.0.1
-- 说明: [迁移内容说明]
-- 执行前检查: SELECT COUNT(*) FROM old_table;
-- 执行后验证: SELECT COUNT(*) FROM new_table;
-- 回滚方案: [回滚SQL或备份说明]
-- ====================================
START TRANSACTION;

-- Step 1: 新增字段
ALTER TABLE table_name
ADD COLUMN new_field VARCHAR(200) NOT NULL DEFAULT '' COMMENT '新字段';

-- Step 2: 数据迁移
UPDATE table_name
SET new_field = CONCAT(old_field1, '-', old_field2)
WHERE old_field1 != '';

-- Step 3: 验证
-- SELECT COUNT(*) FROM table_name WHERE new_field = '';

COMMIT;
-- ROLLBACK; -- 执行失败时手动回滚
```

### 存储过程

```sql
DELIMITER //

-- ====================================
-- 存储过程: sp_procedure_name
-- 说明: [功能说明]
-- 参数:
--   IN  p_param1  BIGINT       参数1说明
--   IN  p_param2  VARCHAR(100) 参数2说明
--   OUT p_result  INT          输出结果
-- 调用示例: CALL sp_procedure_name(1, 'test', @result); SELECT @result;
-- ====================================
CREATE PROCEDURE sp_procedure_name(
    IN  p_param1  BIGINT,
    IN  p_param2  VARCHAR(100),
    OUT p_result  INT
)
BEGIN
    -- 异常处理
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        SET p_result = -1;
    END;

    START TRANSACTION;

    -- 业务逻辑
    UPDATE table_name
    SET status = 1,
        updated_at = NOW()
    WHERE id = p_param1;

    SET p_result = ROW_COUNT();

    COMMIT;
END //

DELIMITER ;
```

### 自定义函数

```sql
DELIMITER //

-- ====================================
-- 函数: fn_function_name
-- 说明: [功能说明]
-- 参数: p_input VARCHAR(100) 输入参数
-- 返回: VARCHAR(200) 处理后的字符串
-- ====================================
CREATE FUNCTION fn_function_name(p_input VARCHAR(100))
RETURNS VARCHAR(200)
DETERMINISTIC
READS SQL DATA
BEGIN
    DECLARE v_result VARCHAR(200) DEFAULT '';

    -- 业务逻辑
    SET v_result = CONCAT('[', p_input, ']');

    RETURN v_result;
END //

DELIMITER ;
```

## 输出格式

```markdown
## 需求分析
[脚本目标和执行环境]

## 执行顺序
1. [第一步] — 说明 + 风险
2. [第二步] — 说明 + 风险
3. [第三步] — 说明 + 风险

## 脚本内容

### 脚本1: xxx
\`\`\`sql
-- 完整脚本
\`\`\`

### 脚本2: xxx
\`\`\`sql
-- 完整脚本
\`\`\`

## 风险提示
| 风险点 | 影响 | 规避方式 |

## 验证方法
- 执行前检查：[SQL]
- 执行后验证：[SQL]

## 回滚方案
[回滚SQL或备份还原步骤]
```

## Constraints

- 所有 DDL 必须使用 `IF NOT EXISTS` 或 `IF EXISTS`
- 所有 DML 脚本必须包裹在 `START TRANSACTION` / `COMMIT` 中
- 金额字段禁止使用 `FLOAT` / `DOUBLE`
- 字符集统一 `utf8mb4`
- 每条 COMMENT 必须有实际描述意义，不能是空字符串
- 存储过程中必须包含异常处理 DECLARE EXIT HANDLER
- 迁移脚本必须包含执行前检查、执行后验证、回滚方案

## Common Pitfalls

- 存储过程未设置 DELIMITER → 分号导致定义中断
- DDL 未判断 `IF NOT EXISTS` → 重复执行报错
- 金额使用 FLOAT → 精度丢失
- 大批量 UPDATE 未分批 → 锁表时间过长
- 迁移脚本无事务包裹 → 部分成功部分失败无法回滚
- AUTO_INCREMENT 从 0 开始 → 需指定初始值
- 存储过程中使用 `SELECT * INTO` → 字段数不匹配时静默失败
