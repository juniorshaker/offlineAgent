---
name: java-code-refactoring
description: Use when the user asks to refactor Java code, eliminate duplication, remove dead code, or improve maintainability. Triggers on requests like "重构这段代码", "有没有重复代码", "冗余代码清理", "代码优化", "extract common method", "删除无用代码". Also use for identifying duplicate methods, unused imports, deprecated code, and suggesting abstraction patterns.
---

# Java 冗余代码重构优化

## Overview

识别项目内重复代码、冗余方法、无用导入、废弃常量变量、多余逻辑分支。评估代码复用性、可维护性，针对重复代码给出抽离公共方法、封装工具类、抽象通用接口的重构方案。

## Analysis Checklist

### 1. 重复代码检测
- 完全重复的代码块（相同逻辑复制粘贴）
- 结构相同但变量名不同的代码（参数模板化）
- 不同类中相同职责的方法
- 构造函数中的重复初始化逻辑
- 相同格式的 if-else 或 try-catch 块
- 提取建议优先级：
  - 3 次以上重复 → 必须抽离
  - 2 次重复 → 建议抽离
  - 1 次 → 不处理

### 2. 冗余代码识别
- 无用的 import 语句
- 从未被调用的私有方法
- 声明但从未使用的变量/常量
- 赋值后从未读取的变量
- 永远不会执行到的代码分支（参见 java-branch-analysis）
- @Deprecated 标记但已无调用方的代码
- 注释掉的代码块
- 冗余的类型转换（如 String.toString()）

### 3. 方法级重构机会
- 过长方法（超过 80 行为警告，超过 150 行为严重）
- 参数过多（超过 5 个参数应考虑封装为对象）
- 圈复杂度过高（超过 10 建议拆分）
- 方法职责混杂（一个方法做了多件不相关的事）
- 可提取为独立方法的代码块

### 4. 类级重构机会
- 上帝类：超过 500 行或 20 个 public 方法
- 数据类：只有 getter/setter 无业务逻辑（贫血模型评估）
- 内幕交易：两个类之间过度紧密的耦合
- 平行继承体系：新增子类需要在多个层次同时新增
- 过度使用 static 方法导致难以测试

### 5. 设计改善建议
- 提取公共父类或接口
- 策略模式替代复杂的 if-else 链
- 模板方法模式抽离公共流程
- 建造者模式处理复杂对象构造
- 工厂模式管理对象创建
- 命令模式替代巨型 switch

## Output Format

```markdown
## 重复代码清单
| 位置 A | 位置 B | 重复类型 | 可提取为 |

## 冗余代码清单
| 位置 | 类型 | 说明 | 操作建议 |

## 方法重构建议
| 方法 | 问题 | 当前指标 | 重构方案 |

## 类级重构建议
| 类 | 问题 | 当前指标 | 重构方案 |
```

## Constraints

- 禁止无意义重构：没有重复就不抽离，没有复杂就不拆分
- 重构建议必须给出具体的抽取方式（方法签名/类结构）
- 不要为了设计模式而引入设计模式
- 重构不改变原有业务逻辑（等价变换）
- 评估重构的工作量和收益，标注优先级

## Common Pitfalls

- 不要把框架生成的代码（如 lombok.config/MapStruct）标记为冗余
- 不要把重载方法的不同版本标记为重复
- 不要把实现相同接口的不同类标记为重复（除非实现逻辑完全一致）
- 不要过于激进地提取工具类，把简单的一行代码封装成方法反而降低可读性
