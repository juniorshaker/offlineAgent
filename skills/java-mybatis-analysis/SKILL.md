---
name: java-mybatis-analysis
description: Use when the user asks to analyze MyBatis or MyBatis-Plus code, Mapper interfaces, XML SQL, LambdaQueryWrapper, pagination, or join queries. Triggers on requests like "MyBatis代码分析", "这个SQL有注入风险吗", "分页为什么不生效", "字段映射不对", "Mapper XML检查", "动态SQL逻辑". Also use for SQL injection detection, pagination failure diagnosis, and query optimization.
---

# MyBatis & MyBatis-Plus 代码分析

## Overview

解析 Mapper 接口、XML 原生 SQL、LambdaQueryWrapper、分页插件、联表查询相关代码。排查 SQL 注入隐患、分页失效、字段映射不匹配、主键生成异常、动态 SQL 逻辑错误等问题，优化低效查询 SQL。

## Analysis Checklist

### 1. SQL 注入检测（最高优先级）
- ${} 动态拼接（字符串替换，有注入风险）vs #{}（预编译占位符）
- 动态排序字段（ORDER BY ${}）→ 必须白名单校验
- 动态表名/列名 → 必须白名单校验
- LIKE 模糊查询：CONCAT('%', #{keyword}, '%') 而非 '%${keyword}%'
- IN 查询：使用 <foreach> + #{} 而非 ${} 拼接
- 自定义 SQL 注入器是否安全

### 2. Mapper 接口分析
- 方法签名与 XML 映射的一致性（resultType/resultMap/parameterType）
- @Select/@Insert/@Update/@Delete 注解 SQL 的完整性和正确性
- 返回值类型：List<Entity> vs Entity vs int（影响行数）
- @Param 注解的必需性和正确使用
- 多参数时是否使用 @Param 或封装为对象

### 3. XML 映射分析
- namespace 与 Mapper 接口全限定名是否一致
- resultMap 的 column 与 property 映射（下划线转驼峰是否开启）
- id/result 标签的使用（id 提升性能）
- association/collection 嵌套查询的 N+1 问题
- <include> 引用的 SQL 片段是否正确
- <where>/<set>/<trim> 的动态条件处理
- <choose>/<when>/<otherwise> 的覆盖率

### 4. MyBatis-Plus 专项
- LambdaQueryWrapper 的字段引用（Lambda 表达式，类型安全）
- 分页插件配置（PaginationInnerInterceptor）是否正确
- 分页失效场景：
  - 未配置分页插件
  - 手动在 SQL 中添加 LIMIT 被插件覆盖
  - 嵌套查询导致 count 不正确
- 主键策略（IdType.AUTO/ASSIGN_ID/INPUT 等）
- 逻辑删除（@TableLogic）的配置和使用
- 自动填充（@TableField fill）的 MetaObjectHandler
- 乐观锁（@Version）的实现

### 5. 查询性能审计
- 全表扫描风险（无 WHERE 条件或条件列无索引）
- 结果集过大（无 LIMIT 或分页）
- N+1 查询问题（association/collection 的 select 属性）
- 批量操作：使用 <foreach> 批量插入/更新（注意 SQL 长度限制）
- resultMap 中不必要的关联查询
- 避免 SELECT *、指定需要的列

### 6. 配置与最佳实践
- mybatis.configuration.map-underscore-to-camel-case = true
- 是否启用二级缓存（注意脏读风险）
- 枚举类型处理器（TypeHandler）配置
- SQL 日志级别（DEBUG 级别打印 SQL 及参数）
- 数据源配置（连接池大小、超时）

## Output Format

```markdown
## SQL 注入风险
| 优先级 | 位置 | 不安全的写法 | 风险等级 | 修复方案 |

## Mapper 接口审计
| Mapper | 方法 | 返回类型 | XML匹配 | 问题 |

## 查询性能审计
| SQL/方法 | 问题 | 影响 | 优化建议 |

## 分页审计
| 查询位置 | 分页方式 | 是否生效 | 问题 |
```

## Common Pitfalls

- MyBatis-Plus 的分页插件在 3.4.0+ 需要 PaginationInnerInterceptor
- @TableField(exist = false) 标记的字段不会参与数据库映射
- MyBatis-Plus 的 saveOrUpdate 依赖主键是否为 null 判断
- <resultMap> 中的 <id> 标签影响 MyBatis 的对象缓存（影响比较判断）
- PageHelper 与 MyBatis-Plus 分页插件冲突
