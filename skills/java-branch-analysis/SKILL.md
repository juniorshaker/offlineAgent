---
name: java-branch-analysis
description: Use when the user asks to analyze complex conditional logic, if-else chains, switch statements, loops, recursion, or ternary operators in Java code. Triggers on requests like "分析这段代码的分支逻辑", "有哪些条件分支", "这个if-else覆盖全了吗", "会不会有逻辑冲突", "switch有没有遗漏case", "边界条件检查". Also use for exhaustive branch coverage checking and hidden bug detection.
---

# Java 复杂分支逻辑拆解

## Overview

深度解析代码内 if-else、switch、for、while、递归、三元运算符等所有条件逻辑。罗列每一条分支的触发前置条件、执行内容、最终返回结果以及边界极端场景。排查条件覆盖不全、逻辑冲突、分支冗余等隐性 BUG。

## Analysis Checklist

### 1. 全量分支枚举
- 逐条列出代码中所有决策点：if/else-if/else、switch-case、三元运算符 ?:
- 对每个 if 条件拆解为布尔子表达式，分析每个子表达式的真值表
- 对 switch 枚举所有 case 值（包括 fall-through）和 default
- 标注每个分支的执行路径和出口

### 2. 循环逻辑分析
- 识别所有 for/while/do-while/增强 for/Stream.forEach
- 分析循环入口条件、终止条件、步进逻辑
- 检测无限循环风险：终止条件永远为 true、步进逻辑缺失
- 检测提前退出：break、continue、return 在循环中的位置和触发条件
- 嵌套循环：分析内外层交互，检测是否可以提前终止外层循环

### 3. 递归逻辑分析
- 分析递归终止条件（base case）的完备性
- 检查递归深度风险（是否会 StackOverflow）
- 分析递归调用是否向 base case 收敛
- 尾递归识别与优化建议

### 4. 分支完备性检测
- 所有 if 链是否以 else 结尾（保护性编程）
- switch 是否包含 default 分支
- 条件是否为互斥且完备的集合（MECE 原则）
- 是否存在逻辑盲区（某些输入值无法匹配任何分支）

### 5. 逻辑冲突与冗余检测
- 永远不会执行的分支（dead branch）：条件恒为 false
- 永远会执行的分支（tautology）：条件恒为 true
- 重复的分支：多个分支执行相同逻辑
- 矛盾的分支：A 和 B 不能同时成立但被同时检查
- 可合并的分支：多个条件可简化为一个

### 6. 边界极端场景
- null 输入对所有分支的影响
- 空字符串、空集合、零值、负值
- 极大值、极小值、Integer.MAX_VALUE/MIN_VALUE
- 并发场景下共享变量的分支行为
- 枚举类型的 null 和未预期值

## Output Format

```markdown
## 分支全景图
[Mermaid flowchart 展示所有分支路径]

## 分支详表
| 分支ID | 触发条件 | 执行逻辑 | 返回结果 | 边界风险 |

## 循环/递归分析
| 结构 | 类型 | 入口条件 | 终止条件 | 风险 |

## 问题清单
| 严重程度 | 问题类型 | 位置 | 说明 | 修复建议 |

## 条件覆盖矩阵
| 输入组合 | 命中的分支 | 预期结果 |
```

## Common Pitfalls

- 不要把 if (obj != null && obj.getXxx()) 的短路特性当作逻辑缺陷
- 不要把设计模式中的策略/状态模式分支当作需要合并的重复分支
- switch 的 fall-through 在没有 break 时可能是故意的，需确认
- try-catch-finally 中的 return 语句会影响分支分析
