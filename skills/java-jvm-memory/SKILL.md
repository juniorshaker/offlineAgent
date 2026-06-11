---
name: java-jvm-memory
description: Use when the user asks about JVM memory risks, memory leaks, GC analysis, heap/stack analysis, or memory optimization from code perspective. Triggers on requests like "会不会内存泄漏", "JVM内存分析", "有没有FullGC风险", "ThreadLocal内存泄漏", "大对象问题", "堆内存溢出风险", "静态变量滥用". Also use for analyzing static variable risks, ThreadLocal leaks, and global cache issues.
---

# Java JVM 内存风险分析

## Overview

基于代码层面预判内存泄漏、频繁 FullGC、大对象溢出、堆内存溢出等风险。排查静态变量滥用、ThreadLocal 内存泄露、全局缓存失控等问题。分析代码对 JVM 内存区域的占用情况，提供内存调优建议。

## Analysis Checklist

### 1. 静态变量风险
- 静态集合（static List/Map/Set）是否只增不减
- 静态变量引用的对象生命周期是否受控
- 单例对象持有的缓存是否设置了容量上限和过期策略
- 静态常量是否过大（如静态加载的大文件内容）

### 2. ThreadLocal 内存泄漏
- ThreadLocal 是否有 remove() 调用（finally 块中）
- 线程池场景下的 ThreadLocal 清理（线程复用导致值残留）
- ThreadLocal 变量的生命周期是否与线程生命周期绑定
- ThreadLocal.withInitial() 的初始化表达式是否有副作用

### 3. 全局缓存风险
- 缓存是否设置了最大容量（LRU/LFU/时间过期）
- 是否使用弱引用或软引用作为缓存（WeakHashMap/SoftReference）
- 缓存键的设计是否合理（是否可能无限增长）
- 本地缓存 vs 分布式缓存的选型

### 4. 大对象与直接内存
- 大数组、大字符串、大集合的生命周期和引用链
- ByteBuffer.allocateDirect() 的直接内存释放（-XX:MaxDirectMemorySize）
- 大对象直接进入老年代（PretenureSizeThreshold）
- 文件读取是否一次性加载全部内容

### 5. 引用链分析
- 强引用 → 软引用 → 弱引用 → 虚引用的使用场景
- 软引用是否适合做缓存（在内存敏感场景下）
- 弱引用在 WeakHashMap 和 ThreadLocal 中的应用
- 引用队列（ReferenceQueue）的使用

### 6. GC 友好性评估
- 短生命周期对象 vs 长生命周期对象的比例
- 对象晋升老年代的速率预估
- 循环引用是否被 GC 正确处理（Java 使用可达性分析，非引用计数）
- finalize() 方法的使用（JDK9 后已废弃）

## Output Format

```markdown
## 内存风险清单（按严重程度排序）
| 优先级 | 风险类型 | 位置 | 内存区域 | 风险描述 |

## 问题详解与修复方案
### 问题1: [名称]
- 当前代码 + 行号
- 内存影响分析
- 泄漏路径
- 修复代码

## 内存使用概览
| 类型 | 变量/缓存 | 预期大小 | 生命周期 | 风险 |
```

## Common Pitfalls

- 不要把所有 static 变量都标记为内存风险
- 有明确淘汰策略的缓存（如 Guava Cache、Caffeine）不是泄漏
- Spring 的 prototype scope Bean 需要手动管理生命周期
- 不要在 finalize() 中做资源释放，使用 try-with-resources
- 日志框架的缓冲区（如 Logback AsyncAppender）满时可能导致 OOM
