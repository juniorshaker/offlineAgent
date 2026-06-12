---
name: python-code-standards
description: Use when the user asks to check Python code standards, PEP 8 compliance, code style review, naming conventions, or wants a code quality audit.
---

# Python 编码规范审查

## Overview

按 PEP 8、PEP 257、PEP 484 等标准审查 Python 代码，检测不符合规范的写法并给出修复建议。

## Checklist

### PEP 8 基础规范
- 缩进：4空格，禁止tab
- 行宽：≤79字符（代码）/ ≤72字符（文档字符串）
- 空行：顶层定义间2行，类方法间1行
- Import：每个导入独占一行，标准库 → 第三方 → 本地 分块排列
- 空格：运算符两侧、逗号后、冒号后，括号内不加空格
- 注释：`# ` 后跟空格，行内注释与代码至少2空格

### 命名规范
- 模块名：`lower_with_under.py`
- 类名：`CapWords`（PascalCase）
- 异常名：`CapWords` + `Error` 后缀
- 函数/方法/变量：`lower_with_under`
- 常量：`CAPS_WITH_UNDER`
- 私有属性/方法：`_leading_underscore`
- 内部私有：`__double_leading_underscore`（name mangling）
- 避免单字符名称（除计数器 i/j/k 和迭代变量）
- 避免 `l`、`O`、`I` 作为变量名

### 文档字符串（PEP 257）
- 所有 public 模块/类/函数必须有 docstring
- 使用三重双引号 `"""`
- 一行 docstring 的结束引号在同一行
- 多行 docstring：首行摘要 → 空行 → 详细描述
- 包含参数、返回值、异常的说明

### 类型注解（PEP 484）
- 所有 public 函数应有参数和返回值类型注解
- 使用 `typing` 模块：`List`、`Dict`、`Optional`、`Union` 等
- Python 3.10+ 可使用 `list[int]`、`dict[str, Any]`、`str | None` 等语法

## Output Format

```markdown
## 规范问题清单
| 行号 | 问题 | 违反规则 | 建议修复 |

## 命名问题
| 当前命名 | 建议命名 | 原因 |

## Import 问题
| 当前写法 | 建议写法 |

## 文档缺失
- [列表]
```

## Constraints

- 不对项目现有风格做激进改革
- 如果项目有 `.flake8` / `pyproject.toml` 配置，以其为准
- 只标记明确违规，不标记"可以更好"的主观建议
