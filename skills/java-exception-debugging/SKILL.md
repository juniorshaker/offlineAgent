---
name: java-exception-debugging
description: Use when the user provides a Java exception stack trace and asks for diagnosis, root cause analysis, or fix suggestions. Triggers on requests like "这个异常怎么回事", "帮忙看下这个报错", "NullPointerException分析", "堆栈分析", "fix this exception", "debug this error". Also use for analyzing NPE, ClassCastException, ArrayIndexOutOfBoundsException, IOException, and custom business exceptions.
---

# Java 异常堆栈精准排错

## Overview

能够解读完整 Java 异常堆栈信息，包含空指针、类型转换异常、数组越界、IO 异常、自定义业务异常等。快速定位报错代码行、直接诱因、底层根因、复现场景，输出通俗易懂的问题解析与完整修复代码。

## Analysis Checklist

### 1. 堆栈解读方法
- 从下往上读（从方法调用链底层到顶层）
- 关注 `Caused by` 链：最底层的 Caused by 往往是根因
- 识别异常类型和异常消息
- 筛选出项目代码的堆栈行（忽略框架和 JDK 内部调用）
- 定位第一个属于项目代码的堆栈帧

### 2. NPE 专项分析（最高频异常）
- 定位 NPE 抛出位置
- 分析可能为 null 的引用来源：
  - 方法返回值未判空
  - 集合/Map 的 get() 返回 null
  - 自动拆箱时包装类型为 null
  - 级联调用中的任一环节为 null
  - 远程调用/RPC 返回值未判空
- 给出完整的非空判断修复方案

### 3. 常见异常诊断矩阵
- ClassCastException：类转换失败
  - 检查泛型擦除后的强制转换
  - 检查 RPC 序列化/反序列化的类版本一致性
- ArrayIndexOutOfBoundsException：数组越界
  - 检查索引计算逻辑
  - 检查集合/数组长度判断
- ConcurrentModificationException：并发修改
  - 检查 for-each 中是否执行了 add/remove
  - 检查多线程共享集合
- IllegalArgumentException：参数不合法
  - 检查参数校验逻辑
  - 检查枚举值的非法输入
- NoSuchMethodError/NoClassDefFoundError：类/方法找不到
  - 检查依赖版本冲突
  - 检查编译版本和运行版本不一致
- StackOverflowError：栈溢出
  - 检查无限递归
  - 检查循环依赖导致的循环调用
- OutOfMemoryError：内存溢出（参见 java-jvm-memory skill）

### 4. 根因追溯
- 区别直接原因（proximate cause）和根本原因（root cause）
- 关联上下游调用链排查数据来源
- 识别是否是数据问题（脏数据）而非代码问题
- 判断是否是环境问题（配置缺失、依赖版本不兼容）

### 5. 修复方案
- 每种异常给出至少两个修复方案（防御性修复 vs 根治性修复）
- 防御性：加判空/加 try-catch/加参数校验
- 根治性：修正业务逻辑/修正数据流/修正配置
- 附带完整的修复代码（可直接复制）

## Output Format

```markdown
## 异常信息摘要
- 异常类型：
- 异常消息：
- 抛出位置：

## 根因分析
1. 直接原因：[代码行 + 解释]
2. 根本原因：[上游问题 + 数据流]

## 复现场景
[具体的触发条件和步骤]

## 修复方案
### 方案A（防御性修复）
[代码 + 说明]

### 方案B（根治性修复）
[代码 + 说明]

## 堆栈关键路径
[从入口到异常位置的调用链路]
```

## Common Pitfalls

- NPE 不只是 "没判空"，要追溯到为什么会出现 null
- Caused by 链可能很长，不要止步于第一个 Caused by
- 不要忽略 Suppressed exceptions（try-with-resources 中可能携带）
- Spring 框架的异常包装（UndeclaredThrowableException/InvocationTargetException）需解包
- 不要只修异常不修根因，特别是数据问题
