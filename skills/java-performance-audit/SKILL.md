---
name: java-performance-audit
description: Use when the user asks to audit Java code performance, find bottlenecks, or analyze time/space complexity. Triggers on requests like "性能分析", "这段代码有什么性能问题", "时间复杂度分析", "哪里慢了", "find performance bottlenecks", "内存占用分析". Also use for nested loop optimization, string concatenation issues, collection misuse, and repeated computation detection.
---

# Java 代码性能瓶颈审计

## Overview

全方位扫描 Java 代码性能问题，包含嵌套循环、无效 IO 操作、字符串低效拼接、集合选型错误、重复计算、频繁创建销毁对象等。计算核心方法时间/空间复杂度，精准定位性能短板，提供等价优化代码并讲解优化原理。

## Analysis Checklist

### 1. 时间复杂度分析
- 识别所有循环结构，标注循环层数
- 分析嵌套循环的复杂度：O(1) / O(log n) / O(n) / O(n²) / O(2ⁿ)
- 标注循环内是否有重量级操作（数据库查询、网络调用、文件 IO）
- 检测循环不变量：是否可以提取到循环外部
- Stream API 链式调用的复杂度分析（注意惰性求值）

### 2. 空间复杂度分析
- 分析对象创建频率和生命周期
- 集合初始容量是否合理（ArrayList/HashMap 扩容代价）
- 大数据量下的内存占用估算
- 递归调用的栈深度
- 缓存/缓冲区的占用

### 3. 字符串操作优化
- 循环内的 + 拼接 → StringBuilder
- 字符串常量拼接（编译期优化）vs 变量拼接
- String.format() 的性能开销
- 大量字符串匹配：使用预编译 Pattern 而非 String.matches()
- toString() 方法中避免创建大字符串

### 4. 集合选型检查
- 频繁随机访问 → ArrayList 而非 LinkedList
- 频繁插入删除 → LinkedList 而非 ArrayList
- 需要排序去重 → TreeSet 而非 HashSet + Collections.sort()
- 键值对遍历 → entrySet() 而非 keySet() + get()
- 线程安全场景 → ConcurrentHashMap 而非 Collections.synchronizedMap()
- 只读集合 → Collections.unmodifiableList() 或 List.of()

### 5. IO 与网络优化
- 使用缓冲流：BufferedInputStream/BufferedReader
- 使用 NIO 替代传统 IO（大文件场景）
- try-with-resources 确保流关闭
- 文件读取避免逐字节/逐字符
- 网络连接池配置（HttpClient 连接池）
- 避免在循环中频繁建立/关闭连接

### 6. 对象创建与 GC 友好性
- 循环内频繁 new 对象 → 对象复用/对象池
- 自动装箱/拆箱的性能损耗
- BigDecimal 创建性能（优先用 valueOf 而非 new）
- 大量临时对象导致 GC 压力
- 基本类型 vs 包装类型的选择

## Output Format

```markdown
## 性能问题清单（按严重程度排序）
| 优先级 | 问题类型 | 位置 | 当前复杂度 | 影响评估 |

## 问题详解与优化方案
### 问题1: [名称]
- 当前代码：[代码片段 + 行号]
- 问题分析：[为什么慢]
- 优化代码：[等价优化代码]
- 优化原理：[为什么快]
- 优化收益：[复杂度变化 / 预估提升]

## 总体评估
- 整体时间复杂度：
- 关键瓶颈排名：
```

## Common Pitfalls

- 不要对日志打印（log.debug）代码进行性能优化
- 不要将常量的编译期拼接（"a"+"b"）标记为性能问题
- 小数据量场景下的微优化往往不必要，标注数据量前提
- Stream API 的惰性求值可能导致误判：中间操作未执行时没有性能开销
- 不要建议用数组替代集合，除非数据量极大（10⁶+）
