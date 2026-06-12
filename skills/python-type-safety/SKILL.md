---
name: python-type-safety
description: Use when the user asks to add Python type hints, review type safety, run mypy/pyright checks, improve type annotations, or use Pydantic/dataclass for data validation.
---

# Python 类型安全

## Overview

审计和增强 Python 代码的类型安全，使用类型注解、mypy/pyright 静态检查、Pydantic/dataclass 运行时验证。

## Checklist

### 1. 类型注解覆盖率
- 所有 public 函数/方法应有完整类型注解
- 返回值类型包括 `None` 时用 `Optional[X]` 或 `X | None`
- 可变参数：`*args: int`、`**kwargs: str`
- 泛型：`list[str]`、`dict[str, int]`、`Callable[[int], str]`

### 2. 常见类型问题
- `None` 处理：检查 `Optional` 是否正确使用
- `Any` 过度使用：应具体化类型
- 协变/逆变：`Sequence` vs `List`，`Mapping` vs `Dict`
- `TypeVar` 边界约束
- `Protocol` / `ABC` 抽象类型

### 3. 数据验证
- Pydantic：model 定义、field validator、自定义类型
- dataclass：`field(default_factory=...)`、`__post_init__` 验证
- TypedDict：结构化字典的类型安全
- `Literal`：枚举值的类型约束
- `Final`：不可变常量

### 4. mypy 配置
- `pyproject.toml` 或 `mypy.ini` 严格模式
- 第三方库 stub 包安装
- 渐进式 typing：先新代码强制，再逐步覆盖旧代码

## Output Format

```markdown
## 类型注解缺失
| 文件:行 | 缺失项 | 建议类型 |

## 类型错误
| 位置 | 问题 | 修复 |

## 数据验证改进
[Before/After 代码对比]
```

## Constraints

- 不强制要求 100% 类型覆盖
- 类型注解不应过度复杂（避免 3 层嵌套泛型）
- 关注运行时影响：类型注解不影响性能
