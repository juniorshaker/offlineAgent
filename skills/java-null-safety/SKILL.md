---
name: java-null-safety
description: Use when the user asks to scan Java code for null pointer risks, missing null checks, boundary validation issues, or parameter validation gaps. Triggers on requests like "空指针检查", "有没有NPE风险", "参数校验全吗", "边界条件检查", "null safety scan", "入参没校验". Also use for comprehensive null safety audits including array bounds, negative parameters, and return value null handling.
---

# Java 空指针与边界风险扫描

## Overview

全局扫描代码中所有未做非空校验的入参、对象、集合、返回值。识别空指针高危位置、参数边界未校验、数组下标越界、负数入参等隐性 BUG，统一补充健壮的判空、参数校验代码。

## Analysis Checklist

### 1. 入参非空检查
- 所有 public 方法的参数是否有非空校验
- @NonNull/@NotNull 注解是否正确使用（JSR-380 Bean Validation）
- 构造器参数是否校验
- setter 方法是否需要非空校验
- @Autowired 注入的 Bean 是否需要 required = false
- 影响范围分类：
  - P0（高危）：public API 入口参数 → 必须校验
  - P1（中危）：内部方法间调用参数 → 建议校验
  - P2（低危）：私有方法参数（调用方可控）→ 可选校验

### 2. 对象/集合/数组使用前的判空
- 方法调用链：a.getB().getC() 的每一步是否可能为 null
- 集合操作前：list.size()/forEach() 前是否判空
- Map 操作：get() 返回值是否判空（特别是作为其他方法入参时）
- 数组操作：length 访问、索引访问前是否判空
- 字符串操作：equals()/startsWith() 等方法调用前是否判空
- Optional 的使用：是否滥用 Optional.of() 而非 Optional.ofNullable()

### 3. 返回值判空
- 远程调用返回值（RPC/HTTP/Dubbo）的判空
- 数据库查询结果：selectOne() 返回 null（MyBatis-Plus 可能抛异常）
- 缓存查询结果：Redis/JVM 缓存的 null 处理
- 工厂方法/单例获取方法的返回值
- Collections.emptyXxx() 返回值虽非 null 但可能为空集合

### 4. 参数边界检查
- 数值范围：
  - 数组索引：[0, length-1]
  - 集合索引：indexOf/subList 的范围
  - 正整数参数（如 pageNum >= 1, pageSize > 0）
  - 金额/价格（>= 0）
  - 百分比（0-100 或 0.0-1.0）
  - 端口号（1-65535）
- 字符串：长度上限（防止超长输入）、非空非空白
- 枚举：是否为合法的枚举值
- 日期：开始时间 <= 结束时间

### 5. 自动拆箱 NPE 风险
- 包装类型（Integer/Long/Boolean 等）直接赋值给基本类型
- 方法返回包装类型，调用方直接拆箱使用
- Map/List 中存储包装类型，取出时拆箱
- 三元运算符中的拆箱
- switch 语句中使用了包装类型的枚举

### 6. 修复策略选择
- 参数校验方式：
  - Assert 语句（仅开发阶段有效）
  - Objects.requireNonNull()（简洁）
  - if + throw new IllegalArgumentException()（可自定义消息）
  - @Valid + @NotNull（Spring Bean Validation）
  - Preconditions（Guava）
- 空集合处理：返回 Collections.emptyList() vs null
- Optional 使用：方法返回 Optional 明确表达可能为空

## Output Format

```markdown
## 空指针风险清单（按严重程度排序）
| 优先级 | 位置 | 变量/参数 | 风险场景 | 修复建议 |

## 参数边界风险
| 位置 | 参数 | 合法范围 | 当前校验 | 风险 |

## 自动拆箱 NPE 风险
| 位置 | 包装类型 | 可能为 null 的来源 | 风险 |

## 建议修复模板
[提供统一的判空工具类或校验注解使用示例]
```

## Common Pitfalls

- StringUtils.isEmpty() 和 StringUtils.isBlank() 的区别（空白字符串）
- CollectionUtils.isEmpty() 判空同时判 size() = 0
- Objects.equals(a, b) 是 null 安全的，a.equals(b) 不是
- Optional 不应该作为字段类型或方法参数
- 不要对集合参数做判空后赋空集合（可能掩盖调用方的错误）
