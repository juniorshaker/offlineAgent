---
name: java-call-chain
description: Use when the user asks to trace Java method call chains, analyze dependencies, or map upstream callers and downstream dependencies. Triggers on requests like "分析调用链路", "谁调用了这个方法", "画出依赖关系图", "trace call chain", "find circular dependencies", "检查循环依赖", "identify dead code". Also use for class/interface dependency analysis and coupling evaluation.
---

# Java 全链路调用依赖分析

## Overview

针对指定 Java 类/方法向上追溯全部调用方、向下拆解底层内部依赖，生成完整调用链路图。识别项目内循环依赖、无效冗余调用、僵尸废弃代码，分析类与类、接口与实现类之间的依赖关系，评估代码耦合度。

## Analysis Checklist

### 1. 入口定位
- 确认分析目标：指定类全限定名 或 方法签名
- 收集所有调用入口：Controller 端点、定时任务、消息监听器、事件处理器、RPC 接口等
- 标注每个入口的触发方式（HTTP/MQ/Schedule/RPC）

### 2. 向上追溯（谁调用了它）
- 从目标出发向上搜索所有直接调用方
- 递归追溯间接调用方，直到达到调用链顶端
- 对每个调用方标注：调用位置（类.方法:行号）、调用频率、调用条件
- 生成逆向调用树

### 3. 向下拆解（它调用了谁）
- 列出目标方法内部的所有方法调用（包括 this.xxx()）
- 逐一展开被调用方法的内部依赖
- 标注关键节点：数据库操作、缓存操作、远程调用、文件 IO
- 生成正向依赖树

### 4. 循环依赖检测
- 扫描 A→B→C→A 形式的依赖环
- 检查 Bean 注入循环（构造器注入 vs @Lazy vs 字段注入）
- 检查包级别循环引用
- 标注循环的位置、环长度、严重程度

### 5. 冗余与废弃代码识别
- 私有方法无任何内部调用
- public 方法在项目内无调用方且非 API 端点
- 实现类接口方法体为空或仅返回 null
- 常量/枚举值从未被引用
- @Deprecated 标记的方法/类

### 6. 耦合度评估
- 统计类的直接依赖数量（出度）和反向依赖数量（入度）
- 区分依赖类型：接口依赖 vs 实现类依赖（接口依赖更优）
- 识别上帝类（入度过高，承担过多职责）
- 给出解耦建议：提取接口、拆分职责、事件驱动

## Output Format

```markdown
## 调用链路总图
[Mermaid graph LR 或 TB，展示完整链路]

## 上游调用方（谁调用它）
| 调用方 | 调用方式 | 调用条件 | 调用频率 |

## 下游依赖（它调用谁）
| 被调用方 | 调用类型 | 是否外部依赖 | 关键节点 |

## 循环依赖
| 循环路径 | 涉及类 | 严重程度 | 修复建议 |

## 冗余/僵尸代码
| 代码位置 | 类型 | 说明 |

## 耦合度评估
| 指标 | 当前值 | 评估 | 优化建议 |
```

## Common Pitfalls

- Lombok 生成的 getter/setter 不要计入调用统计
- 反射调用（Class.forName、Method.invoke）会在静态分析中遗漏，单独标注
- AOP 代理导致的方法调用链可能与源码不一致
- 框架自动生成的方法（如 MyBatis Mapper 代理）不能按普通方法分析调用关系
- Lambda 表达式和匿名内部类的方法调用需要展开分析
