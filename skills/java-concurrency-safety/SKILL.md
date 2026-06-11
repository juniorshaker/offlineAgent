---
name: java-concurrency-safety
description: Use when the user asks to analyze Java multi-threading code, thread safety, deadlock risks, race conditions, or thread pool configuration. Triggers on requests like "线程安全分析", "有没有并发问题", "检查死锁", "线程池配置对了吗", "race condition check", "CompletableFuture用得对吗". Also use for analyzing synchronized blocks, Lock usage, CountDownLatch patterns, and concurrent data structures.
---

# Java 多线程并发安全分析

## Overview

分析 Thread、线程池、synchronized、Lock、CountDownLatch、CompletableFuture 等并发相关代码。排查线程不安全、死锁、活锁、竞态条件、线程池参数配置错误、任务拒绝等线上高频并发问题，给出标准化修复方案。

## Analysis Checklist

### 1. 线程安全基础检查
- 共享可变状态：多个线程是否同时读写同一变量（无同步）
- 复合操作的原子性：check-then-act 和 read-modify-write 是否有竞态
- 64 位值的原子性：long/double 在 32 位 JVM 上的非原子写入
- 发布逸出：对象在构造完成前被其他线程访问
- 指令重排序的影响：是否存在需要 volatile 但未声明的字段

### 2. synchronized 与 Lock 分析
- synchronized 锁的对象是否正确（类锁 vs 实例锁）
- 锁的范围是否恰当（锁粗化 vs 锁细化）
- 可重入性是否被正确利用
- Lock 的 tryLock 超时和中断处理
- 是否存在嵌套锁可能导致死锁
- ReadWriteLock 的读锁和写锁使用是否正确
- synchronized 方法上的 @Transactional 注意锁和事务的交互

### 3. 线程池分析
- 是否使用了 Executors 创建线程池（禁止，阿里巴巴规约）
- ThreadPoolExecutor 参数分析：
  - corePoolSize / maximumPoolSize 是否合理
  - keepAliveTime 设置
  - 工作队列类型（无界 LinkedBlockingQueue 风险）
  - RejectedExecutionHandler 策略（AbortPolicy/CallerRunsPolicy/DiscardPolicy）
- 线程命名是否清晰
- 任务提交后是否有 Future.get() 超时处理
- shutdown() vs shutdownNow() 的调用时机
- ForkJoinPool 和 parallelStream 的使用场景和限制

### 4. 死锁/活锁/饥饿检测
- 死锁四要素：互斥、持有并等待、不可剥夺、循环等待
- 多个锁的获取顺序是否一致
- 嵌套锁的层级关系
- CompletableFuture 的 join()/get() 循环依赖
- 活锁：线程不断重试但无法推进
- 饥饿：高优先级线程长期占用资源

### 5. JUC 工具类使用检查
- CountDownLatch：countDown 是否在所有路径被调用（包括异常）
- CyclicBarrier：await 超时后的处理
- Semaphore：acquire/release 的配对和 finally 释放
- CompletableFuture：
  - 线程池参数传递（thenApplyAsync 等未指定 executor 使用 ForkJoinPool）
  - 异常处理：exceptionally/whenComplete/handle 的区别
  - 组合操作：thenCombine/allOf/anyOf 的正确使用
- ConcurrentHashMap：computeIfAbsent 的原子性边界
- Atomic 类：compareAndSet 的循环重试

### 6. volatile 与 final 语义
- volatile 保证可见性和禁止指令重排序，但不保证原子性
- 双重校验锁（DCL）单例中 volatile 的必要性
- final 字段的安全发布保证
- happens-before 关系的建立

## Output Format

```markdown
## 并发问题清单（按严重程度排序）
| 优先级 | 问题类型 | 位置 | 并发场景 | 风险描述 |

## 问题详解与修复方案
### 问题1: [名称]
- 当前代码 + 行号
- 并发风险分析
- 复现场景
- 修复代码

## 线程池配置审计
| 线程池 | coreSize | maxSize | 队列 | 拒绝策略 | 问题 |
```

## Common Pitfalls

- Spring 单例 Bean 的成员变量天然是共享状态，需注意线程安全
- SimpleDateFormat 线程不安全，应改用 DateTimeFormatter 或 ThreadLocal 包装
- HashMap 在多线程 put 时可能导致死循环（JDK7 头插法），应改用 ConcurrentHashMap
- parallelStream 使用公共 ForkJoinPool，注意阻塞操作的影响
- volatile 不能替代 synchronized 用于复合操作
